#!/usr/bin/env python3
"""Check that the fingerprint network can be created on this host."""

import ipaddress
import json
import subprocess
from pathlib import Path


def get(*args):
    return json.loads(subprocess.check_output(args, text=True) or "[]")


def check():
    plan = json.loads((Path(__file__).parent / "plan.json").read_text(encoding="utf-8"))
    names = {item["name"] for item in get("ip", "-j", "netns", "list")}
    links = {item["ifname"] for item in get("ip", "-j", "link", "show")}
    routes = get("ip", "-j", "-4", "route", "show", "table", "all")
    for role in plan["roles"].values():
        if role["ns"] in names or role["host_if"] in links:
            raise ValueError("Fingerprint network object already exists")
        network = ipaddress.ip_network(role["network"])
        for route in routes:
            destination = route.get("dst", "default")
            if destination != "default" and network.overlaps(
                ipaddress.ip_network(destination, strict=False)
            ):
                raise ValueError(f"Fingerprint network overlaps route {destination}")
    if plan["wan"] not in links:
        raise ValueError("WAN interface does not exist")


if __name__ == "__main__":
    check()
