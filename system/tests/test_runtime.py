"""Offline runtime regressions: no sockets, namespaces, services or nft changes."""
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

SYSTEM = Path(__file__).resolve().parents[1]
SCRIPTS = SYSTEM.parent / 'skills/operate-vps-network/scripts'
sys.path.insert(0, str(SCRIPTS))


def runtime_module(name):
    spec = importlib.util.spec_from_file_location('portable_test_' + name,
                                                SYSTEM / 'runtime' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


certificate = runtime_module('certificate')
usage = runtime_module('usage')
network = runtime_module('network')
guard = runtime_module('guard')


@unittest.skipUnless(shutil.which('openssl'), 'OpenSSL required for local certificate fixtures')
class CertificateTests(unittest.TestCase):
    """A temporary trust root is injected only into these test subprocesses."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='portable-cert-test-')
        cls.root = Path(cls.temp.name)
        cls.ca = cls.root / 'ca.pem'
        cls.ca_key = cls.root / 'ca-key.pem'
        cls.cert = cls.root / 'server.pem'
        cls.key = cls.root / 'server-key.pem'
        cls.csr = cls.root / 'server.csr'
        cls.extensions = cls.root / 'extensions.cnf'
        cls.extensions.write_text('basicConstraints=critical,CA:FALSE\n'
                                  'keyUsage=critical,digitalSignature\n'
                                  'extendedKeyUsage=serverAuth\n'
                                  'subjectAltName=DNS:sub.example.com\n')
        cls.command('req', '-x509', '-newkey', 'ed25519', '-nodes', '-days', '60',
                    '-subj', '/CN=Portable Offline Test Root', '-keyout', cls.ca_key,
                    '-out', cls.ca, '-addext', 'basicConstraints=critical,CA:TRUE')
        cls.command('req', '-new', '-newkey', 'ed25519', '-nodes', '-subj',
                    '/CN=sub.example.com', '-keyout', cls.key, '-out', cls.csr)
        cls.sign(cls.cert, 30, 1)
        for path in cls.root.iterdir():
            path.chmod(0o600)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def command(cls, *args):
        return subprocess.run(['openssl', *map(str, args)], check=True,
                              capture_output=True, timeout=15)

    @classmethod
    def sign(cls, destination, days, serial):
        cls.command('x509', '-req', '-in', cls.csr, '-CA', cls.ca, '-CAkey',
                    cls.ca_key, '-set_serial', serial, '-out', destination,
                    '-days', days, '-extfile', cls.extensions)

    def trust_fixture(self):
        return mock.patch.dict(os.environ, {'SSL_CERT_FILE': str(self.ca),
                                            'SSL_CERT_DIR': str(self.root / 'empty-trust')})

    def test_untrusted_certificate_rejected(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SSL_CERT_FILE', None)
            os.environ.pop('SSL_CERT_DIR', None)
            with self.assertRaises(subprocess.CalledProcessError):
                certificate.check(self.cert, self.key, 'sub.example.com')

    def test_matching_trusted_certificate_passes(self):
        with self.trust_fixture():
            certificate.check(self.cert, self.key, 'sub.example.com')

    def test_trusted_wrong_hostname_rejected(self):
        with self.trust_fixture(), self.assertRaises(subprocess.CalledProcessError):
            certificate.check(self.cert, self.key, 'wrong.example.com')

    def test_trusted_mismatched_key_rejected(self):
        with self.trust_fixture(), self.assertRaises(ValueError):
            certificate.check(self.cert, self.ca_key, 'sub.example.com')

    def test_trusted_near_expiry_rejected(self):
        near_expiry = self.root / 'near-expiry.pem'
        self.sign(near_expiry, 1, 2)
        with self.trust_fixture(), self.assertRaises(subprocess.CalledProcessError):
            certificate.check(near_expiry, self.key, 'sub.example.com')


class UsageSocketTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o750,
                                         st_uid=1001, st_gid=1002)
        self.socket = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o666,
                                      st_uid=1001, st_gid=1002)
        self.path = mock.MagicMock()
        self.path.__str__.return_value = '/run/vps-mihomo/control.sock'
        self.path.parent.lstat.return_value = self.directory
        self.path.lstat.return_value = self.socket
        self.stack.enter_context(mock.patch.object(usage, 'SOCKET', self.path))
        self.stack.enter_context(mock.patch.object(usage.pwd, 'getpwnam',
                                                   return_value=SimpleNamespace(pw_uid=1001)))
        self.stack.enter_context(mock.patch.object(usage.grp, 'getgrnam',
                                                   return_value=SimpleNamespace(gr_gid=1002)))
        self.transport = self.stack.enter_context(mock.patch.object(usage, 'UnixHTTP'))
        self.connection = self.transport.return_value
        self.response = self.connection.getresponse.return_value
        self.response.status = 200
        self.response.read.return_value = b'{"connections":null}'

    def assert_rejected_before_request(self):
        with self.assertRaises(ValueError):
            usage.fetch()
        self.transport.assert_not_called()

    def test_mihomo_0666_socket_allowed_inside_private_parent(self):
        self.assertEqual(usage.fetch(), {'connections': None})
        self.transport.assert_called_once_with('/run/vps-mihomo/control.sock')
        self.connection.request.assert_called_once_with('GET', '/connections')
        self.response.read.assert_called_once_with(usage.daemon.MAX_RESPONSE + 1)
        self.connection.close.assert_called_once_with()

    def test_world_traversable_parent_rejected(self):
        self.directory.st_mode = stat.S_IFDIR | 0o755
        self.assert_rejected_before_request()

    def test_group_writable_parent_rejected(self):
        self.directory.st_mode = stat.S_IFDIR | 0o770
        self.assert_rejected_before_request()

    def test_wrong_directory_owner_rejected(self):
        self.directory.st_uid = 999
        self.assert_rejected_before_request()

    def test_wrong_directory_group_rejected(self):
        self.directory.st_gid = 999
        self.assert_rejected_before_request()

    def test_symlink_directory_rejected(self):
        self.directory.st_mode = stat.S_IFLNK | 0o750
        self.assert_rejected_before_request()

    def test_regular_file_socket_rejected(self):
        self.socket.st_mode = stat.S_IFREG | 0o666
        self.assert_rejected_before_request()

    def test_symlink_socket_rejected(self):
        self.socket.st_mode = stat.S_IFLNK | 0o666
        self.assert_rejected_before_request()

    def test_wrong_socket_owner_rejected(self):
        self.socket.st_uid = 999
        self.assert_rejected_before_request()

    def test_http_failure_closes_connection(self):
        self.response.status = 403
        with self.assertRaises(ValueError):
            usage.fetch()
        self.connection.close.assert_called_once_with()

    def test_oversized_response_rejected_and_closed(self):
        self.stack.enter_context(mock.patch.object(usage.daemon, 'MAX_RESPONSE', 16))
        self.response.read.return_value = b'x' * 17
        with self.assertRaises(ValueError):
            usage.fetch()
        self.connection.close.assert_called_once_with()

    def test_invalid_json_closes_connection(self):
        self.response.read.return_value = b'not JSON'
        with self.assertRaises(ValueError):
            usage.fetch()
        self.connection.close.assert_called_once_with()


class NetworkOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.state_data = {
            'phase': 'ready',
            'tables': {'inet:vps_network': 11, 'ip:vps_nat': 12},
            'namespaces': {
                'windows': {'name': 'vps-windows', 'identity': [4, 51],
                            'host_if': 'vpn-win0', 'ifindex': 31},
                'ios': {'name': 'vps-ios', 'identity': [4, 52],
                        'host_if': 'vpn-ios0', 'ifindex': 32},
            },
        }
        self.state = mock.Mock()
        self.state.read_text.side_effect = lambda: json.dumps(self.state_data)
        self.stack.enter_context(mock.patch.object(network, 'STATE', self.state))
        self.tables = self.stack.enter_context(mock.patch.object(
            network, 'table_handles', return_value={('inet', 'vps_network'): 11,
                                                    ('ip', 'vps_nat'): 12}))
        self.identities = {'vps-windows': [4, 51], 'vps-ios': [4, 52]}
        self.stack.enter_context(mock.patch.object(
            network, 'ns_identity', side_effect=lambda name: self.identities[name]))
        self.ifindices = {'vpn-win0': 31, 'vpn-ios0': 32}
        self.get = self.stack.enter_context(mock.patch.object(
            network, 'get', side_effect=lambda *args: [{'ifindex': self.ifindices[args[-1]]}]))
        self.run = self.stack.enter_context(mock.patch.object(network, 'run'))

    def assert_no_cleanup(self):
        with self.assertRaises(ValueError):
            network.stop()
        self.run.assert_not_called()
        self.state.unlink.assert_not_called()

    def test_changed_table_handle_refuses_all_cleanup(self):
        self.tables.return_value[('inet', 'vps_network')] = 99
        self.assert_no_cleanup()

    def test_missing_table_refuses_all_cleanup(self):
        del self.tables.return_value[('ip', 'vps_nat')]
        self.assert_no_cleanup()

    def test_changed_namespace_refuses_all_cleanup(self):
        self.identities['vps-ios'] = [4, 999]
        self.assert_no_cleanup()

    def test_changed_interface_refuses_all_cleanup(self):
        self.ifindices['vpn-ios0'] = 999
        self.assert_no_cleanup()

    def test_verified_objects_only_are_deleted(self):
        network.stop()
        self.assertEqual(self.run.call_args_list, [
            mock.call('nft', 'delete', 'table', 'inet', 'vps_network'),
            mock.call('nft', 'delete', 'table', 'ip', 'vps_nat'),
            mock.call('ip', 'netns', 'delete', 'vps-windows'),
            mock.call('ip', 'netns', 'delete', 'vps-ios'),
        ])
        self.state.unlink.assert_called_once_with()

    def test_failed_delete_preserves_ownership_record(self):
        self.run.side_effect = subprocess.CalledProcessError(1, ['nft'])
        with self.assertRaises(subprocess.CalledProcessError):
            network.stop()
        self.assertEqual(self.run.call_count, 1)
        self.state.unlink.assert_not_called()

    def test_preflight_refuses_partial_start_before_commands(self):
        self.state.exists.return_value = True
        with self.assertRaises(ValueError):
            network.preflight({})
        self.get.assert_not_called()
        self.run.assert_not_called()


class GuardOwnershipTests(unittest.TestCase):
    def test_changed_table_handle_refuses_delete(self):
        state = mock.Mock()
        state.read_text.return_value = '{"handle":11}'
        with mock.patch.object(guard, 'STATE', state), \
                mock.patch.object(guard, 'table_identity', return_value=99), \
                mock.patch.object(guard.os, 'geteuid', return_value=0), \
                mock.patch.object(guard, 'run') as run, \
                mock.patch.object(sys, 'argv', ['guard.py', 'stop', '--apply']):
            with self.assertRaises(SystemExit):
                guard.main()
        run.assert_not_called()
        state.unlink.assert_not_called()


if __name__ == '__main__':
    unittest.main()
