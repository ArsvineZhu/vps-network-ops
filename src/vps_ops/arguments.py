"""Command-line syntax; business modules accept explicit Python arguments."""

import argparse
from pathlib import Path

from .status import SECTIONS


def parser():
    root = argparse.ArgumentParser(prog="vps-ops", description="VPS checks and operations")
    root.add_argument("--config", default="/etc/vps-ops/config.yaml")
    root.add_argument("--json", action="store_true")
    commands = root.add_subparsers(dest="command", required=True)

    descriptions = {
        "device": "Register, list, show or revoke a device on this node",
        "add": "Register a device and apply its credentials immediately",
        "list": "List device identities without private URLs",
        "show": "Show a device and its private subscription URL",
        "revoke": "Revoke device credentials and remove its subscription",
        "sync": "Apply saved device changes to running services",
        "connect": "Open a persistent remote CLI session over OpenSSH",
        "shell": "Run commands in an interactive session",
        "status": "Show a server summary or selected status sections",
        "check": "Check service and network functionality",
        "dns": "Diagnose or repair namespace DNS",
        "logs": "Read service logs with credential redaction",
        "service": "Manage a configured systemd service",
        "packages": "List or upgrade distribution packages",
        "reboot": "Reboot the server",
        "usage": "Read cumulative usage or run the sampler",
        "report": "Read the existing usage database",
        "serve": "Run the usage sampler",
        "controller": "Validate the private controller directory",
        "wait": "Wait for a service listener",
        "listener": "Wait for a TCP listener owned by the service MainPID",
        "member": "Create private offline member materials",
        "create": "Generate a client profile and pending server identity",
        "profile": "Generate a local client profile or node provider",
        "generate": "Generate client configuration from a private node descriptor",
        "subscription": "Apply a shared routing policy to subscriptions",
        "apply": "Update a subscription file or directory",
        "certificate": "Check a local certificate hostname and validity",
        "deploy": "Initialize and deploy an Ubuntu 24.04 AMD64 node",
    }

    def command(name, parent=commands):
        item = parent.add_parser(name, help=descriptions[name], description=descriptions[name])
        item.add_argument(
            "--json",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Print report data as JSON",
        )
        return item

    connect = command("connect")
    connect.add_argument("target")
    connect.add_argument("--port", type=int)
    connect.add_argument("--user")
    connect.add_argument("--identity")
    connect.add_argument("--wait", type=float, default=0)
    command("shell")

    status = command("status")
    status.add_argument("--all", action="store_true", help="Show all status sections")
    for section in SECTIONS:
        status.add_argument("--" + section, dest="sections", action="append_const", const=section)
    status.add_argument(
        "--service", action="append", help="Select a configured service; repeatable"
    )

    check = command("check")
    check.add_argument(
        "section",
        nargs="?",
        default="all",
        choices=["all", "dns", "proxy", "subscription", "certificate", "tailscale"],
    )
    dns = command("dns")
    dns.add_argument("action", choices=["diagnose", "repair"])
    logs = command("logs")
    logs.add_argument("service")
    logs.add_argument("--since", default="24 hours ago")
    logs.add_argument("--lines", type=int, default=50)
    logs.add_argument("--follow", action="store_true")
    service = command("service")
    service.add_argument("action", choices=["status", "start", "stop", "restart"])
    service.add_argument("service")
    packages = command("packages")
    packages.add_argument("action", choices=["list", "upgrade"])
    command("reboot")

    usage = command("usage").add_subparsers(dest="action", required=True)
    for name in ("report", "serve"):
        item = command(name, usage)
        item.add_argument(
            "--config",
            dest="collector_config",
            type=Path,
            default=Path("/etc/mihomo-observed/collector.json"),
        )
    controller = command("controller")
    controller.add_argument("action", choices=["check-directory"])
    wait = command("wait").add_subparsers(dest="action", required=True)
    listener = command("listener", wait)
    listener.add_argument("service", help="systemd service name")
    listener.add_argument("port", type=int, help="TCP port")
    listener.add_argument(
        "--seconds", type=float, default=10, help="Timeout in seconds (default: 10)"
    )

    device = command("device").add_subparsers(dest="action", required=True)
    add = command("add", device)
    add.add_argument("name", nargs="?", help="Unique name for this physical device")
    add.add_argument(
        "--platform",
        choices=["Default", "Windows", "Apple"],
        help="Default profile for an unknown client",
    )
    command("list", device)
    command("sync", device)
    for action in ("show", "revoke"):
        entry = command(action, device)
        entry.add_argument("device", help="Device ID or active device name")

    member = command("member").add_subparsers(dest="action", required=True)
    create = command("create", member)
    create.add_argument("public_template", type=Path, help="Public server descriptor JSON")
    create.add_argument("member", help="Member label: letters, digits, underscores or hyphens")
    create.add_argument("output", type=Path, help="New private output directory")
    create.add_argument("--policy", required=True, type=Path, help="Shared routing policy")
    profile = command("profile").add_subparsers(dest="action", required=True)
    generate = command("generate", profile)
    generate.add_argument("descriptor", type=Path, help="Private node descriptor JSON")
    generate.add_argument("output", type=Path, help="New output file")
    generate.add_argument(
        "--policy", type=Path, help="Shared routing policy; required for a full profile"
    )
    generate.add_argument(
        "--kind",
        choices=["profile", "provider"],
        default="profile",
        help="Complete profile or proxy provider (default: profile)",
    )
    subscription = command("subscription").add_subparsers(dest="action", required=True)
    apply = command("apply", subscription)
    apply.add_argument("profile", nargs="?", type=Path, help="Single subscription file")
    apply.add_argument(
        "--directory", type=Path, help="Process all YAML subscriptions in this directory"
    )
    apply.add_argument("--policy", required=True, type=Path, help="Shared routing policy")
    apply.add_argument(
        "--output", type=Path, help="Output path; defaults to updating the input file"
    )
    certificate = command("certificate").add_subparsers(dest="action", required=True)
    cert = command("check", certificate)
    cert.add_argument("--cert", required=True, type=Path, help="Certificate file")
    cert.add_argument("--hostname", required=True, help="Expected DNS hostname")
    cert.add_argument(
        "--min-days", type=int, default=7, help="Minimum remaining validity (default: 7 days)"
    )
    deploy = command("deploy")
    deploy.add_argument("action", choices=["setup", "init", "configure", "plan", "apply", "show"])
    deploy.add_argument("deployment", help="Private YAML path, or subscriptions for show")
    return root
