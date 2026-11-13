#!/usr/bin/env python3
"""Read the per-exit fingerprint engine selection."""

import json
import sys
from pathlib import Path

PATH = Path("/etc/tcpfp/fingerprint-engines.json")
ROLES = ("windows", "ios")


def load(path=PATH):
    return parse(path.read_bytes())


def parse(raw):
    config = json.loads(raw)
    if not isinstance(config, dict) or set(config) != set(ROLES):
        raise ValueError("Expected one engine entry per exit")
    for role in ROLES:
        if config[role] not in ("tc", "nfqueue"):
            raise ValueError("Invalid fingerprint engine")
    return config


def verify_runtime(engine, section, filters, tables):
    bpf = [item for item in filters if item.get("kind") == "bpf"]
    if engine == "tc":
        if any(
            item.get("table", {}).get("family") == "ip" and item["table"].get("name") == "vps_syn"
            for item in tables
        ):
            raise ValueError("Queue capture table remains on the tc exit")
        if not any(section in str(item.get("options", {}).get("bpf_name", "")) for item in bpf):
            raise ValueError("Expected fingerprint filter missing")
    elif engine == "nfqueue":
        if bpf:
            raise ValueError("BPF filter present on the NFQUEUE exit")
    else:
        raise ValueError("Invalid fingerprint engine")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ROLES:
        raise SystemExit("Expected windows or ios")
    print(load()[sys.argv[1]])
