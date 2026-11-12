#!/usr/bin/env python3
"""Recreate dedicated namespaces on boot; never touch unrelated objects."""
from __future__ import annotations
import argparse
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import shutil

STATE = Path('/run/vps-network/objects.json')
CONFIG = Path('/etc/vps-network/network.json')

def run(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, capture_output=True, text=True, **kwargs).stdout

def get(*args):
    return json.loads(run(*args))

def ns_identity(name):
    st = Path('/run/netns', name).stat()
    return [st.st_dev, st.st_ino]

def table_handles():
    return {(x['table']['family'], x['table']['name']): x['table']['handle']
            for x in get('nft', '-j', 'list', 'tables')['nftables'] if 'table' in x}

def preflight(c):
    if STATE.exists():
        raise ValueError('Existing network state: inspect partial or running deployment')
    names = {x['name'] for x in get('ip', '-j', 'netns', 'list')}
    links = {x['ifname'] for x in get('ip', '-j', 'link', 'show')}
    routes = get('ip', '-j', '-4', 'route', 'show', 'table', 'all')
    if c['wan'] not in links:
        raise ValueError('WAN interface not found')
    for r in c['roles'].values():
        if r['namespace'] in names or r['host_if'] in links:
            raise ValueError('A requested namespace or interface already exists')
        network = ipaddress.ip_network(r['network'])
        if any(x.get('dst', 'default') != 'default' and network.overlaps(
            ipaddress.ip_network(x['dst'], strict=False)) for x in routes):
            raise ValueError('Namespace address overlaps an existing route')
    for item in get('nft', '-j', 'list', 'ruleset')['nftables']:
        chain = item.get('chain', {})
        if chain.get('hook') == 'forward':
            raise ValueError('Existing forwarding policy requires review; no automatic UFW/Tailscale edits')
    if shutil.which('iptables'):
        forward = run('iptables', '-S', 'FORWARD').strip().splitlines()
        if forward != ['-P FORWARD ACCEPT']:
            raise ValueError('Existing legacy or compatibility forwarding policy requires review')
    handles = table_handles()
    if ('inet', 'vps_network') in handles or ('ip', 'vps_nat') in handles:
        raise ValueError('Network tables already exist')
    for key in ('net.ipv4.tcp_congestion_control',):
        if c['bbr'] and 'bbr' not in run('sysctl', '-n', 'net.ipv4.tcp_available_congestion_control').split():
            raise ValueError('BBR unavailable; load the official kernel module before deployment')
    run('nft', '-c', '-f', '/etc/vps-network/forward.nft')
    return True

def save(state):
    STATE.write_text(json.dumps(state, indent=2) + '\n'); STATE.chmod(0o600)

def start(c):
    preflight(c)
    state = {'namespaces': {}, 'tables': {}, 'phase': 'starting'}
    save(state)
    # Persist phase after each creation. A failed start is deliberately not
    # retried or automatically rolled back across uncertain resource ownership.
    for profile, r in c['roles'].items():
        ns = r['namespace']
        run('ip', 'netns', 'add', ns)
        state['namespaces'][profile] = {'name': ns, 'identity': ns_identity(ns), 'host_if': r['host_if'], 'ifindex': None}
        save(state)
        run('ip', 'link', 'add', r['host_if'], 'type', 'veth', 'peer', 'name', 'e0', 'netns', ns)
        state['namespaces'][profile]['ifindex'] = get('ip', '-j', 'link', 'show', 'dev', r['host_if'])[0]['ifindex']; save(state)
        run('ip', 'addr', 'add', r['host_ip'] + '/30', 'dev', r['host_if'])
        run('ip', 'link', 'set', r['host_if'], 'mtu', c['mtu'], 'up')
        run('ip', '-n', ns, 'link', 'set', 'lo', 'up')
        run('ip', '-n', ns, 'addr', 'add', r['address'] + '/30', 'dev', 'e0')
        run('ip', '-n', ns, 'link', 'set', 'e0', 'mtu', c['mtu'], 'up')
        run('ip', '-n', ns, 'route', 'add', 'default', 'via', r['host_ip'], 'dev', 'e0')
        settings = {'net.ipv4.ip_default_ttl': 129 if profile == 'windows' else 65,
            'net.ipv4.tcp_timestamps': 0 if profile == 'windows' else 1,
            'net.ipv4.tcp_rmem': '4096 131072 8388608' if profile == 'windows' else '4096 262144 2097152',
            'net.ipv4.tcp_sack': 1, 'net.ipv4.tcp_window_scaling': 1,
            'net.ipv4.tcp_ecn': 0, 'net.ipv4.tcp_fastopen': 0}
        if c['bbr']:
            settings['net.ipv4.tcp_congestion_control'] = 'bbr'
        for key, value in settings.items():
            run('ip', 'netns', 'exec', ns, 'sysctl', '-qw', f'{key}={value}')
        run('ip', 'netns', 'exec', ns, 'nft', '-f', f'/etc/vps-network/namespace-{profile}.nft')
        run('ip', 'netns', 'exec', ns, 'tc', 'qdisc', 'add', 'dev', 'e0', 'clsact')
        run('ip', 'netns', 'exec', ns, 'tc', 'filter', 'add', 'dev', 'e0', 'egress', 'chain', '0',
            'protocol', 'ip', 'pref', '49152', 'handle', '1', 'bpf', 'da', 'obj',
            '/usr/local/lib/vps-network/ebpf/syn_rewrite.o', 'sec', r['section'])
    run('nft', '-f', '/etc/vps-network/forward.nft')
    handles = table_handles()
    state['tables'] = {family + ':' + name: handles[(family, name)] for family, name in [('inet', 'vps_network'), ('ip', 'vps_nat')]}; save(state)
    run('sysctl', '-qw', 'net.ipv4.ip_forward=1')
    state['phase'] = 'ready'; save(state)

def stop():
    state = json.loads(STATE.read_text())
    handles = table_handles()
    # Verify the whole set before deleting anything. Identity uncertainty stops.
    for key, handle in state['tables'].items():
        if handles.get(tuple(key.split(':'))) != handle:
            raise ValueError('Table identity changed; stop and inspect')
    for item in state['namespaces'].values():
        if ns_identity(item['name']) != item['identity']:
            raise ValueError('Namespace identity changed; stop and inspect')
        if item['ifindex'] is not None and get('ip', '-j', 'link', 'show', 'dev', item['host_if'])[0]['ifindex'] != item['ifindex']:
            raise ValueError('Interface identity changed; stop and inspect')
    for key in state['tables']:
        run('nft', 'delete', 'table', *key.split(':'))
    for item in state['namespaces'].values():
        run('ip', 'netns', 'delete', item['name'])
    STATE.unlink()
    # ip_forward is host-wide; do not silently revert it after other services
    # may have started using it. Review the host baseline during uninstall.

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'start', 'stop'])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.action != 'check' and not args.apply:
        print('No changes. Review deployment and authorize --apply.'); return
    c = json.loads(CONFIG.read_text())
    if args.action == 'check': preflight(c)
    elif os.geteuid() != 0: raise SystemExit('Root required')
    elif args.action == 'start': start(c)
    else: stop()

if __name__ == '__main__':
    try: main()
    except (ValueError, subprocess.CalledProcessError):
        raise SystemExit('Network operation stopped. Inspect the private state and owned objects before retrying.')
