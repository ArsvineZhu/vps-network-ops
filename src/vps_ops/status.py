"""Collect the requested parts of the server status."""

import subprocess
from pathlib import Path

from .runtime import run

SECTIONS = ("system", "resources", "services", "network", "firewall", "updates", "errors")


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
            raise ValueError(f"Service is not configured: {name}")
    return list(dict.fromkeys(selected))


def collect(configured_services, selected_sections=(), *, summary=False, selected_services=()):
    """Collect machine-readable status fields without querying unrelated sections."""
    sections = set(selected_sections)
    data = {}

    def query(key, args):
        try:
            data[key] = run(args)
        except (RuntimeError, OSError, subprocess.SubprocessError):
            data[key] = "Query failed"

    if summary or "system" in sections:
        query("system", ["uname", "-sr"])
        query("uptime", ["uptime"])
    if summary or "resources" in sections:
        query("memory", ["free", "-h"])
        query("disks", ["df", "-hT", "/"] if summary else ["df", "-hT"])
    if "network" in sections:
        query("listeners", ["ss", "-lntu"])
        query("routes", ["ip", "route"])
    if "firewall" in sections:
        query("firewall", ["ufw", "status"])
    if (summary or "services" in sections) and (not selected_services or sections == set(SECTIONS)):
        query("failed_services", ["systemctl", "--failed", "--no-pager"])
    if "updates" in sections:
        query("updates", ["apt", "list", "--upgradable"])
    if summary or "services" in sections:
        data["services"] = {}
        for service in selected_services or configured_services:
            try:
                data["services"][service] = run(
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
                data["services"][service] = "Query failed"
    if "system" in sections:
        try:
            data["boot_id"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError:
            data["boot_id"] = "Query failed"
    if "errors" in sections:
        try:
            data["error_count_24h"] = len(
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
            data["error_count_24h"] = "Query failed"
    if "network" in sections:
        query("namespaces", ["ip", "netns", "list"])
    if summary or "system" in sections or "updates" in sections:
        data["reboot_required"] = Path("/var/run/reboot-required").exists()
    return data
