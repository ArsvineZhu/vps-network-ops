"""Authenticated frontend checks using temporary private client state."""

import json
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import yaml

from .runtime import curl


def subscription(c, url, expected, *, user_agent=None, target=None):
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
        frontend = yaml.safe_load(Path(c["frontend_config"]).read_text())
        for platform, user in (("Windows", "windows-test"), ("Apple", "ios-test")):
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
            if f"IN-USER,{user},{platform}" not in frontend["rules"]:
                raise RuntimeError("Server TCP route is missing for this identity")
        primary = next((g for g in profile.get("proxy-groups", []) if g["name"] == "Nodes"), {})
        names = {n["name"] for n in profile["proxies"]}
        if set(primary.get("proxies", [])) != names:
            raise RuntimeError("Node selector does not include every identity and protocol")
        if primary.get("default-selected") != (target or "Windows") + " · VLESS":
            raise RuntimeError("Subscription default does not match the detected platform")
    return "HTTP 200; subscription content and identities match"


def frontend(c, protocol, target=None):
    nodes = []
    for path in Path(c["subscription_root"]).glob("*.yaml"):
        nodes.extend(yaml.safe_load(path.read_text()).get("proxies", []))
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
