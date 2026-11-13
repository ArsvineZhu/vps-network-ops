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
        raise RuntimeError("需要 Ubuntu 24.04 AMD64，并以 root 登录")
    if shutil.disk_usage("/").free < 4 * 1024**3:
        raise RuntimeError("至少需要 4 GiB 可用磁盘空间")
    if not os.environ.get("SSH_CONNECTION"):
        raise RuntimeError("缺少 SSH 连接信息，无法保留实际管理端口")
    marker = Path("/etc/vps-ops/deployment.json")
    if marker.exists():
        previous = json.loads(marker.read_text())
        if previous["mode"] != c["mode"]:
            raise RuntimeError("已有节点的部署模式不同，自动部署不执行模式迁移")
    else:
        for path in (
            "/etc/mihomo/config.yaml",
            "/etc/caddy/Caddyfile",
            "/etc/tailscale/tailscaled.conf",
            "/var/lib/tailscale/tailscaled.state",
            "/etc/clash/config.yaml",
        ):
            if Path(path).exists():
                raise RuntimeError("发现未受本工具管理的现有配置：" + path)
        if subprocess.run(["systemctl", "is-active", "--quiet", "tailscaled"]).returncode == 0:
            raise RuntimeError("发现未受本工具管理的 Tailscale 节点")
    if c["mode"] != "tailscale":
        addresses = {x[4][0] for x in socket.getaddrinfo(c["domain"], None, socket.AF_INET)}
        if addresses != {c["public_ipv4"]}:
            raise RuntimeError("订阅域名 A 记录应只指向该节点公网 IPv4，请关闭 CDN 代理")
        try:
            if socket.getaddrinfo(c["domain"], None, socket.AF_INET6):
                raise RuntimeError("IPv4 节点请移除订阅域名 AAAA 记录")
        except socket.gaierror:
            pass


if __name__ == "__main__":
    try:
        verify(json.loads(Path("node.json").read_text()))
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from None
