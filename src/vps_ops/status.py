"""Collect the requested parts of the server status."""

import argparse
import subprocess
from pathlib import Path

from .runtime import run

SECTIONS = {
    "system": "系统和启动信息",
    "resources": "内存和磁盘",
    "services": "服务状态",
    "network": "TCP 监听、路由和网络空间",
    "firewall": "防火墙规则",
    "updates": "软件更新和重启提示",
    "errors": "最近 24 小时的系统错误数量",
}


def arguments(args):
    parser = argparse.ArgumentParser(prog="vps-ops status", description="查看服务器状态")
    parser.add_argument("--all", action="store_true", help="显示全部状态")
    for name, description in SECTIONS.items():
        parser.add_argument(
            "--" + name, dest="sections", action="append_const", const=name, help=description
        )
    parser.add_argument("--service", action="append", metavar="名称", help="只查看指定服务，可重复")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    return parser.parse_args(args)


def select_services(names, configured_services):
    selected = []
    for name in names:
        if name in configured_services:
            selected.append(name)
        elif name.endswith(".service") and name.removesuffix(".service") in configured_services:
            selected.append(name.removesuffix(".service"))
        elif name + ".service" in configured_services:
            selected.append(name + ".service")
        else:
            raise ValueError(f"未配置服务：{name}")
    return list(dict.fromkeys(selected))


def collect(configured_services, selected_sections=(), *, summary=False, selected_services=()):
    """Retain the status JSON fields while avoiding unrelated system queries."""
    sections = set(selected_sections)
    data = {}

    def query(key, args):
        try:
            data[key] = run(args)
        except (RuntimeError, OSError, subprocess.SubprocessError):
            data[key] = "读取失败"

    if summary or "system" in sections:
        query("系统", ["uname", "-sr"])
        query("运行", ["uptime"])
    if summary or "resources" in sections:
        query("内存", ["free", "-h"])
        query("磁盘", ["df", "-hT", "/"] if summary else ["df", "-hT"])
    if "network" in sections:
        query("监听", ["ss", "-lnt"])
        query("路由", ["ip", "route"])
    if "firewall" in sections:
        query("防火墙", ["ufw", "status"])
    if (summary or "services" in sections) and (not selected_services or sections == set(SECTIONS)):
        query("失败服务", ["systemctl", "--failed", "--no-pager"])
    if "updates" in sections:
        query("更新", ["apt", "list", "--upgradable"])
    if summary or "services" in sections:
        data["服务"] = {}
        for service in selected_services or configured_services:
            try:
                data["服务"][service] = run(
                    [
                        "systemctl",
                        "show",
                        service,
                        "-p",
                        "ActiveState",
                        "-p",
                        "SubState",
                        "-p",
                        "NRestarts",
                    ]
                )
            except (RuntimeError, OSError, subprocess.SubprocessError):
                data["服务"][service] = "读取失败"
    if "system" in sections:
        try:
            data["启动标识"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError:
            data["启动标识"] = "读取失败"
    if "errors" in sections:
        try:
            data["最近24小时错误数"] = len(
                run(
                    [
                        "journalctl",
                        "-p",
                        "0..3",
                        "--since",
                        "24 hours ago",
                        "--no-pager",
                        "-o",
                        "json",
                    ]
                ).splitlines()
            )
        except (RuntimeError, OSError, subprocess.SubprocessError):
            data["最近24小时错误数"] = "读取失败"
    if "network" in sections:
        query("网络空间", ["ip", "netns", "list"])
    if summary or "system" in sections or "updates" in sections:
        data["需要重启"] = Path("/var/run/reboot-required").exists()
    return data
