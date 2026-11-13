"""Server-side installation of the selected node capabilities."""

import gzip
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from vps_ops.checks import checks
from vps_ops.deploy.render import render, save
from vps_ops.runtime import DEFAULT, emit, run

from .components import ACME, GO, MIHOMO, command, download, install


def prepare_proxy(c):
    assets = Path(__file__).parent / "assets/system"
    if not assets.exists():
        assets = Path(__file__).resolve().parents[3] / "system"
    with tempfile.TemporaryDirectory(prefix="vps-build-") as temp:
        temp = Path(temp)
        if not Path("/usr/local/lib/tcpfp/mirage-syn").exists():
            download(GO, temp / "go.tar.gz")
            with tarfile.open(temp / "go.tar.gz") as archive:
                archive.extractall(temp, filter="data")
            env = os.environ | {
                "GOMAXPROCS": "1",
                "GOMEMLIMIT": "384MiB",
                "GOTOOLCHAIN": "local",
                "GOCACHE": str(temp / "cache"),
                "GOMODCACHE": str(temp / "mod"),
            }
            command(
                str(temp / "go/bin/go"),
                "build",
                "-p",
                "1",
                "-o",
                str(temp / "mirage-syn"),
                "./cmd/mirage-syn",
                cwd=assets / "tcpfp/mirage-syn",
                env=env,
            )
            install(temp / "mirage-syn", "/usr/local/lib/tcpfp/mirage-syn", 0o755)
        command("make", "-C", str(assets / "tcpfp/ebpf"), "OUTPUT=" + str(temp / "syn_rewrite.o"))
        install(temp / "syn_rewrite.o", "/usr/local/lib/tcpfp/ebpf/syn_rewrite.o")
        download(MIHOMO, temp / "mihomo.gz")
        binary = gzip.decompress((temp / "mihomo.gz").read_bytes())
        (temp / "mihomo").write_bytes(binary)
        install(temp / "mihomo", "/usr/local/bin/mihomo", 0o755)
        install("/usr/local/bin/mihomo", "/usr/local/lib/tcpfp/mihomo", 0o755)
        download(ACME, temp / "acme.tar.gz")
        with tarfile.open(temp / "acme.tar.gz") as archive:
            archive.extractall(temp, filter="data")
        if not Path("/opt/acme.sh/acme.sh").exists():
            shutil.copytree(temp / "acme.sh-3.1.6", "/opt/acme.sh")
    c["wan"] = json.loads(run(["ip", "-j", "route", "get", "1.1.1.1"]))[0]["dev"]
    render(c, assets)
    with tempfile.TemporaryDirectory(prefix="vps-network-") as folder:
        generated = Path(folder) / "network"
        command(
            sys.executable,
            str(assets / "tcpfp/render_assets.py"),
            "--public-ipv4",
            c["public_ipv4"],
            "--wan",
            c["wan"],
            "--output",
            str(generated),
        )
        for name in ("host.nft", "windows.nft", "ios.nft", "plan.json"):
            install(generated / name, "/etc/tcpfp/" + name, 0o600)
    for f in (assets / "tcpfp").glob("*.py"):
        install(f, "/usr/local/lib/tcpfp/" + f.name)
    for f in ("network.sh", "preflight.py", "fingerprint-engines.json", "syn-windows.json"):
        install(assets / "tcpfp" / f, "/etc/tcpfp/" + f, 0o700 if f.endswith("sh") else 0o600)
    for folder in ("mihomo", "tcpfp/systemd", "subscriptions"):
        for f in (assets / folder).glob("*.service"):
            install(f, "/etc/systemd/system/" + f.name)
    install(assets / "subscriptions/vps-rules.path", "/etc/systemd/system/vps-rules.path")
    install(
        assets / "mihomo/mihomo-private-controller.conf",
        "/etc/systemd/system/mihomo.service.d/40-private-controller.conf",
    )
    install(
        assets / "tcpfp/systemd/tcpfp-windows-test.service.d/20-syn-capture.conf",
        "/etc/systemd/system/tcpfp-windows-test.service.d/20-syn-capture.conf",
    )


def start_proxy(c):
    for port in ("8443/tcp", "8443/udp", "9444/tcp", "9443/tcp"):
        command("ufw", "allow", port)
    command("modprobe", "tcp_bbr")
    save("/etc/modules-load.d/vps-ops.conf", "tcp_bbr\n", 0o644)
    command(
        "/usr/local/bin/mihomo",
        "-t",
        "-d",
        "/var/lib/mihomo",
        "-f",
        "/etc/mihomo/config.yaml",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    command(
        "caddy",
        "validate",
        "--config",
        "/etc/caddy/Caddyfile",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    command("systemctl", "daemon-reload")
    for unit in c["services"]:
        if unit != "tailscaled":
            command("systemctl", "enable", "--now", unit)
    command(
        "systemctl",
        "restart",
        "tcpfp-windows-test",
        "tcpfp-ios-test",
        "mihomo",
        "mihomo-observed",
        "caddy",
    )


def finish(c):
    runtime = {k: c[k] for k in ("mode", "services")}
    if c["mode"] != "tailscale":
        runtime["subscription_host"] = c["domain"]
    save("/etc/vps-ops/config.yaml", yaml_dump(runtime))
    if c["mode"] != "mihomo":
        current = json.loads(run(["tailscale", "status", "--json"]))
        if current.get("BackendState") == "Running":
            command("tailscale", "set", "--advertise-exit-node", "--hostname=" + c["name"])
        else:
            command(
                "tailscale",
                "up",
                "--advertise-exit-node",
                "--hostname=" + c["name"],
                "--timeout=15m",
            )
        status = json.loads(run(["tailscale", "status", "--json"]))
        advertised = status.get("Self", {}).get("ExitNodeOption", False)
        print(
            "Tailscale 已登录；出口节点状态："
            + ("已提供出口能力" if advertised else "等待控制台批准或状态同步")
            + "。请在客户端选择此出口。",
            flush=True,
        )
    result = checks(DEFAULT | runtime, "all")
    emit(result)
    if any(r["state"] == "失败" for r in result):
        raise RuntimeError("部署后检查失败")
    print(
        "部署完成；如已安装代理，可用 deploy show subscriptions 查看私有订阅地址；SSH 会话继续保留。",
        flush=True,
    )


def yaml_dump(value):
    import yaml

    return yaml.safe_dump(value)


def main():
    action, folder = sys.argv[1:]
    work = Path(folder)
    c = json.loads((work / "node.json").read_text())
    save("/etc/vps-ops/deployment.json", {k: v for k, v in c.items() if k != "authorized_key"})
    if action == "prepare":
        prepare_proxy(c)
    elif action == "certificate":
        from .certificates import configure

        configure(c, work)
    elif action == "start":
        start_proxy(c)
    elif action == "finish":
        finish(c)
    else:
        raise ValueError("unknown deployment action")


if __name__ == "__main__":
    main()
