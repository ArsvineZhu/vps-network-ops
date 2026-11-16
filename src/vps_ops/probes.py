"""Authenticated frontend checks using temporary private client state."""

import json
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import yaml

from . import identity
from .capabilities import Capabilities
from .fingerprint_profiles import PROFILES
from .runtime import curl, published_subscriptions, run


def subscription(c, device_id, url, expected, *, user_agent=None, target=""):
    """Verify delivered configuration without including credentials in diagnostics."""
    response = curl(
        url,
        resolve=f"{c['subscription_host']}:{c['subscription_port']}:127.0.0.1",
        user_agent=user_agent,
        body=True,
    )
    try:
        profile = yaml.safe_load(response)
        local = yaml.safe_load(expected.read_text())
    except yaml.YAMLError:
        raise RuntimeError("Subscription content is not valid YAML") from None
    if not isinstance(profile, dict) or profile != local:
        raise RuntimeError("Subscription response does not match the expected configuration")
    if target is not None:
        state = identity.load()
        device = state["devices"][device_id]
        plan = Capabilities.from_config(c)
        frontend = yaml.safe_load(Path(c["frontend_config"]).read_text())
        for fingerprint in PROFILES:
            platform = fingerprint.label
            principal = device["profiles"][fingerprint.key]
            user = principal["user"]
            expected_route = platform if plan.fingerprint else "DIRECT"
            if "IN-USER," + user + "," + expected_route not in frontend["rules"]:
                raise RuntimeError("Server TCP route is missing for this identity")
            for protocol in ("vless", "hysteria2", "anytls"):
                nodes = [
                    n
                    for n in profile.get("proxies", [])
                    if n.get("type") == protocol and n.get("name", "").startswith(platform + " · ")
                ]
                listeners = [x for x in frontend["listeners"] if x["type"] == protocol]
                if len(nodes) != 1 or len(listeners) != 1:
                    raise RuntimeError(
                        "Subscription must contain one node per identity and protocol"
                    )
                if protocol == "vless":
                    users = [x for x in listeners[0]["users"] if x["username"] == user]
                    valid = len(users) == 1 and nodes[0].get("uuid") == users[0]["uuid"]
                else:
                    valid = nodes[0].get("password") == listeners[0]["users"].get(user)
                if not valid:
                    raise RuntimeError("Subscription credentials do not match the server identity")
            if plan.wireguard:
                from .wireguard import client_node

                nodes = [
                    n
                    for n in profile.get("proxies", [])
                    if n.get("name") == platform + " · WireGuard"
                ]
                server = next(
                    n["server"]
                    for n in profile["proxies"]
                    if n.get("name") == platform + " · VLESS"
                )
                if nodes != [client_node(state, device_id, fingerprint.key, server)]:
                    raise RuntimeError(
                        "Subscription WireGuard credentials do not match the server identity"
                    )
        primary = next((g for g in profile.get("proxy-groups", []) if g["name"] == "Nodes"), {})
        names = {n["name"] for n in profile["proxies"]}
        if set(primary.get("proxies", [])) != names:
            raise RuntimeError("Node selector does not include every identity and protocol")
        suffix = " · WireGuard" if plan.wireguard else " · VLESS"
        if primary.get("default-selected") != (target or device["platform"]) + suffix:
            raise RuntimeError("Subscription default does not match the detected platform")
    return "HTTP 200; subscription content and identities match"


def frontend(c, protocol, target, *, device_id):
    if protocol not in ("vless", "hysteria2", "anytls"):
        raise ValueError(
            "WireGuard health checks inspect peers without loading device private keys into a probe"
        )
    profiles = published_subscriptions(c)[device_id]["files"]
    nodes = yaml.safe_load(profiles[target or ""].read_text())["proxies"]
    node = next(
        (
            n
            for n in nodes
            if n.get("type") == protocol
            and (target is None or n.get("name", "").startswith(target + " · "))
        ),
        None,
    )
    if node is None:
        raise RuntimeError("Subscription has no node for this protocol")
    node = dict(node, name="probe")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="vps-ops-") as directory:
        path = Path(directory) / "config.json"
        path.write_text(
            json.dumps(
                {
                    "mixed-port": port,
                    "bind-address": "127.0.0.1",
                    "allow-lan": False,
                    "log-level": "silent",
                    "proxies": [node],
                    "rules": ["MATCH,probe"],
                }
            )
        )
        path.chmod(0o600)
        process = subprocess.Popen(
            ["/usr/local/bin/mihomo", "-d", directory, "-f", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            end = time.monotonic() + 10
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Temporary client failed to start")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    if time.monotonic() > end:
                        raise RuntimeError("Temporary client startup timed out") from None
                    time.sleep(0.1)
            return curl(c["probe_url"], f"socks5h://127.0.0.1:{port}")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def wireguard_peer(device_id, profile_key):
    from .wireguard import peers

    state = identity.load()
    expected = next(
        peer
        for peer in peers(state)
        if peer["device_id"] == device_id and peer["profile"] == profile_key
    )
    lines = run(["wg", "show", "vps-ops", "dump"]).splitlines()[1:]
    matching = [line.split("\t") for line in lines if line.split("\t")[0] == expected["public"]]
    if len(matching) != 1 or matching[0][3] != expected["address"] + "/32":
        raise RuntimeError("WireGuard peer authentication or source address is missing")
    return int(matching[0][4]) > 0
