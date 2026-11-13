#!/usr/bin/env python3
"""Manage the SYN queue rule in a dedicated fingerprint namespace."""

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Capture:
    interface: str
    queue: int
    failure_mode: str


def load(path: Path) -> Capture:
    config = json.loads(path.read_text(encoding="utf-8"))
    interface = config["interface"]
    queue = config["syn"]["queue_num"]
    mode = config["syn"]["failure_mode"]
    if not isinstance(interface, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", interface):
        raise ValueError("Invalid network interface")
    if type(queue) is not int or not 0 <= queue <= 65535:
        raise ValueError("Invalid queue number")
    if mode not in ("strict", "open"):
        raise ValueError("Invalid queue failure mode")
    return Capture(interface, queue, mode)


def nft(*args: str, data: str | None = None) -> str:
    return subprocess.run(
        ["nft", *args], input=data, text=True, capture_output=True, check=True
    ).stdout


def table_exists() -> bool:
    tables = json.loads(nft("-j", "list", "tables"))["nftables"]
    return any(
        item.get("table", {}).get("family") == "ip" and item["table"].get("name") == "vps_syn"
        for item in tables
    )


def verify_rule(config: Capture) -> None:
    objects = json.loads(nft("-j", "list", "table", "ip", "vps_syn"))["nftables"]
    if any(
        len(item) != 1 or set(item) - {"metainfo", "table", "chain", "rule"} for item in objects
    ):
        raise ValueError("Capture table contains unexpected objects")
    tables = [item["table"] for item in objects if "table" in item]
    chains = [item["chain"] for item in objects if "chain" in item]
    rules = [item["rule"] for item in objects if "rule" in item]
    if len(tables) != 1 or len(chains) != 1 or len(rules) != 1:
        raise ValueError("Capture table has unexpected contents")
    chain = {
        "family": "ip",
        "table": "vps_syn",
        "name": "output",
        "type": "filter",
        "hook": "postrouting",
        "prio": -150,
        "policy": "accept",
    }
    if any(chains[0].get(key) != value for key, value in chain.items()):
        raise ValueError("Capture chain differs from the configured hook")
    queue: dict[str, object] = {"num": config.queue}
    if config.failure_mode == "open":
        queue["flags"] = ["bypass"]
    interface = {
        "match": {"op": "==", "left": {"meta": {"key": "oifname"}}, "right": config.interface}
    }
    for flags in (["syn", "ack"], {"|": ["syn", "ack"]}):
        match = {
            "match": {
                "op": "==",
                "left": {"&": [{"payload": {"protocol": "tcp", "field": "flags"}}, flags]},
                "right": "syn",
            }
        }
        if rules[0].get("chain") == "output" and rules[0].get("expr") == [
            interface,
            match,
            {"queue": queue},
        ]:
            return
    raise ValueError("Capture rule differs from the configured queue")


def attach(config: Capture) -> None:
    if table_exists():
        verify_rule(config)
        return
    bypass = " bypass" if config.failure_mode == "open" else ""
    rules = (
        "create table ip vps_syn\n"
        "create chain ip vps_syn output { type filter hook postrouting priority -150; policy accept; }\n"
        f'add rule ip vps_syn output oifname "{config.interface}" tcp flags & (syn | ack) == syn queue num {config.queue}{bypass}\n'
    )
    nft("-f", "-", data=rules)


def detach(config: Capture) -> None:
    if table_exists():
        verify_rule(config)
        nft("delete", "table", "ip", "vps_syn")


def check(config: Capture) -> None:
    verify_rule(config)
    queues = Path("/proc/net/netfilter/nfnetlink_queue").read_text(encoding="utf-8")
    if not any(
        line.split() and line.split()[0] == str(config.queue) for line in queues.splitlines()
    ):
        raise ValueError("Queue listener is missing")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("attach", "detach", "check"))
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = load(args.config)
    {"attach": attach, "detach": detach, "check": check}[args.action](config)


if __name__ == "__main__":
    main()
