#!/usr/bin/env python3
"""Read-only local leaf certificate check. Does not establish trust or inspect keys."""

import datetime
import re
import subprocess
from pathlib import Path


def check(cert, hostname, min_days=7):
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", hostname):
        raise ValueError("Invalid hostname; use a DNS name without a scheme, port or wildcard")
    if min_days < 0 or min_days > 3650:
        raise ValueError("Minimum validity must be between 0 and 3650 days")
    path = Path(cert)
    if not path.is_file():
        raise ValueError("Certificate file does not exist")

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
        raise ValueError("Certificate is not valid yet")
    if parse(dates["notAfter"]) <= now + datetime.timedelta(days=min_days):
        raise ValueError("Certificate has expired or has insufficient remaining validity")
    # Older OpenSSL versions may exit successfully even for a hostname mismatch.
    # Require the explicit positive result instead of trusting the exit code alone.
    result = run("-checkhost", hostname).strip()
    if result != f"Hostname {hostname} does match certificate":
        raise ValueError("Certificate hostname mismatch or unrecognized OpenSSL response")

    return {
        "hostname": hostname,
        "not_before": parse(dates["notBefore"]).isoformat(),
        "not_after": parse(dates["notAfter"]).isoformat(),
    }
