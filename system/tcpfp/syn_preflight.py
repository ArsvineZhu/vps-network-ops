#!/usr/bin/env python3
"""Check the fingerprint exit before installing its queue capture rule."""

import argparse
import json
import os
import subprocess
from pathlib import Path

from engines import load


def check(role):
    namespace = Path("/run/netns/tcpfp-" + role + "-test").stat()
    current = os.stat("/proc/self/ns/net")
    if (namespace.st_dev, namespace.st_ino) != (current.st_dev, current.st_ino):
        raise ValueError("Unexpected network namespace")
    selected = load()[role]
    if selected != "nfqueue":
        raise ValueError("NFQUEUE is not selected for this exit")
    config = json.loads(Path("/etc/tcpfp/syn-" + role + ".json").read_text())
    syn = config["syn"]
    if config["interface"] != "e0" or syn["profile"] != role or not syn["enabled"]:
        raise ValueError("Queue configuration does not match the selected exit")
    data = subprocess.check_output(["tc", "-j", "filter", "show", "dev", "e0", "egress"], text=True)
    if any(item.get("kind") == "bpf" for item in json.loads(data)):
        raise ValueError("A BPF filter is still attached to this exit")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("windows", "ios"))
    check(parser.parse_args().role)
