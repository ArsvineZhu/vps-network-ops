"""Read-only eligibility checks before provisioning a fresh node."""

import json
import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path


def verify(c):
    release = dict(
        line.split("=", 1)
        for line in Path("/etc/os-release").read_text().splitlines()
        if "=" in line
    )
    if (
        release.get("ID", "").strip('"') != "ubuntu"
        or release.get("VERSION_ID", "").strip('"') != "24.04"
        or platform.machine() != "x86_64"
        or os.geteuid() != 0
    ):
        raise RuntimeError("Ubuntu 24.04 AMD64 and root access are required")
    if shutil.disk_usage("/").free < 4 * 1024**3:
        raise RuntimeError("At least 4 GiB of free disk space is required")
    if not os.environ.get("SSH_CONNECTION"):
        raise RuntimeError(
            "SSH connection information is missing; cannot preserve the management port"
        )
    marker = Path("/etc/vps-ops/deployment.json")
    if marker.exists():
        previous = json.loads(marker.read_text())
        if previous["mode"] != c["mode"]:
            raise RuntimeError(
                "Existing node uses another deployment mode; automatic mode migration is not supported"
            )
    else:
        for path in (
            "/etc/mihomo/config.yaml",
            "/etc/caddy/Caddyfile",
            "/etc/tailscale/tailscaled.conf",
            "/var/lib/tailscale/tailscaled.state",
            "/etc/clash/config.yaml",
        ):
            if Path(path).exists():
                raise RuntimeError("Unmanaged configuration already exists: " + path)
        if subprocess.run(["systemctl", "is-active", "--quiet", "tailscaled"]).returncode == 0:
            raise RuntimeError("An unmanaged Tailscale node already exists")
    if c["mode"] != "tailscale":
        addresses = {x[4][0] for x in socket.getaddrinfo(c["domain"], None, socket.AF_INET)}
        if addresses != {c["public_ipv4"]}:
            raise RuntimeError(
                "Subscription A record must point only to this node's public IPv4; disable CDN proxying"
            )
        try:
            if socket.getaddrinfo(c["domain"], None, socket.AF_INET6):
                raise RuntimeError("Remove subscription AAAA records for this IPv4 node")
        except socket.gaierror:
            pass


if __name__ == "__main__":
    try:
        verify(json.loads(Path("node.json").read_text()))
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from None
