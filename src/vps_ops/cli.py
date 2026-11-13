"""Unified VPS operations."""

import argparse
import importlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from .checks import checks
from .runtime import config, emit, resolver, run


def dispatch_module(module, args):
    sys.argv = ["vps-ops " + module, *args]
    importlib.import_module("vps_ops." + module).main()


def execute(argv):
    p = argparse.ArgumentParser(prog="vps-ops", description="VPS 检查与运维")
    p.add_argument("--config", default="/etc/vps-ops/config.yaml")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "command",
        choices=[
            "deploy",
            "connect",
            "shell",
            "status",
            "check",
            "logs",
            "usage",
            "dns",
            "service",
            "packages",
            "reboot",
            "member",
            "profile",
            "subscription",
            "certificate",
            "controller",
            "wait",
        ],
    )
    command_index = next((i for i, arg in enumerate(argv) if arg in p._actions[-1].choices), None)
    if command_index is None:
        a = p.parse_args(argv)
        rest = []
    else:
        a = p.parse_args(argv[: command_index + 1])
        rest = argv[command_index + 1 :]
    cmd = a.command
    if cmd == "deploy":
        from .deploy.client import main as deploy_main

        deploy_main(rest)
        return 0
    if cmd in ("member", "profile", "subscription", "certificate"):
        expected, module = {
            "member": ("create", "new_member"),
            "profile": ("generate", "clash_profile"),
            "subscription": ("apply", "subscription_policy"),
            "certificate": ("check", "certificate_check"),
        }[cmd]
        if not rest or rest.pop(0) != expected:
            p.error(f"需要 {cmd} {expected}")
        dispatch_module(module, rest)
        return 0
    if cmd == "usage":
        if not rest or rest[0] not in ("report", "serve"):
            p.error("usage report|serve")
        if rest[0] == "serve":
            dispatch_module("usage_daemon", ["--serve", *rest[1:]])
        else:
            import contextlib
            import io

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                dispatch_module("usage_daemon", ["--report", *rest[1:]])
            emit(json.loads(buf.getvalue()), a.json)
        return 0
    if cmd == "controller":
        if rest != ["check-directory"]:
            p.error("controller check-directory")
        importlib.import_module("vps_ops.check_socket_dir").main()
        return 0
    if cmd == "wait":
        if not rest or rest.pop(0) != "listener":
            p.error("wait listener")
        sys.argv = ["wait listener", *rest]
        importlib.import_module("vps_ops.wait_listener").main()
        return 0
    if cmd == "connect":
        cp = argparse.ArgumentParser(prog="vps-ops connect")
        cp.add_argument("target")
        cp.add_argument("--port", type=int)
        cp.add_argument("--user")
        cp.add_argument("--identity")
        cp.add_argument("--wait", type=float, default=0)
        x = cp.parse_args(rest)
        from .transport import ssh_command, wait_ssh

        args = ssh_command(x.target, port=x.port, user=x.user, identity=x.identity, tty=True)
        if x.wait:
            wait_ssh(args, x.wait)
        return subprocess.call([*args, "vps-ops shell"])
    if cmd == "shell":
        while True:
            try:
                line = input("vps-ops> ")
            except EOFError:
                return 0
            if line.strip() in ("exit", "quit"):
                return 0
            if line.strip() == "help":
                line = "--help"
            if not line.strip():
                continue
            try:
                execute(["--config", a.config, *shlex.split(line)])
            except SystemExit:
                pass
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
                print(
                    type(e).__name__ + ": 操作失败" if not isinstance(e, RuntimeError) else str(e),
                    file=sys.stderr,
                )
    c = config(a.config)
    if cmd == "check" or cmd == "dns" and rest == ["diagnose"]:
        section = rest[0] if cmd == "check" and rest else "dns" if cmd == "dns" else "all"
        if section not in ("all", "dns", "proxy", "subscription", "certificate", "tailscale"):
            p.error("未知检查")
        result = checks(c, section)
        emit(result, a.json)
        return int(any(r["state"] == "失败" for r in result))
    if cmd == "dns":
        if rest != ["repair"]:
            p.error("dns diagnose|repair")
        resolver()
        result = checks(c, "dns")
        emit(result, a.json)
        return int(any(x["state"] == "失败" for x in result))
    if cmd == "status":
        data = {}
        for key, args in {
            "系统": ["uname", "-sr"],
            "运行": ["uptime"],
            "内存": ["free", "-h"],
            "磁盘": ["df", "-hT"],
            "监听": ["ss", "-lnt"],
            "路由": ["ip", "route"],
            "防火墙": ["ufw", "status"],
            "失败服务": ["systemctl", "--failed", "--no-pager"],
            "更新": ["apt", "list", "--upgradable"],
        }.items():
            try:
                data[key] = run(args)
            except (RuntimeError, OSError, subprocess.SubprocessError):
                data[key] = "读取失败"
        data["服务"] = {
            s: run(
                ["systemctl", "show", s, "-p", "ActiveState", "-p", "SubState", "-p", "NRestarts"]
            )
            for s in c["services"]
        }
        data["启动标识"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        data["最近24小时错误数"] = len(
            run(
                ["journalctl", "-p", "0..3", "--since", "24 hours ago", "--no-pager", "-o", "json"]
            ).splitlines()
        )
        data["网络空间"] = run(["ip", "netns", "list"])
        data["需要重启"] = Path("/var/run/reboot-required").exists()
        emit(data, a.json)
        return 0
    if cmd == "logs":
        lp = argparse.ArgumentParser()
        lp.add_argument("service")
        lp.add_argument("--since", default="24 hours ago")
        lp.add_argument("--lines", type=int, default=50)
        lp.add_argument("--follow", action="store_true")
        x = lp.parse_args(rest)
        if x.service.removesuffix(".service") not in c["services"]:
            p.error("未知服务")
        args = ["journalctl", "-u", x.service, "--since", x.since, "-n", str(x.lines), "--no-pager"]
        if x.follow:
            args.append("-f")
        from .runtime import filtered_logs

        return filtered_logs(args, c)
    if cmd == "service":
        if (
            len(rest) != 2
            or rest[0] not in ("status", "start", "stop", "restart")
            or rest[1] not in c["services"]
        ):
            p.error("service <操作> <已配置服务>")
        return subprocess.call(["systemctl", *rest, "--no-pager"])
    if cmd == "packages":
        if rest == ["list"]:
            print(run(["apt", "list", "--upgradable"]))
            return 0
        if rest != ["upgrade"]:
            p.error("packages list|upgrade")
        audit = run(["dpkg", "--audit"])
        if audit:
            raise RuntimeError("dpkg 状态异常，更新已停止")
        subprocess.run(["apt-get", "update"], check=True)
        subprocess.run(["apt-get", "-s", "--no-remove", "upgrade"], check=True)
        return subprocess.call(
            ["apt-get", "--no-remove", "-o", "Dpkg::Options::=--force-confold", "-y", "upgrade"],
            env=os.environ | {"DEBIAN_FRONTEND": "noninteractive"},
        )
    if cmd == "reboot":
        print("正在重启，SSH 连接将中断。", flush=True)
        return subprocess.call(["systemctl", "reboot"])
    return 0


def main():
    try:
        raise SystemExit(execute(sys.argv[1:]))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as e:
        print(
            str(e) if isinstance(e, RuntimeError) else type(e).__name__ + ": 操作失败",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
