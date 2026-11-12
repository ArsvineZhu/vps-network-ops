import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SYSTEM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SYSTEM))
import build
import config
import render


def fixture(full=False):
    site = json.loads((SYSTEM / 'examples/site.json').read_text())
    site['subscription']['enabled'] = False
    if full:
        for value in site['protocols'].values(): value['enabled'] = True
        site['tcpfp']['enabled'] = True
        site['devices'] = [
            {'id': 'laptop', 'tcp_profile': 'windows', 'udp_policy': 'deny', 'protocols': list(config.PROTOCOLS), 'ssh_direct': True},
            {'id': 'phone', 'tcp_profile': 'ios', 'udp_policy': 'direct', 'protocols': list(config.PROTOCOLS), 'ssh_direct': False}]
    secret = {'reality': {'private_key': 'A' * 43, 'public_key': 'L-V9o0fNYkMVKNqsX7spBzD_9oSvxM_C7ZCZX1jLO3Q', 'short_id': '0123456789abcdef'}, 'devices': {}, 'backends': {}}
    for index, device in enumerate(site['devices']):
        value = {'subscription_token': ('test-token-' + device['id']).ljust(40, 'x')}
        for protocol in device['protocols']:
            value[protocol] = (f'00000000-0000-4000-8000-{index + 1:012d}' if protocol == 'vless'
                               else (protocol + '-test-' + device['id']).ljust(40, 'y'))
        secret['devices'][device['id']] = value
        if device['tcp_profile'] != 'native': secret['backends'][device['tcp_profile']] = ('backend-test-' + device['tcp_profile']).ljust(40, 'z')
    return site, secret


class SchemaTests(unittest.TestCase):
    def test_minimal_valid(self):
        s, k = fixture(); config.validate_site(s); config.validate_secrets(s, k)

    def test_all_protocols_valid(self):
        s, k = fixture(True); config.validate_site(s); config.validate_secrets(s, k)

    def test_unknown_fields_rejected(self):
        s, _ = fixture(); s['typo'] = True
        with self.assertRaises(ValueError): config.validate_site(s)

    def test_ports_transport_aware(self):
        s, _ = fixture(True); s['protocols']['anytls']['port'] = s['protocols']['vless']['port']
        with self.assertRaises(ValueError): config.validate_site(s)

    def test_subscription_port_collision(self):
        s, _ = fixture(); s['subscription'].update(enabled=True, port=8443)
        with self.assertRaises(ValueError): config.validate_site(s)

    def test_disabled_protocol_rejected(self):
        s, _ = fixture(); s['devices'][0]['protocols'].append('anytls')
        with self.assertRaises(ValueError): config.validate_site(s)

    def test_enabled_protocol_needs_users(self):
        s, _ = fixture(); s['protocols']['anytls']['enabled'] = True
        with self.assertRaises(ValueError): config.validate_site(s)

    def test_profile_requires_tcpfp(self):
        s, _ = fixture(); s['devices'][0]['tcp_profile'] = 'ios'
        with self.assertRaises(ValueError): config.validate_site(s)

    def test_udp_is_explicit(self):
        s, _ = fixture(); s['devices'][0]['udp_policy'] = 'auto'
        with self.assertRaises(ValueError): config.validate_site(s)

    def test_duplicate_id_rejected(self):
        s, _ = fixture(); s['devices'].append(copy.deepcopy(s['devices'][0]))
        with self.assertRaises(ValueError): config.validate_site(s)

    def test_duplicate_credential_rejected(self):
        s, k = fixture(True); k['devices']['phone']['anytls'] = k['devices']['laptop']['anytls']
        with self.assertRaises(ValueError): config.validate_secrets(s, k)

    def test_unrelated_reality_keys_rejected(self):
        s, k = fixture(); k['reality']['public_key'] = 'B' * 43
        with self.assertRaises(ValueError): config.validate_secrets(s, k)

    def test_private_resolver_rejected(self):
        s, _ = fixture(); s['host']['dns'] = '127.0.0.53'
        with self.assertRaises(ValueError): config.validate_site(s)

    def test_injected_hostname_rejected(self):
        s, _ = fixture(); s['subscription']['hostname'] = 'example.com\nrespond 200'
        with self.assertRaises(ValueError): config.validate_site(s)

    def test_boolean_not_string(self):
        s, _ = fixture(); s['bbr']['host'] = 'false'
        with self.assertRaises(ValueError): config.validate_site(s)


class RenderTests(unittest.TestCase):
    def setUp(self): self.site, self.secret = fixture(True)

    def test_identity_shared_across_protocols(self):
        data = render.frontend(self.site, self.secret)
        self.assertEqual([x['type'] for x in data['listeners']], list(config.PROTOCOLS))
        for listener in data['listeners']:
            users = listener['users']
            self.assertEqual(set(x['username'] for x in users) if isinstance(users, list) else set(users), {'laptop', 'phone'})

    def test_udp_precedes_tcp_identity(self):
        rules = render.frontend(self.site, self.secret)['rules']
        self.assertLess(rules.index('AND,((IN-USER,laptop),(NETWORK,UDP)),REJECT'), rules.index('IN-USER,laptop,egress-windows'))
        self.assertLess(rules.index('AND,((IN-USER,phone),(NETWORK,UDP)),DIRECT'), rules.index('IN-USER,phone,egress-ios'))
        self.assertEqual(rules[-1], 'MATCH,REJECT')

    def test_no_direct_fallback_group(self):
        data = render.frontend(self.site, self.secret)
        self.assertNotIn('proxy-groups', data)
        self.assertTrue(all(not x['udp'] for x in data['proxies']))

    def test_management_exception_device_specific(self):
        laptop = render.client(self.site, self.secret, self.site['devices'][0])
        phone = render.client(self.site, self.secret, self.site['devices'][1])
        self.assertEqual(laptop['rules'][0], 'AND,((IP-CIDR,203.0.113.10/32),(NETWORK,TCP),(DST-PORT,23899)),DIRECT')
        self.assertFalse(any('23899' in x for x in phone['rules']))

    def test_client_never_has_server_private_key(self):
        data = json.dumps(render.client(self.site, self.secret, self.site['devices'][0]))
        self.assertNotIn(self.secret['reality']['private_key'], data)
        self.assertIn(self.secret['reality']['public_key'], data)
        self.assertNotIn(self.secret['devices']['phone']['vless'], data)

    def test_private_and_self_blocked(self):
        data = render.frontend(self.site, self.secret)
        self.assertIn('IP-CIDR,203.0.113.10/32,REJECT', data['rules'])
        self.assertIn('IP-CIDR,100.64.0.0/10,REJECT', data['rules'])
        self.assertIn('IP-CIDR6,::/0,REJECT', data['rules'])

    def test_private_destinations_resolve_before_identity(self):
        rules = render.frontend(self.site, self.secret)['rules']
        first_identity = next(i for i, r in enumerate(rules) if 'IN-USER' in r)
        self.assertTrue(all(not r.endswith('no-resolve') for r in rules[:first_identity]))
        self.assertLess(rules.index('IP-CIDR,10.0.0.0/8,REJECT'), first_identity)

    def test_guard_scoped_to_uid_and_backends(self):
        text = render.guard(self.site, ['windows', 'ios'])
        self.assertIn('meta skuid @MIHOMO_UID@ jump guard', text)
        self.assertIn('oifname "vpn-win0" ip daddr 10.203.1.2 tcp dport 1080 return', text)
        self.assertNotIn('flush ruleset', text)

    def test_units_order_and_least_privilege(self):
        units = render.units(self.site, ['windows', 'ios'])
        self.assertIn('BindsTo=vps-guard.service vps-tcpfp-windows.service vps-tcpfp-ios.service', units['vps-mihomo.service'])
        self.assertIn('DynamicUser=yes', units['vps-tcpfp-windows.service'])
        self.assertIn('LoadCredential=', units['vps-mihomo.service'])


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.site, self.secret = fixture()
    def tearDown(self): self.temp.cleanup()
    def test_private_bundle_permissions_and_hashes(self):
        out = self.root / 'bundle'; build.compile_bundle(self.site, self.secret, out)
        self.assertEqual(out.stat().st_mode & 0o777, 0o700)
        manifest = json.loads((out / 'manifest.json').read_text())
        for entry in manifest['files']:
            path = out / entry['source']
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(build.hashlib.sha256(path.read_bytes()).hexdigest(), entry['sha256'])
        self.assertFalse(json.loads((out / 'plan.json').read_text())['network_changes_executed'])
    def test_refuses_existing_output(self):
        with self.assertRaises(ValueError): build.compile_bundle(self.site, self.secret, self.root)
    def test_refuses_repo_output(self):
        with self.assertRaises(ValueError): build.compile_bundle(self.site, self.secret, SYSTEM / 'output')
    def test_refuses_parent_traversal(self):
        with self.assertRaises(ValueError): build.compile_bundle(self.site, self.secret, self.root / '..' / 'bundle')
        with self.assertRaises(ValueError): build.protected_file(self.root / '..' / 'private.json')
    def test_refuses_symlink_parent(self):
        (self.root / 'link').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): build.compile_bundle(self.site, self.secret, self.root / 'link' / 'bundle')
    def test_refuses_public_secret_permissions(self):
        path = self.root / 'private.json'; path.write_text('{}'); path.chmod(0o644)
        with self.assertRaises(ValueError): build.protected_file(path)
    def test_refuses_secret_symlink(self):
        path = self.root / 'private.json'; path.write_text('{}'); path.chmod(0o600)
        (self.root / 'link').symlink_to(path)
        with self.assertRaises(ValueError): build.protected_file(self.root / 'link')
    def test_tls_material_required(self):
        self.site['subscription']['enabled'] = True
        with self.assertRaises(ValueError): build.compile_bundle(self.site, self.secret, self.root / 'bundle')


@unittest.skipUnless(os.environ.get('MIHOMO_BINARY'), 'Set MIHOMO_BINARY for real parser validation')
class MihomoParserTests(unittest.TestCase):
    def test_all_protocol_server_backends_and_clients(self):
        binary = Path(os.environ['MIHOMO_BINARY']).resolve()
        self.assertEqual(build.hashlib.sha256(binary.read_bytes()).hexdigest(), '817f50b3ac6a8b1c4360c5cf2961906057f3a883d970ebbcb0028a01632b620f')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); cert = root / 'cert.pem'; key = root / 'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key), '-out', str(cert),
                '-days', '30', '-subj', '/CN=sub.example.com', '-addext', 'subjectAltName=DNS:sub.example.com'], check=True, capture_output=True)
            cert.chmod(0o600); key.chmod(0o600)
            site, secret = fixture(True); site['subscription']['enabled'] = True
            # The parser fixture is intentionally self-signed. Production build
            # performs system-trust validation; do not disable it in product code.
            sys.path.insert(0, str(SYSTEM / 'runtime'))
            import certificate
            with self.assertRaises(subprocess.CalledProcessError):
                certificate.check(cert, key, 'sub.example.com')
            with mock.patch.object(certificate, 'check'):
                build.compile_bundle(site, secret, root / 'bundle', cert, key)
            configurations = {'frontend': render.frontend(site, secret)}
            for listener in configurations['frontend']['listeners']:
                if 'certificate' in listener: listener.update({'certificate': str(cert), 'private-key': str(key)})
            for profile in secret['backends']: configurations[profile] = render.backend(site, secret, profile)
            for device in site['devices']: configurations[device['id']] = render.client(site, secret, device)
            for name, data in configurations.items():
                path = root / (name + '.json'); path.write_text(json.dumps(data)); path.chmod(0o600)
                result = subprocess.run([str(binary), '-t', '-d', str(root / (name + '-data')), '-f', str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, name + ': ' + result.stdout + result.stderr)

if __name__ == '__main__': unittest.main()
