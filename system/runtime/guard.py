#!/usr/bin/env python3
"""Manage only our guard table; explicit --apply is required."""
import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess

STATE = Path('/run/vps-guard/identity.json')

def run(*args, **kw):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kw).stdout

def table_identity():
    data = json.loads(run('nft', '-j', 'list', 'tables'))
    tables = [x['table'] for x in data['nftables'] if 'table' in x
              and x['table']['family'] == 'inet' and x['table']['name'] == 'vps_guard']
    return tables[0]['handle'] if tables else None

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'check'])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.action == 'check':
        rendered = Path('/etc/vps-network/guard.nft').read_text().replace('@MIHOMO_UID@', str(pwd.getpwnam('vps-mihomo').pw_uid))
        run('nft', '-c', '-f', '-', input=rendered)
        return
    if not args.apply:
        print('No changes. Explicit --apply and deployment authorization required.'); return
    if os.geteuid() != 0:
        raise SystemExit('Root required')
    current = table_identity()
    if args.action == 'start':
        if current is not None or STATE.exists():
            raise SystemExit('Existing guard or state: inspect, do not overwrite')
        rendered = Path('/etc/vps-network/guard.nft').read_text().replace('@MIHOMO_UID@', str(pwd.getpwnam('vps-mihomo').pw_uid))
        run('nft', '-c', '-f', '-', input=rendered)
        run('nft', '-f', '-', input=rendered)
        STATE.write_text(json.dumps({'handle': table_identity()})); STATE.chmod(0o600)
    else:
        saved = json.loads(STATE.read_text())
        if current != saved['handle'] or current is None:
            raise SystemExit('Guard identity changed; manual review required')
        run('nft', 'delete', 'table', 'inet', 'vps_guard')
        STATE.unlink()

if __name__ == '__main__':
    main()
