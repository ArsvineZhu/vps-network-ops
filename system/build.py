#!/usr/bin/env python3
"""Offline bundle compiler. No server, DNS, service, firewall or Git mutation."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
from config import ROLES, validate_site, validate_secrets
import render

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

def protected_file(path):
    if '..' in Path(path).parts: raise ValueError('Parent traversal in private input path rejected')
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink(): raise ValueError('Symlink input rejected')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError('Private input must be a regular file with mode 0600 or stricter')
    if info.st_uid != os.getuid(): raise ValueError('Private input must belong to the caller')
    if path.is_relative_to(REPO): raise ValueError('Private inputs must be outside the repository')
    return path.read_bytes()

def compile_bundle(site, secret, output, certificate=None, key=None):
    validate_site(site); validate_secrets(site, secret)
    if '..' in Path(output).parts: raise ValueError('Parent traversal in output path rejected')
    output = Path(output).absolute()
    if output.is_relative_to(REPO) or output.exists() or output.is_symlink():
        raise ValueError('Use a new output directory outside the repository')
    for parent in output.parents:
        if parent.is_symlink(): raise ValueError('Symlink output parent rejected')
    if not output.parent.is_dir(): raise ValueError('Create a private output parent first')
    if output.parent.stat().st_mode & 0o022: raise ValueError('Output parent is writable by another user')
    tls = site['subscription']['enabled'] or any(site['protocols'][p]['enabled'] for p in ('hysteria2', 'anytls'))
    if tls and (certificate is None or key is None): raise ValueError('TLS requires certificate and private-key files')
    cert_data = protected_file(certificate) if tls else None
    key_data = protected_file(key) if tls else None
    if tls:
        sys.path.insert(0, str(HERE / 'runtime'))
        from certificate import check
        check(Path(certificate), Path(key), site['subscription']['hostname'])
    output.mkdir(mode=0o700)
    entries = []
    def add(target, content, owner='root', group='root', mode='0600'):
        source = 'artifacts/' + target.lstrip('/')
        path = output / source
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Every ancestor in the bundle is private, not only its top directory.
        for parent in path.parents:
            if parent == output: break
            parent.chmod(0o700)
        data = content if isinstance(content, bytes) else content.encode()
        with path.open('xb') as stream: stream.write(data)
        path.chmod(0o600)
        entries.append({'source': source, 'target': target, 'owner': owner, 'group': group,
                        'mode': mode, 'sha256': hashlib.sha256(data).hexdigest()})
    def add_json(target, obj, **kwargs): add(target, render.text_json(obj), **kwargs)
    profiles = sorted(secret['backends'])
    add_json('/etc/vps-network/mihomo.json', render.frontend(site, secret))
    add('/etc/vps-network/guard.nft', render.guard(site, profiles))
    units = render.units(site, profiles)
    for profile in profiles:
        add_json(f'/etc/vps-network/{profile}.json', render.backend(site, secret, profile))
        add(f'/etc/vps-network/namespace-{profile}.nft', render.namespace_guard(site, profile))
    if profiles:
        add_json('/etc/vps-network/network.json', {'wan': site['host']['wan'], 'mtu': site['tcpfp']['mtu'],
            'bbr': site['bbr']['namespaces'], 'roles': {p: ROLES[p] for p in profiles}})
        add('/etc/vps-network/forward.nft', render.forward_rules(site, profiles))
        for name in ('Makefile', 'syn_rewrite.c'):
            add('/usr/local/lib/vps-network/ebpf/' + name, (HERE / 'tcpfp/ebpf' / name).read_bytes(), mode='0644')
    for name in ('network.py', 'guard.py', 'certificate.py', 'usage.py'):
        add('/usr/local/lib/vps-network/' + name, (HERE / 'runtime' / name).read_bytes(), mode='0755')
    services = (['vps-network.service'] if profiles else []) + ['vps-tcpfp-' + p + '.service' for p in profiles] + ['vps-guard.service', 'vps-mihomo.service']
    if tls:
        add('/etc/vps-network/tls/fullchain.pem', cert_data, group='vps-tls', mode='0640')
        add('/etc/vps-network/tls/privkey.pem', key_data, group='vps-tls', mode='0640')
        units['vps-cert-check.service'] = f'''[Unit]
Description=Local certificate expiry and key check
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/local/lib/vps-network/certificate.py --hostname {site['subscription']['hostname']}
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateNetwork=yes
'''
        units['vps-cert-check.timer'] = '''[Unit]
Description=Daily local certificate check
[Timer]
OnCalendar=*-*-* 03:23:00
RandomizedDelaySec=1800
Persistent=true
[Install]
WantedBy=timers.target
'''
        services.append('vps-cert-check.timer')
    if site['subscription']['enabled']:
        add('/etc/vps-network/Caddyfile', render.caddy(site, secret), group='caddy', mode='0640')
        add('/etc/systemd/system/caddy.service.d/vps-network.conf', '''[Service]
ExecStart=
ExecStart=/usr/bin/caddy run --environ --config /etc/vps-network/Caddyfile --adapter caddyfile
ExecReload=
ExecReload=/usr/bin/caddy reload --config /etc/vps-network/Caddyfile --adapter caddyfile --force
SupplementaryGroups=vps-tls
''', mode='0644')
        for device in site['devices']:
            add_json('/srv/vps-network/subscriptions/' + device['id'] + '.json', render.client(site, secret, device), owner='root', group='caddy', mode='0640')
        services.append('caddy.service')
    if site['usage']['enabled']:
        scripts = REPO / 'skills/operate-vps-network/scripts'
        for name in ('usage_daemon.py', 'observed_usage.py'):
            add('/usr/local/lib/vps-network/' + name, (scripts / name).read_bytes(), mode='0755')
        collectors = [{'socket': '/run/vps-mihomo/control.sock', 'db': '/var/lib/vps-usage/' + p + '.sqlite',
            'inbound': p + '-in', 'instance': 'private-vps', 'users': [d['id'] for d in site['devices'] if p in d['protocols']],
            'interval': site['usage']['interval_seconds']} for p, value in site['protocols'].items() if value['enabled']]
        add_json('/etc/vps-network/collector.json', {'collectors': collectors})
        units['vps-usage.service'] = '''[Unit]
Description=Approximate private connection sampling
After=vps-mihomo.service
[Service]
User=vps-usage
Group=vps-usage
SupplementaryGroups=vps-controller
LoadCredential=collector.json:/etc/vps-network/collector.json
ExecStart=/usr/bin/python3 /usr/local/lib/vps-network/usage.py --config %d/collector.json
WorkingDirectory=/var/lib/vps-usage
UMask=0077
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateNetwork=yes
RestrictAddressFamilies=AF_UNIX
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=/var/lib/vps-usage
CapabilityBoundingSet=
MemoryMax=192M
CPUQuota=10%
[Install]
WantedBy=multi-user.target
'''
        services.append('vps-usage.service')
    if site['bbr']['host']:
        add('/etc/sysctl.d/80-vps-network-bbr.conf', 'net.ipv4.tcp_congestion_control=bbr\n', mode='0644')
    for name, content in units.items(): add('/etc/systemd/system/' + name, content, mode='0644')
    manifest = {'schema': 1, 'files': entries, 'services': services,
                'prerequisites': ['Ubuntu 24.04 x86_64', 'verified Mihomo v1.19.33', 'approved fresh host'],
                'enabled_protocols': [p for p, item in site['protocols'].items() if item['enabled']],
                'tcpfp_enabled': bool(profiles), 'bbr_host': site['bbr']['host']}
    plan = {'schema': 1, 'kind': 'private-offline-bundle', 'services': services,
            'protocols': manifest['enabled_protocols'], 'tcp_profiles': profiles,
            'udp_policy': {d['id']: d['udp_policy'] for d in site['devices']},
            'network_changes_executed': False, 'production_verified': False,
            'certificate_renewal': 'external DNS-01 issuance/import; timer checks only',
            'source_revision': 'uncommitted worktree; review and commit before deployment',
            'requires_fresh_host_acceptance': True}
    for filename, data in [('manifest.json', manifest), ('plan.json', plan)]:
        (output / filename).write_text(render.text_json(data)); (output / filename).chmod(0o600)
    return plan

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True, type=Path)
    parser.add_argument('--secrets', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--certificate', type=Path)
    parser.add_argument('--certificate-key', type=Path)
    args = parser.parse_args()
    try:
        site = json.loads(args.site.read_text())
        secrets = json.loads(protected_file(args.secrets))
        plan = compile_bundle(site, secrets, args.output, args.certificate, args.certificate_key)
    except Exception:
        print('Build stopped: invalid input, permissions, certificate or output. No live system changed; inspect private inputs.', file=sys.stderr)
        return 2
    print(json.dumps({'bundle_created': True, 'live_changes': False, 'protocols': plan['protocols']}))
    return 0

if __name__ == '__main__': raise SystemExit(main())
