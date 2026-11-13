#!/usr/bin/env python3
"""Read-only local leaf certificate check. Does not establish trust or inspect keys."""

import argparse
import datetime
import re
import subprocess
from pathlib import Path


def check(cert, hostname, min_days=7):
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", hostname):
        raise ValueError("hostname must be a DNS name, without scheme, port or wildcard")
    if min_days < 0 or min_days > 3650:
        raise ValueError("invalid minimum validity")
    path = Path(cert)
    if not path.is_file():
        raise ValueError("certificate file missing")

    def run(*args):
        return subprocess.run(
            ["openssl", "x509", "-in", str(path), "-noout", *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout

    # x509 reads the first certificate only; never claim fullchain trust from this.
    dates = dict(line.split("=", 1) for line in run("-dates").strip().splitlines())

    def parse(value):
        return datetime.datetime.strptime(value, "%b %d %H:%M:%S %Y GMT").replace(
            tzinfo=datetime.UTC
        )

    now = datetime.datetime.now(datetime.UTC)
    if parse(dates["notBefore"]) > now:
        raise ValueError("certificate is not yet valid")
    if parse(dates["notAfter"]) <= now + datetime.timedelta(days=min_days):
        raise ValueError("certificate expired or below minimum validity")
    # Older OpenSSL versions may exit successfully even for a hostname mismatch.
    # Require the explicit positive result instead of trusting the exit code alone.
    result = run("-checkhost", hostname).strip()
    if result != f"Hostname {hostname} does match certificate":
        raise ValueError("certificate hostname mismatch or unrecognized check result")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--min-days", type=int, default=7)
    args = parser.parse_args()
    try:
        check(args.cert, args.hostname, args.min_days)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError):
        print(
            "FAIL: local certificate checks; no configuration changed. Check file, hostname, dates and OpenSSL availability."
        )
        return 1
    print(
        "PASS: local leaf hostname and validity only. Trust chain, private key match, deployment and network remain unverified."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
