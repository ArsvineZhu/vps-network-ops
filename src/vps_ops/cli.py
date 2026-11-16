"""CLI orchestration: parse input, call operations, and present results."""

import os
import shlex
import subprocess
import sys

import yaml

from . import arguments, output, status
from .checks import checks
from .runtime import config, journal, resolver, run


def execute(argv):
    try:
        return _execute(argv)
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        subprocess.SubprocessError,
        yaml.YAMLError,
    ) as exc:
        output.error(exc)
        return 1


def _execute(argv):
    parser = arguments.parser()
    a = parser.parse_args(argv)
    cmd = a.command
    if cmd == "deploy":
        from . import prompts
        from .deploy import client

        if a.action == "init":
            data = client.init(a.deployment, prompts.deployment())
            output.emit(data, a.json, view="init")
        elif a.action == "apply":
            client.apply(
                a.deployment,
                prompt_secret=prompts.dns_secret,
                notify=output.notice,
                stream=output.write_line,
            )
        elif a.deployment == "subscriptions":
            output.emit(client.subscriptions(), a.json, view="subscriptions")
        else:
            parser.error("deploy show only supports subscriptions")
        return 0
    if cmd == "member":
        from .new_member import create

        output.emit(create(a.public_template, a.member, a.output, a.policy), a.json, view="member")
        return 0
    if cmd == "profile":
        from .clash_profile import generate_file

        if a.kind == "profile" and not a.policy:
            parser.error("A complete profile requires --policy")
        output.emit(
            generate_file(a.descriptor, a.output, policy=a.policy, kind=a.kind),
            a.json,
            view="profile",
        )
        return 0
    if cmd == "subscription":
        from .subscription_policy import apply

        if bool(a.profile) == bool(a.directory) or (a.directory and a.output):
            parser.error("Choose either a subscription file or a directory")
        output.emit(
            apply(a.policy, profile=a.profile, directory=a.directory, output=a.output),
            a.json,
            view="subscription",
        )
        return 0
    if cmd == "certificate":
        from .certificate_check import check

        try:
            data = check(a.cert, a.hostname, a.min_days)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from None
        output.emit(data, a.json, view="certificate")
        return 0
    if cmd == "usage":
        from .usage_daemon import read_report, serve

        if a.action == "serve":
            serve(a.collector_config)
        else:
            output.emit(read_report(a.collector_config), a.json, view="usage")
        return 0
    if cmd == "controller":
        from .check_socket_dir import check

        output.emit(check(), a.json, view="controller")
        return 0
    if cmd == "wait":
        from .wait_listener import wait

        output.emit(wait(a.service, a.port, a.seconds), a.json, view="listener")
        return 0
    if cmd == "connect":
        from .transport import ssh_command, wait_ssh

        args = ssh_command(a.target, port=a.port, user=a.user, identity=a.identity, tty=True)
        if a.wait:
            wait_ssh(args, a.wait)
        return subprocess.call([*args, "vps-ops shell"])
    if cmd == "shell":
        return shell(a.config)
    c = config(a.config)
    if cmd == "status":
        try:
            selected_services = status.select_services(a.service or [], c["services"])
        except ValueError as exc:
            parser.error(str(exc))
        sections = set(status.SECTIONS) if a.all else set(a.sections or [])
        summary = not sections and not selected_services
        if selected_services:
            sections.add("services")
        data = status.collect(
            c["services"], sections, summary=summary, selected_services=selected_services
        )
        output.emit(data, a.json, view="status", summary=summary)
        return 0
    if cmd in ("check", "dns"):
        if cmd == "dns" and a.action == "repair":
            resolver()
        result = checks(c, a.section if cmd == "check" else "dns")
        output.emit(result, a.json)
        return int(any(item["state"] == "fail" for item in result))
    if cmd == "logs":
        if a.service.removesuffix(".service") not in c["services"]:
            parser.error("Service is not configured")
        args = ["journalctl", "-u", a.service, "--since", a.since, "-n", str(a.lines), "--no-pager"]
        if a.json:
            args += ["-o", "json"]
        if a.follow:
            args.append("-f")
        records = journal(args, c, machine=a.json)
        try:
            for record in records:
                output.emit_log(record, machine=a.json)
        finally:
            records.close()
        return 0
    if cmd == "service":
        if a.service not in c["services"]:
            parser.error("Service is not configured")
        args = ["systemctl", a.action, a.service, "--no-pager"]
        if a.action == "status":
            args += ["--full", "--lines=0"]
        return subprocess.call(args)
    if cmd == "packages":
        if a.action == "list":
            output.emit({"updates": run(["apt", "list", "--upgradable"])}, a.json, view="status")
            return 0
        if run(["dpkg", "--audit"]):
            raise RuntimeError("dpkg reported an inconsistent state; upgrade stopped")
        subprocess.run(["apt-get", "update"], check=True)
        subprocess.run(["apt-get", "-s", "--no-remove", "upgrade"], check=True)
        return subprocess.call(
            ["apt-get", "--no-remove", "-o", "Dpkg::Options::=--force-confold", "-y", "upgrade"],
            env=os.environ | {"DEBIAN_FRONTEND": "noninteractive"},
        )
    if cmd == "reboot":
        output.notice("rebooting")
        return subprocess.call(["systemctl", "reboot"])
    return 0


def shell(config_path):
    while True:
        try:
            line = input("vps-ops> ")
        except EOFError:
            return 0
        except KeyboardInterrupt:
            output.write_line("")
            continue
        if line.strip() in ("exit", "quit"):
            return 0
        if line.strip() == "help":
            line = "--help"
        if not line.strip():
            continue
        try:
            execute(["--config", config_path, *shlex.split(line)])
        except (SystemExit, KeyboardInterrupt):
            pass


def main():
    try:
        raise SystemExit(execute(sys.argv[1:]))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
