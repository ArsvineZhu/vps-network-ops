"""Install selected node capabilities while preserving identity and usage."""

import gzip
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import yaml

from vps_ops.capabilities import Capabilities
from vps_ops.checks import checks
from vps_ops.files import save
from vps_ops.runtime import config, run

from .components import ACME, GO, MIHOMO, command, download, install
from .render import render


def asset_directory():
    packaged = Path(__file__).parent / "assets/system"
    return packaged if packaged.exists() else Path(__file__).resolve().parents[3] / "system"


def reconcile(c):
    """Stop capabilities removed from a managed node before replacing its configuration."""
    marker = Path("/etc/vps-ops/deployment.json")
    if not marker.exists():
        return
    previous = Capabilities.from_config(json.loads(marker.read_text()))
    selected = Capabilities.from_config(c)
    removed = set(previous.services) - set(selected.services)
    for unit in reversed(previous.services):
        if unit in removed:
            command("systemctl", "disable", "--now", unit)
    if previous.mihomo and previous.fingerprint and not (selected.mihomo and selected.fingerprint):
        from vps_ops.forwarding import local_stop

        local_stop()
    for port in set(previous.ports) - set(selected.ports):
        command("ufw", "--force", "delete", "allow", port)
    if previous.tailscale and not selected.tailscale:
        command("ufw", "--force", "delete", "allow", "in", "on", "tailscale0")
    if previous.mihomo and not selected.mihomo:
        cron = Path("/etc/cron.d/vps-acme")
        cron.unlink(missing_ok=True)
        if (
            subprocess.run(
                ["nft", "list", "table", "inet", "mihomo_guard"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        ):
            command("nft", "delete", "table", "inet", "mihomo_guard")


def prepare(c):
    plan = Capabilities.from_config(c)
    reconcile(c)
    c["wan"] = json.loads(run(["ip", "-j", "route", "get", "1.1.1.1"]))[0]["dev"]
    c["services"] = plan.services
    runtime = {key: c[key] for key in ("name", "wan", "mode", "features", "services")}
    if plan.mihomo:
        runtime["subscription_host"] = c["domain"]
    save("/etc/vps-ops/config.yaml", yaml.safe_dump(runtime))
    assets = asset_directory()
    with tempfile.TemporaryDirectory(prefix="vps-build-") as folder:
        temp = Path(folder)
        if plan.fingerprint:
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
        if plan.mihomo:
            download(MIHOMO, temp / "mihomo.gz")
            with gzip.open(temp / "mihomo.gz", "rb") as source, (temp / "mihomo").open("wb") as out:
                shutil.copyfileobj(source, out)
            install(temp / "mihomo", "/usr/local/bin/mihomo", 0o755)
            download(ACME, temp / "acme.tar.gz")
            with tarfile.open(temp / "acme.tar.gz") as archive:
                archive.extractall(temp, filter="data")
            shutil.copytree(temp / "acme.sh-3.1.6", "/opt/acme.sh", dirs_exist_ok=True)
            render(c, assets)
            for folder in ("mihomo", "subscriptions"):
                for unit in (assets / folder).glob("*.service"):
                    install(unit, "/etc/systemd/system/" + unit.name)
            install(assets / "subscriptions/vps-rules.path", "/etc/systemd/system/vps-rules.path")
            install(
                assets / "mihomo/mihomo-private-controller.conf",
                "/etc/systemd/system/mihomo.service.d/40-private-controller.conf",
            )
        if plan.mihomo and plan.fingerprint:
            command(
                "make", "-C", str(assets / "tcpfp/ebpf"), "OUTPUT=" + str(temp / "syn_rewrite.o")
            )
            install(temp / "syn_rewrite.o", "/usr/local/lib/tcpfp/ebpf/syn_rewrite.o")
            install("/usr/local/bin/mihomo", "/usr/local/lib/tcpfp/mihomo", 0o755)
            generated = temp / "network"
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
            for source in (assets / "tcpfp").glob("*.py"):
                install(source, "/usr/local/lib/tcpfp/" + source.name)
            for name in (
                "network.sh",
                "preflight.py",
                "fingerprint-engines.json",
                "syn-windows.json",
            ):
                install(
                    assets / "tcpfp" / name,
                    "/etc/tcpfp/" + name,
                    0o700 if name.endswith("sh") else 0o600,
                )
            for unit in (assets / "tcpfp/systemd").glob("*.service"):
                install(unit, "/etc/systemd/system/" + unit.name)
            install(
                assets / "tcpfp/systemd/tcpfp-windows-test.service.d/20-syn-capture.conf",
                "/etc/systemd/system/tcpfp-windows-test.service.d/20-syn-capture.conf",
            )
    from .network import install as install_network

    install_network(c)
    command("systemctl", "daemon-reload")
    save("/etc/vps-ops/deployment.json", {k: v for k, v in c.items() if k != "authorized_key"})


def start(c):
    plan = Capabilities.from_config(c)
    for port in plan.ports:
        command("ufw", "allow", port)
    if plan.tailscale:
        command("ufw", "allow", "in", "on", "tailscale0")
    if plan.mihomo:
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
    command("systemctl", "enable", *plan.services)
    command("systemctl", "restart", *plan.services)


def finish(c):
    plan = Capabilities.from_config(c)
    authorization = None
    if plan.tailscale:
        from vps_ops.tailscale import configure

        authorization = configure(c["name"])
    result = checks(config("/etc/vps-ops/config.yaml"), "all")
    readiness = "ready"
    if any(item["state"] == "fail" for item in result):
        readiness = "failed"
    elif authorization and authorization["state"] != "ready":
        readiness = "pending"
    return {
        "checks": result,
        "tailscale": authorization,
        "readiness": readiness,
        "subscription": plan.mihomo,
        "wireguard": plan.wireguard,
    }


def main():
    action, folder = sys.argv[1:]
    work = Path(folder)
    c = json.loads((work / "node.json").read_text())
    if action == "prepare":
        prepare(c)
    elif action == "certificate":
        from .certificates import configure

        configure(c, work)
    elif action == "start":
        start(c)
    elif action == "finish":
        from vps_ops.output import emit

        result = finish(c)
        emit(result, view="deployment")
        if any(item["state"] == "fail" for item in result["checks"]):
            raise RuntimeError("Post-deployment checks failed")
    else:
        raise ValueError("Unknown deployment action")


if __name__ == "__main__":
    main()
