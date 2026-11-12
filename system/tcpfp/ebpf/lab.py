#!/usr/bin/env python3
"""Private, ephemeral two-namespace lab. No host-interface loader exists.

No changes unless --apply is present. Never run this on a production server.
Every destructive command is scoped to resources this process created and
whose identity still matches. Not a security boundary against concurrent root.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import signal
import stat
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent

class SafetyError(RuntimeError):
    pass

class Runner:
    def run(self, args: list[str]) -> str:
        # No shell, no imported script execution, bounded command duration.
        p = subprocess.run(args, text=True, capture_output=True, timeout=30)
        if p.returncode:
            raise SafetyError(f"Command failed ({p.returncode}): {shlex.join(args)}\n{p.stderr}")
        return p.stdout

    def identity(self, name: str) -> tuple[int, int]:
        st = os.stat('/run/netns/' + name, follow_symlinks=False)
        if stat.S_ISLNK(st.st_mode):
            raise SafetyError('Namespace path must not be a symbolic link')
        return st.st_dev, st.st_ino

class Namespace:
    """Created only by Lab.create; successful command AND captured identity."""
    def __init__(self, runner: Runner, name: str, identity: tuple[int, int]):
        self.runner, self.name, self.identity = runner, name, identity
        self.deleted = False

    def check(self):
        if self.deleted or self.runner.identity(self.name) != self.identity:
            raise SafetyError(f'Refusing to act: namespace identity changed: {self.name}')

    def run(self, args):
        self.check()
        return self.runner.run(['ip', 'netns', 'exec', self.name, *args])

    def delete(self):
        self.check()
        self.runner.run(['ip', 'netns', 'delete', self.name])
        self.deleted = True

class Lab:
    def __init__(self, runner=None, token=None):
        self.runner = runner or Runner()
        self.token = token or secrets.token_hex(6)
        if not re.fullmatch(r'[0-9a-f]{12}', self.token):
            raise ValueError('Invalid lab token')
        self.owned: list[Namespace] = []
        self.notes: list[str] = []

    def create(self, role):
        if role not in ('client', 'server'):
            raise ValueError('Invalid namespace role')
        name = f'tcpfp-{self.token}-{role}'
        existing = json.loads(self.runner.run(['ip', '-j', 'netns', 'list']))
        if any(entry.get('name') == name for entry in existing):
            raise SafetyError(f'Name already exists; never deleting it: {name}')
        try:
            self.runner.run(['ip', 'netns', 'add', name])
        except Exception:
            # A timeout/command error is not proof of ownership. No speculative
            # cleanup or automatic retry; report a possibly-created object.
            self.notes.append(f'Creation not confirmed; inspect manually: {name}')
            raise
        try:
            ident = self.runner.identity(name)
        except Exception:
            self.notes.append(f'Created but identity unavailable; inspect manually: {name}')
            raise
        ns = Namespace(self.runner, name, ident)
        self.owned.append(ns)
        return ns

    def setup(self):
        client, server = self.create('client'), self.create('server')
        # Both endpoints are born inside owned namespaces, never in the host.
        server.check()
        client.run(['ip', 'link', 'add', 'c0', 'type', 'veth', 'peer', 'name', 's0', 'netns', server.name])
        for ns, iface, ipaddr in ((client, 'c0', '10.203.0.2/30'), (server, 's0', '10.203.0.1/30')):
            ns.run(['ip', 'link', 'set', 'lo', 'up'])
            ns.run(['ip', 'addr', 'add', ipaddr, 'dev', iface])
            ns.run(['ip', 'link', 'set', iface, 'up'])
        return client, server

    def cleanup(self):
        errors = []
        for ns in reversed(self.owned):
            if ns.deleted:
                continue
            try:
                ns.delete()
            except Exception as error:
                errors.append(str(error))
        if errors:
            raise SafetyError('Cleanup incomplete: ' + '; '.join(errors))

def _handle(value):
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None

class Filter:
    def __init__(self, ns: Namespace, iface: str, pref: int):
        if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', iface) or not (1 <= pref <= 65535):
            raise ValueError('Invalid interface/preference')
        self.ns, self.iface, self.pref = ns, iface, pref
        self.identity = None

    def entries(self):
        return json.loads(self.ns.run(['tc', '-j', 'filter', 'show', 'dev', self.iface, 'egress', 'chain', '0']))

    def matching(self):
        return [e for e in self.entries() if e.get('pref') == self.pref]

    def fingerprint(self, entry):
        opts = entry.get('options', {})
        # iproute2 bpf_dump_prog_info nests id/tag in options.prog.
        # Fail closed on unknown schemas; summary-only records lack options.
        prog = opts.get('prog', {})
        required = (entry.get('kind') == 'bpf' and entry.get('protocol') == 'ip'
                    and entry.get('chain', 0) == 0 and _handle(opts.get('handle')) == 1
                    and isinstance(prog.get('id'), int) and prog['id'] > 0
                    and isinstance(prog.get('tag'), str) and len(prog['tag']) == 16)
        if not required:
            raise SafetyError('Unrecognized filter identity; refusing deletion')
        return (entry['pref'], opts['handle'], prog['id'], prog['tag'])

    def attach(self, obj: Path, section: str):
        if section not in ('tc_win', 'tc_ios', 'tc_mark'):
            raise ValueError('Invalid section')
        if self.identity is not None:
            raise SafetyError('Filter object is already attached')
        qdiscs = json.loads(self.ns.run(['tc', '-j', 'qdisc', 'show', 'dev', self.iface]))
        if not any(q.get('kind') == 'clsact' for q in qdiscs):
            self.ns.run(['tc', 'qdisc', 'add', 'dev', self.iface, 'clsact'])
        if self.matching():
            raise SafetyError('Preference already in use; no replacement or deletion')
        self.ns.run(['tc', 'filter', 'add', 'dev', self.iface, 'egress', 'chain', '0',
                     'protocol', 'ip', 'pref', str(self.pref), 'handle', '1',
                     'bpf', 'da', 'obj', str(obj.resolve()), 'sec', section])
        # Query after successful add. Unknown output => stop, no blind delete.
        entries = [e for e in self.matching() if 'options' in e]
        if len(entries) != 1:
            raise SafetyError('Cannot confirm attached filter; no speculative deletion')
        self.identity = self.fingerprint(entries[0])

    def detach(self):
        if self.identity is None:
            raise SafetyError('No confirmed owned filter')
        entries = [e for e in self.matching() if 'options' in e]
        if len(entries) != 1 or self.fingerprint(entries[0]) != self.identity:
            raise SafetyError('Filter changed; refusing deletion')
        self.ns.run(['tc', 'filter', 'del', 'dev', self.iface, 'egress', 'chain', '0',
                     'protocol', 'ip', 'pref', str(self.pref), 'handle', '1', 'bpf'])
        self.identity = None
        # Intentionally NEVER delete clsact: it may carry other filters.


    def read_stats(self):
        """Snapshot the owned program's stats map before detach destroys it."""
        if self.identity is None:
            raise SafetyError('No confirmed owned program')
        try:
            prog = json.loads(self.ns.run(['bpftool', '-j', 'prog', 'show', 'id', str(self.identity[2])]))
            if isinstance(prog, list):
                if len(prog) != 1:
                    raise SafetyError('Unexpected program-info list')
                prog = prog[0]
            maps = []
            for ident in prog.get('map_ids', []):
                info = json.loads(self.ns.run(['bpftool', '-j', 'map', 'show', 'id', str(ident)]))
                if isinstance(info, list):
                    info = info[0] if len(info) == 1 else {}
                if info.get('name') == 'stats':
                    values = json.loads(self.ns.run(['bpftool', '-j', 'map', 'dump', 'id', str(ident)]))
                    maps.append({'info': info, 'values': values})
            if not maps:
                raise SafetyError('Owned program stats map not found')
            return {'available': True, 'maps': maps}
        except Exception as error:
            # Preserve useful traffic evidence but never call this a full pass.
            return {'available': False, 'reason': str(error)}


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def cleanup_resources(lab, processes, report):
    """Always try both process and namespace cleanup; fail if either fails."""
    process_errors = []
    for process in reversed(processes):
        try:
            stop_process(process)
        except Exception as error:
            process_errors.append(str(error))
    report['process_cleanup_errors'] = process_errors
    cleanup_error = None
    try:
        lab.cleanup()
    except Exception as error:
        cleanup_error = error
        report['namespace_cleanup_error'] = str(error)
    report['cleanup_complete'] = not process_errors and cleanup_error is None and not lab.notes
    report['ownership_notes'] = lab.notes
    if cleanup_error is not None or process_errors:
        raise SafetyError('Cleanup incomplete; see result.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Create and later delete a private lab (requires root)')
    parser.add_argument('--mode', choices=['win', 'ios'], default='ios')
    parser.add_argument('--output', type=Path, default=Path('lab-results'))
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({'dry_run': True, 'plan': ['clean BPF build', 'create two random-name private netns',
              'create veth directly inside them', 'start packet capture', 'attach exact owned filter',
              'download and upload 4 MiB with hash checks', 'stop own processes', 'delete only owned namespaces'],
              'warning': 'Run --apply only in an approved disposable VM. Same-host veth is not NIC offload acceptance.'}, indent=2))
        return 0
    if os.geteuid() != 0:
        raise SafetyError('--apply requires root in an approved disposable VM')
    # Build before creating namespaces. Never load a supplied/stale .o.
    subprocess.run(['make', '-B', 'syn_rewrite.o'], cwd=HERE, check=True, timeout=120)
    if args.output.exists():
        raise SafetyError('Output directory already exists; choose a fresh directory')
    args.output.mkdir(parents=True, mode=0o700)
    out = args.output.resolve()
    lab, processes, report = Lab(), [], {'mode': args.mode, 'kernel_acceptance': False}
    old_handlers = {}
    def interrupted(signum, _frame):
        raise InterruptedError(f'Interrupted by signal {signum}')
    for signum in (signal.SIGINT, signal.SIGTERM):
        old_handlers[signum] = signal.signal(signum, interrupted)
    try:
        client, server = lab.setup()
        client.run(['sysctl', '-qw', f'net.ipv4.tcp_timestamps={0 if args.mode == "win" else 1}'])
        client.run(['sysctl', '-qw', f'net.ipv4.ip_default_ttl={128 if args.mode == "win" else 64}'])
        # Original numeric profiles, configured only inside the owned client.
        # Kernel version/memory policy can still change window/WS: inspect PCAP.
        profile = '4096 131072 8388608' if args.mode == 'win' else '4096 262144 2097152'
        for key, value in {'tcp_rmem': profile, 'tcp_fastopen': '0', 'tcp_sack': '1',
                           'tcp_window_scaling': '1', 'tcp_syn_retries': '3'}.items():
            client.run(['sysctl', '-qw', f'net.ipv4.{key}={value}'])
        server.run(['sysctl', '-qw', 'net.ipv4.tcp_timestamps=1', 'net.ipv4.tcp_fastopen=0'])
        report['client_profile'] = client.run(['sysctl', 'net.ipv4.tcp_rmem',
            'net.ipv4.tcp_timestamps', 'net.ipv4.ip_default_ttl'])
        report['kernel'] = os.uname().release
        report['source_sha256'] = hashlib.sha256((HERE/'syn_rewrite.c').read_bytes()).hexdigest()
        report['object_sha256'] = hashlib.sha256((HERE/'syn_rewrite.o').read_bytes()).hexdigest()
        report['tc_version'] = lab.runner.run(['tc', '-V']).strip()
        server.check()
        capture_log = (out / 'tcpdump.log').open('wb')
        capture_file = (out / 'traffic.pcap').open('wb')
        try:
            capture = subprocess.Popen(['ip', 'netns', 'exec', server.name, 'tcpdump', '-U', '-s', '0',
                    '-i', 's0', '-w', '-', 'tcp', 'port', '8080'],
                    stdout=capture_file, stderr=capture_log, env={**os.environ, 'LC_ALL': 'C'})
            processes.append(capture)
            # Wait for tcpdump readiness; sleeping blindly can miss the SYN.
            for _ in range(100):
                if capture.poll() is not None:
                    raise SafetyError('tcpdump exited before readiness')
                if 'listening on' in (out/'tcpdump.log').read_text(errors='replace'):
                    break
                time.sleep(0.05)
            else:
                raise SafetyError('tcpdump readiness timed out')
            server.check()
            service = subprocess.Popen(['ip', 'netns', 'exec', server.name, sys.executable,
                    str(HERE/'traffic.py'), 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            processes.append(service)
            filt = Filter(client, 'c0', 49152)
            filt.attach(HERE/'syn_rewrite.o', 'tc_'+args.mode)
            report['traffic'] = json.loads(client.run([sys.executable, str(HERE/'traffic.py'), 'client']))
            report['filter_before_detach'] = filt.entries()
            report['stats_before_detach'] = filt.read_stats()
            filt.detach()
            # Give FIN/ACK capture a bounded drain interval, then SIGINT to
            # flush pcap and print packet/drop counters.
            time.sleep(0.2)
            capture.send_signal(signal.SIGINT)
            capture.wait(timeout=10)
            if capture.returncode != 0:
                raise SafetyError('tcpdump did not exit successfully')
        finally:
            capture_file.close()
            capture_log.close()
        report['application_hashes_pass'] = True
        report['pcap_sha256'] = hashlib.sha256((out/'traffic.pcap').read_bytes()).hexdigest()
        report['capture_log'] = (out/'tcpdump.log').read_text()
        # veth and app hashes alone are not complete fingerprint/checksum proof.
        report['remaining_gates'] = ['inspect full pcap/handshakes and drop counters',
            'verify original/rewritten option semantics and JA4T', 'independent receive-side offload on/off',
            'concurrency, sustained traffic, loss/retransmission, MTU/route/NAT matrix']
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        # Preserve cleanup against a second interrupt; restore handlers below.
        for signum in old_handlers:
            signal.signal(signum, signal.SIG_IGN)
        try:
            cleanup_resources(lab, processes, report)
        finally:
            try:
                (out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
            finally:
                for signum, handler in old_handlers.items():
                    signal.signal(signum, handler)
    print(json.dumps(report, indent=2))
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
