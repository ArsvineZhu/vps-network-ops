#!/usr/bin/env python3
"""Read-only certificate/key pairing, hostname and expiry check; no CA requests."""
import argparse
import subprocess
from pathlib import Path

def run(*args):
    return subprocess.check_output(args, stderr=subprocess.DEVNULL)

def check(certificate, key, hostname, days=14):
    run('openssl', 'verify', '-purpose', 'sslserver', '-verify_hostname', hostname,
        '-untrusted', str(certificate), str(certificate))
    run('openssl', 'x509', '-in', str(certificate), '-noout', '-checkend', str(days * 86400))
    public = run('openssl', 'x509', '-in', str(certificate), '-noout', '-pubkey')
    private_public = run('openssl', 'pkey', '-in', str(key), '-pubout')
    if public != private_public:
        raise ValueError('Certificate and key differ')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--certificate', default='/etc/vps-network/tls/fullchain.pem')
    parser.add_argument('--key', default='/etc/vps-network/tls/privkey.pem')
    parser.add_argument('--hostname', required=True)
    parser.add_argument('--days', type=int, default=14)
    args = parser.parse_args()
    try:
        check(Path(args.certificate), Path(args.key), args.hostname, args.days)
    except (ValueError, subprocess.CalledProcessError, OSError):
        raise SystemExit('Certificate check failed: trust, validity, expiry, hostname, file or key mismatch; inspect locally')
    print('Certificate/key and expiry check passed. External served certificate not checked.')

if __name__ == '__main__': main()
