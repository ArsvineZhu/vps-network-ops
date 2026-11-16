"""Owned forwarding firewall, SYN capture and privileged tunnel counters."""

import argparse
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

import yaml

from .capabilities import Capabilities
from .exit_profiles import FINGERPRINTS
from .files import save
from .wireguard import INTERFACE, NETWORK, PROFILE_NETWORKS, peers

PRIVATE_V4 = "{ 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.0.0.0/24, 192.0.2.0/24, 192.168.0.0/16, 198.18.0.0/15, 198.51.100.0/24, 203.0.113.0/24, 224.0.0.0/4, 240.0.0.0/4 }"


def command(*args, data=None):
    return subprocess.run(list(args), input=data, text=True, capture_output=True, check=True).stdout


def wan(config):
    name = config["wan"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", name):
        raise ValueError("Invalid WAN interface")
    return name


def table_exists(family, name):
    return any(
        item.get("table", {}).get("family") == family and item["table"].get("name") == name
        for item in json.loads(command("nft", "-j", "list", "tables"))["nftables"]
    )


def replace_table(family, name, rules):
    prefix = f"delete table {family} {name}\n" if table_exists(family, name) else ""
    command("nft", "-f", "-", data=prefix + rules)


def remove_table(family, name):
    if table_exists(family, name):
        command("nft", "delete", "table", family, name)


def wireguard_rules(config, active_peers):
    interface = wan(config)
    addresses = ", ".join(peer["address"] for peer in active_peers)
    elements = " elements = { " + addresses + " };" if addresses else ""
    guard = f'''table inet vps_wireguard_guard {{
 set peers {{ type ipv4_addr;{elements} }}
 chain input {{ type filter hook input priority -10; policy accept;
  iifname "{INTERFACE}" meta nfproto ipv6 drop
  iifname "{INTERFACE}" ip saddr != @peers drop
  iifname "{INTERFACE}" tcp dport 9443 accept
  iifname "{INTERFACE}" drop
 }}
 chain forward {{ type filter hook forward priority -10; policy accept;
  iifname "{INTERFACE}" meta nfproto ipv6 drop
  iifname "{INTERFACE}" ip saddr != @peers drop
  iifname "{INTERFACE}" ip daddr {PRIVATE_V4} drop
  iifname "{INTERFACE}" oifname != "{interface}" drop
  oifname "{INTERFACE}" ct state established,related accept
  oifname "{INTERFACE}" drop
 }}
}}
'''
    nat = f'''table ip vps_wireguard_nat {{
 chain postrouting {{ type nat hook postrouting priority srcnat; policy accept;
  iifname "{INTERFACE}" oifname "{interface}" ip saddr {NETWORK} masquerade
 }}
}}
'''
    return guard, nat


def refresh_peers(config, state):
    guard, nat = wireguard_rules(config, peers(state))
    replace_table("inet", "vps_wireguard_guard", guard)
    replace_table("ip", "vps_wireguard_nat", nat)
    command(
        "ufw",
        "route",
        "allow",
        "in",
        "on",
        INTERFACE,
        "out",
        "on",
        wan(config),
        "from",
        NETWORK,
        "comment",
        "vps-ops-wireguard",
    )


def wireguard_start(config):
    if not Capabilities.from_config(config).wireguard:
        raise ValueError("WireGuard is disabled")
    state = json.loads(Path("/etc/vps-ops/identity.json").read_text())
    refresh_peers(config, state)


def wireguard_stop(config):
    command(
        "ufw",
        "--force",
        "route",
        "delete",
        "allow",
        "in",
        "on",
        INTERFACE,
        "out",
        "on",
        wan(config),
        "from",
        NETWORK,
        "comment",
        "vps-ops-wireguard",
    )
    remove_table("inet", "vps_wireguard_guard")
    remove_table("ip", "vps_wireguard_nat")
    Path("/run/vps-ops/wireguard-usage.json").unlink(missing_ok=True)


def fingerprint_rules(config):
    plan = Capabilities.from_config(config)
    interface = wan(config)
    lines = [
        "table ip vps_fingerprint_forward {",
        " chain forward { type filter hook forward priority -150; policy accept;",
    ]
    if plan.wireguard:
        for profile, queue in zip(FINGERPRINTS, (4947, 4948), strict=True):
            match = f'iifname "{INTERFACE}" oifname "{interface}" ip saddr {PROFILE_NETWORKS[profile.key]}'
            lines.append(f"  {match} ip ttl set {profile.ttl}")
            lines.append(f"  {match} tcp flags & (syn | ack) == syn queue num {queue}")
    if plan.tailscale:
        match = f'iifname "tailscale0" oifname "{interface}"'
        # Native packet TTL distinguishes the two initial TTL families after routing.
        lines.extend(
            (
                f"  {match} ip ttl <= 64 ip ttl set 64",
                f"  {match} ip ttl > 64 ip ttl set 128",
                f"  {match} tcp flags & (syn | ack) == syn tcp option timestamp exists queue num 4948",
                f"  {match} tcp flags & (syn | ack) == syn tcp option timestamp missing queue num 4947",
            )
        )
    return "\n".join([*lines, " }", "}", ""])


def fingerprint_start(config):
    if not Capabilities.from_config(config).forwarding_fingerprint:
        raise ValueError("Forwarding fingerprinting is disabled")
    queues = Path("/proc/net/netfilter/nfnetlink_queue").read_text()
    listening = {line.split()[0] for line in queues.splitlines() if line.split()}
    if not {"4947", "4948"} <= listening:
        raise RuntimeError("Fingerprint queue listeners are not ready")
    replace_table("ip", "vps_fingerprint_forward", fingerprint_rules(config))


def fingerprint_stop(config):
    remove_table("ip", "vps_fingerprint_forward")


def local_stop():
    rules = command("iptables", "-S", "ufw-user-forward").splitlines()
    for line in rules:
        args = shlex.split(line)
        if "--comment" in args and args[args.index("--comment") + 1].startswith("tcpfp-test:"):
            command("iptables", "-D", *args[1:])
    remove_table("inet", "tcpfp_test")
    remove_table("ip", "tcpfp_test_nat")
    # Remove the host ends while named namespaces still keep their peers alive.
    # Namespace deletion can otherwise race asynchronous veth destruction.
    links = {item["ifname"] for item in json.loads(command("ip", "-j", "link", "show"))}
    for name in ("tfp-win0", "tfp-ios0"):
        if name in links:
            command("ip", "link", "delete", name)
    for name in ("tcpfp-windows-test", "tcpfp-ios-test"):
        if Path("/run/netns", name).exists():
            command("ip", "netns", "delete", name)


def write_snapshot(config):
    import grp

    if not Capabilities.from_config(config).wireguard:
        raise ValueError("WireGuard is disabled")
    identity = json.loads(Path("/etc/vps-ops/identity.json").read_text())
    peer_users = {peer["public"]: peer["user"] for peer in peers(identity)}
    epoch = (
        Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        + ":"
        + Path(f"/sys/class/net/{INTERFACE}/ifindex").read_text().strip()
    )
    counters = {}
    for line in command("wg", "show", INTERFACE, "transfer").splitlines():
        key, received, sent = line.split()
        if key in peer_users:
            counters[peer_users[key]] = {
                "user": peer_users[key],
                "upload": int(received),
                "download": int(sent),
            }
    if set(counters) != set(peer_users.values()):
        raise ValueError("WireGuard peer counters are incomplete")
    directory = Path("/run/vps-ops")
    directory.mkdir(mode=0o750, exist_ok=True)
    group = grp.getgrnam("mihomo").gr_gid
    os.chown(directory, 0, group)
    directory.chmod(0o750)
    target = directory / "wireguard-usage.json"
    save(
        target,
        {"time": time.time(), "epoch": epoch, "users": list(counters.values())},
        0o640,
        group=group,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature", choices=("wireguard", "fingerprint", "snapshot", "local"))
    parser.add_argument("action", choices=("start", "stop"), nargs="?", default="start")
    parser.add_argument("--config", type=Path, default=Path("/etc/vps-ops/config.yaml"))
    args = parser.parse_args()
    if args.feature == "local":
        if args.action != "stop":
            raise ValueError("Local cleanup requires stop")
        local_stop()
        return
    config = yaml.safe_load(args.config.read_text())
    if args.feature == "snapshot":
        write_snapshot(config)
    else:
        {
            ("wireguard", "start"): wireguard_start,
            ("wireguard", "stop"): wireguard_stop,
            ("fingerprint", "start"): fingerprint_start,
            ("fingerprint", "stop"): fingerprint_stop,
        }[args.feature, args.action](config)


if __name__ == "__main__":
    main()
