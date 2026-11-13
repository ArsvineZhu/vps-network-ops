#!/usr/bin/env python3
"""Start the fingerprint network or verify an already running instance."""

import json
import subprocess

from engines import load as load_engines
from engines import verify_runtime
from resolver import repair


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def fail(message):
    raise SystemExit(message)


try:
    repair()
    engines = load_engines()
    namespaces = {x["name"] for x in json.loads(run("ip", "-j", "netns", "list") or "[]")}
    links = {x["ifname"] for x in json.loads(run("ip", "-j", "link", "show"))}
    tables = {
        (x["table"]["family"], x["table"]["name"])
        for x in json.loads(run("nft", "-j", "list", "tables"))["nftables"]
        if "table" in x
    }
    expected_ns = {"tcpfp-windows-test", "tcpfp-ios-test"}
    expected_links = {"tfp-win0", "tfp-ios0"}
    expected_tables = {("inet", "tcpfp_test"), ("ip", "tcpfp_test_nat")}
    ufw = run("iptables", "-S", "ufw-user-forward")
    markers = [
        "tcpfp-test:windows:tcp",
        "tcpfp-test:windows:dns",
        "tcpfp-test:ios:tcp",
        "tcpfp-test:ios:dns",
    ]
    present = bool(namespaces & expected_ns or links & expected_links or tables & expected_tables)
    if not present:
        if any(x in ufw for x in markers):
            fail("Fingerprint forwarding rules exist without their network")
        subprocess.run(["/bin/bash", "/etc/tcpfp/network.sh"], check=True)
        print("Recreated fingerprint network")
    else:
        if not (
            expected_ns <= namespaces and expected_links <= links and expected_tables <= tables
        ):
            fail("Partial fingerprint network exists; inspect before starting")
        if any(ufw.count(x) != 1 for x in markers):
            fail("Fingerprint forwarding rules do not match the network")
        guard = run("nft", "list", "chain", "inet", "mihomo_guard", "guard")
        if not all(x in guard for x in ("tcpfp-test:windows", "tcpfp-test:ios")):
            fail("Frontend guard lacks fingerprint backend exceptions")
        for role, section in [("windows", "tc_win"), ("ios", "tc_ios")]:
            ns = "tcpfp-" + role + "-test"
            filters = json.loads(
                run("ip", "netns", "exec", ns, "tc", "-j", "filter", "show", "dev", "e0", "egress")
            )
            tables = []
            if engines[role] == "tc":
                tables = json.loads(run("ip", "netns", "exec", ns, "nft", "-j", "list", "tables"))[
                    "nftables"
                ]
            verify_runtime(engines[role], section, filters, tables)
            if (
                run(
                    "ip", "netns", "exec", ns, "sysctl", "-n", "net.ipv4.tcp_congestion_control"
                ).strip()
                != "bbr"
            ):
                fail("Fingerprint namespace congestion control changed")
        print("Fingerprint network is running")
except (subprocess.CalledProcessError, OSError, ValueError, KeyError) as e:
    raise SystemExit(f"Fingerprint network failed: {e}") from e
