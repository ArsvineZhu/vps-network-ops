#!/usr/bin/env python3
"""Render nftables and preflight inputs for the fingerprint network."""

import argparse
import ipaddress
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]


def render(public_ipv4, wan, output):
    address = ipaddress.IPv4Address(public_ipv4)
    if address.is_loopback or address.is_multicast or address.is_unspecified:
        raise ValueError("Expected the server IPv4 address")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", wan):
        raise ValueError("Invalid WAN interface")
    if ".." in Path(output).parts:
        raise ValueError("Parent traversal is not allowed")
    output = Path(output).absolute()
    if output.is_relative_to(REPO) or any(p.is_symlink() for p in output.parents):
        raise ValueError("Output must be outside the repository and symlink-free")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name in ("host", "windows", "ios"):
        text = (HERE / (name + ".nft.in")).read_text(encoding="utf8")
        if "@PUBLIC_IPV4@" not in text:
            raise ValueError("Network template is missing the server address")
        text = text.replace("@PUBLIC_IPV4@", str(address)).replace("@WAN@", wan)
        (output / (name + ".nft")).write_text(text, encoding="utf8")
    plan = {
        "wan": wan,
        "roles": {
            "windows": {
                "ns": "tcpfp-windows-test",
                "host_if": "tfp-win0",
                "network": "10.203.1.0/30",
            },
            "ios": {"ns": "tcpfp-ios-test", "host_if": "tfp-ios0", "network": "10.203.2.0/30"},
        },
    }
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-ipv4", required=True)
    parser.add_argument("--wan", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(args.public_ipv4, args.wan, args.output)


if __name__ == "__main__":
    main()
