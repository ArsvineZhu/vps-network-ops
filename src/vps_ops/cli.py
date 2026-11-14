"""Unified VPS operations."""

import argparse
import importlib
import json
import os
import shlex
import subprocess
import sys

from .checks import checks
from .output import emit
from .runtime import config, resolver, run


def dispatch_module(module, args):
    original = sys.argv
    try:
        sys.argv = ["vps-ops " + module, *args]
        return importlib.import_module("vps_ops." + module).main() or 0
    finally:
        sys.argv = original


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

        deploy_main(rest, machine=a.json)
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
        return dispatch_module(module, rest)
    if cmd == "usage":
        if not rest or rest[0] not in ("report", "serve"):
            p.error("usage report|serve")
        if rest[0] == "serve":
            dispatch_module("usage_daemon", ["--serve", *rest[1:]])
        else:
            import contextlib
            import io

            report_args = rest[1:]
            report_json = "--json" in report_args
            if report_json:
                report_args.remove("--json")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                dispatch_module("usage_daemon", ["--report", *report_args])
            emit(json.loads(buf.getvalue()), a.json or report_json, view="usage")
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
    if cmd == "status":
        from . import status

        options = status.arguments(rest)
        c = config(a.config)
        try:
            selected_services = status.select_services(options.service or [], c["services"])
        except ValueError as exc:
            p.error(str(exc))
        sections = set(status.SECTIONS) if options.all else set(options.sections or [])
        summary = not sections and not selected_services
        if selected_services:
            sections.add("services")
        data = status.collect(
            c["services"], sections, summary=summary, selected_services=selected_services
        )
        emit(data, a.json or options.json, view="status", summary=summary)
        return 0
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
    if cmd == "logs":
        lp = argparse.ArgumentParser()
        lp.add_argument("service")
        lp.add_argument("--since", default="24 hours ago")
        lp.add_argument("--lines", type=int, default=50)
        lp.add_argument("--follow", action="store_true")
        lp.add_argument("--json", action="store_true", help="逐行输出 JSON 日志")
        x = lp.parse_args(rest)
        if x.service.removesuffix(".service") not in c["services"]:
            p.error("未知服务")
        args = ["journalctl", "-u", x.service, "--since", x.since, "-n", str(x.lines), "--no-pager"]
        machine = a.json or x.json
        if machine:
            args += ["-o", "json"]
        if x.follow:
            args.append("-f")
        from .runtime import filtered_logs

        return filtered_logs(args, c, machine=machine)
    if cmd == "service":
        if (
            len(rest) != 2
            or rest[0] not in ("status", "start", "stop", "restart")
            or rest[1] not in c["services"]
        ):
            p.error("service <操作> <已配置服务>")
        if rest[0] == "status":
            return subprocess.call(["systemctl", *rest, "--full", "--no-pager", "--lines=0"])
        return subprocess.call(["systemctl", *rest, "--no-pager"])
    if cmd == "packages":
        if rest == ["list"]:
            emit({"更新": run(["apt", "list", "--upgradable"])}, a.json, view="status")
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
