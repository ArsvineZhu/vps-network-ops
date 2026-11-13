"""Authenticated frontend checks using temporary private client state."""

import json
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import yaml

from .runtime import curl


def frontend(c, protocol):
    nodes = []
    for path in Path(c["subscription_root"]).glob("*.yaml"):
        nodes.extend(yaml.safe_load(path.read_text()).get("proxies", []))
    node = next((n for n in nodes if n.get("type") == protocol), None)
    if node is None:
        raise RuntimeError("订阅中缺少对应协议节点")
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
                    raise RuntimeError("临时客户端启动失败")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    if time.monotonic() > end:
                        raise RuntimeError("临时客户端启动超时") from None
                    time.sleep(0.1)
            return curl(c["probe_url"], f"socks5h://127.0.0.1:{port}")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
