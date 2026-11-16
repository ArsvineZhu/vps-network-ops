"""Present operational results as readable text or JSON."""

import json
import os
import re
import sys
from datetime import datetime


def _lines(label, value):
    if isinstance(value, bool):
        return [f"{label}: {'yes' if value else 'no'}"]
    if value is None:
        return [f"{label}: Unknown"]
    lines = str(value).splitlines()
    if not lines:
        return [f"{label}: None"]
    if len(lines) == 1:
        return [f"{label}: {lines[0]}"]
    return [f"{label}:", *("  " + line for line in lines)]


def _service(raw):
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            fields[key] = value
    state = fields.get("ActiveState", "")
    substate = fields.get("SubState", "")
    if not state:
        return raw or "Unknown state", "unknown", False
    if state == "active":
        label = {"running": "Running", "exited": "Applied", "waiting": "Waiting"}.get(substate) or (
            f"Active ({substate})" if substate else "Active"
        )
        kind = "active"
    else:
        label = {
            "inactive": "Inactive",
            "failed": "Failed",
            "activating": "Starting",
            "deactivating": "Stopping",
            "reloading": "Reloading",
        }.get(state) or state
        if substate and substate not in ("dead", "failed"):
            label += f" ({substate})"
        kind = "attention"
    restarts = fields.get("NRestarts")
    if restarts is not None:
        label += f" (restarts: {restarts})"
    needs_attention = restarts is not None and restarts.isdecimal() and int(restarts) > 0
    return label, kind, needs_attention


def _listeners(value):
    lines = value.splitlines()
    if lines and lines[0].lstrip().lower().startswith("state"):
        lines = lines[1:]
    if not lines:
        return ["None"]
    rows = [line.split(maxsplit=5) for line in lines]
    if any(len(row) < 5 or row[0] != "LISTEN" for row in rows):
        return value.splitlines() or ["None"]
    output = []
    for state, received, sent, address, peer, *extra in rows:
        output.extend(
            [
                f"{address} ({state})",
                f"  Receive queue: {received}; Send queue: {sent}",
                f"  Peer: {peer}",
            ]
        )
        if extra:
            output.append(f"  {extra[0]}")
    return output


def _size(value):
    match = re.fullmatch(r"([0-9]+(?:[.,][0-9]+)?)([KMGTPE]?)(?:i?B?)?", value)
    if not match:
        return value
    number, unit = match.groups()
    return f"{number} {unit + 'iB' if unit else 'B'}"


def _uptime(value):
    match = re.fullmatch(
        r"\s*(\d{1,2}:\d{2}:\d{2})\s+up\s+(.+?),\s+(\d+)\s+users?,\s+load averages?:\s*(.+?)\s*",
        value,
    )
    if not match:
        return _lines("Uptime and load", value)
    clock, duration, users, load = match.groups()
    duration = re.sub(
        r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])",
        lambda part: f"{int(part[1])}h {int(part[2])}m",
        duration,
    )
    return [
        f"Server time: {clock}",
        f"Uptime: {duration}",
        f"Logged-in users: {users}",
        f"Load average (1/5/15 minutes): {' / '.join(part.strip() for part in load.split(','))}",
    ]


def _memory(value, summary):
    rows = [line.split() for line in value.splitlines()]
    memory = next((row for row in rows if row and row[0] == "Mem:"), None)
    swap = next((row for row in rows if row and row[0] == "Swap:"), None)
    if not memory or len(memory) < 7 or not swap or len(swap) < 4:
        return _lines("Memory", value)
    total, used, free, shared, cache, available = map(_size, memory[1:7])
    lines = ["Memory:", f"  Used: {used} / {total}", f"  Available: {available}"]
    if not summary:
        lines.extend([f"  Free: {free}; Shared: {shared}", f"  Cache and buffers: {cache}"])
    swap_total, swap_used, swap_free = map(_size, swap[1:4])
    if swap[1] in ("0", "0B"):
        lines.append("  Swap: Not configured")
    else:
        lines.append(f"  Swap: Used {swap_used} / {swap_total}")
        if not summary:
            lines.append(f"    Free: {swap_free}")
    return lines


def _disks(value, summary):
    lines = value.splitlines()
    if lines and lines[0].lower().startswith("filesystem"):
        lines = lines[1:]
    rows = [line.split(maxsplit=6) for line in lines]
    if not rows or any(len(row) != 7 or not row[5].endswith("%") for row in rows):
        return _lines("Root filesystem" if summary else "Disks", value)
    output = ["Root filesystem:" if summary else "Disks:"]
    for device, kind, size, used, available, percent, mount in rows:
        if not summary:
            output.append(f"  {mount}: ")
        prefix = "  " if summary else "    "
        output.append(f"{prefix}Used: {_size(used)} / {_size(size)} ({percent})")
        output.append(f"{prefix}Available: {_size(available)}")
        if not summary:
            output.append(f"{prefix}Device: {device}; Type: {kind}")
    return output


def _updates(value):
    lines = value.splitlines()
    if lines and lines[0].startswith("Listing..."):
        lines = lines[1:]
    if not lines:
        return ["Upgradable packages: None"]
    output = ["Upgradable packages:"]
    for line in lines:
        match = re.fullmatch(r"(\S+)/(\S+)\s+(\S+)\s+(\S+)\s+\[upgradable from:\s*(.+?)\]", line)
        if match:
            name, source, available, architecture, installed = match.groups()
            output.extend(
                [
                    f"  {name} ({source})",
                    f"    Current: {installed}",
                    f"    Available: {available} ({architecture})",
                ]
            )
        else:
            output.append("  " + line)
    return output


def _status_text(data, summary):
    groups = []

    def add_group(title, lines):
        if lines:
            groups.append(title + "\n" + "\n".join("  " + line for line in lines))

    system = []
    for key in ("system", "uptime", "boot_id"):
        if key in data:
            if key == "uptime":
                system.extend(_uptime(data[key]))
            else:
                system.extend(_lines("Kernel" if key == "system" else "Boot ID", data[key]))
    if system and "reboot_required" in data:
        system.extend(_lines("Reboot required", data["reboot_required"]))
    add_group("System", system)

    resources = []
    if "memory" in data:
        resources.extend(_memory(data["memory"], summary))
    if "disks" in data:
        resources.extend(_disks(data["disks"], summary))
    add_group("Resources", resources)

    services = []
    if "services" in data:
        parsed = [(name, *_service(raw)) for name, raw in data["services"].items()]
        if not parsed:
            services.append("No configured services")
        elif summary:
            active = sum(kind == "active" for _, _, kind, _ in parsed)
            services.append(f"Active: {active}/{len(parsed)}")
            for name, label, kind, attention in parsed:
                if kind != "active" or attention:
                    services.extend(_lines(name, label))
        else:
            for name, label, _, _ in parsed:
                services.extend(_lines(name, label))
    if "failed_services" in data:
        failed = data["failed_services"]
        if not failed or re.search(r"(?:^|\n)\s*0 loaded units listed\.", failed):
            failed = "None"
        services.extend(_lines("Failed system units", failed))
    add_group("Services", services)

    network = []
    if "listeners" in data:
        network.append("TCP / UDP listeners:")
        network.extend("  " + line for line in _listeners(data["listeners"]))
    for key in ("routes", "namespaces"):
        if key in data:
            network.extend(_lines(key.capitalize(), data[key]))
    add_group("Network", network)

    if "firewall" in data:
        add_group("Firewall", _lines("Rules", data["firewall"]))
    updates = []
    if "updates" in data:
        updates.extend(_updates(data["updates"]))
    if not system and "reboot_required" in data:
        updates.extend(_lines("Reboot required", data["reboot_required"]))
    add_group("Updates", updates)
    if "error_count_24h" in data:
        value = data["error_count_24h"]
        detail = f"{value} entries" if isinstance(value, int) else value
        add_group("Logs", _lines("Errors in the last 24 hours", detail))
    return "\n\n".join(groups)


def _bytes(value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return "Unknown"
    size = float(value)
    for unit in ("bytes", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"):
        if size < 1024 or unit == "EiB":
            return f"{value:,} bytes" if unit == "bytes" else f"{size:.2f} {unit} ({value:,} bytes)"
        size /= 1024
    return f"{value:,} bytes"


def _timestamp(value):
    if not value:
        return "None"
    try:
        return datetime.fromisoformat(value).isoformat(sep=" ", timespec="seconds")
    except (TypeError, ValueError):
        return str(value)


def _usage_text(data):
    lines = ["Usage (approximate observations)"]
    fresh = data.get("fresh")
    freshness = "OK" if fresh is True else "Stale or unavailable" if fresh is False else "Unknown"
    lines.append("  Data freshness: " + freshness)
    latest = data.get("latest_state")
    if isinstance(latest, (list, tuple)) and len(latest) == 2:
        state = {
            "observed": "Sampling successful",
            "startup/gap": "Startup or sampling gap",
            "gap/error": "Sampling failed",
            "gap/delayed": "Sampling delayed",
            "stopped": "Stopped",
        }.get(latest[1], latest[1])
        lines.append(f"  Latest state: {state} ({_timestamp(latest[0])})")
    else:
        lines.append("  Latest state: None")
    lines.append(f"  Last success: {_timestamp(data.get('last_success'))}")
    users = data.get("users") or []
    if not users:
        lines.append("  Users: None")
    for user in users:
        label = user.get("label", user.get("user", "Unknown user"))
        lines.append("\n  " + label + (" (revoked)" if user.get("active") is False else ""))
        lines.append(f"    Upload: {_bytes(user.get('upload_bytes'))}")
        lines.append(f"    Download: {_bytes(user.get('download_bytes'))}")
        active = user.get("active_connections")
        lines.append(f"    Active connections: {active if active is not None else 'Unknown'}")
        observed = user.get("ever_observed")
        lines.append(
            f"    Ever observed: {'yes' if observed is True else 'no' if observed is False else 'Unknown'}"
        )
    return "\n".join(lines)


def _log_fields(value, indent=2):
    prefix = " " * indent
    lines = []
    items = value.items() if isinstance(value, dict) else (("-", item) for item in value)
    labels = {"level": "Level", "msg": "Message", "logger": "Source", "ts": "Time"}
    for name, item in items:
        name = str(name)
        label = labels.get(name, name) if name != "-" else "-"
        if isinstance(item, (dict, list)) and item:
            lines.append(f"{prefix}{label}:" if label != "-" else f"{prefix}-")
            lines.extend(_log_fields(item, indent + 2))
        else:
            value_text = "None" if item is None or item == {} or item == [] else str(item)
            values = value_text.splitlines() or [""]
            lines.append(
                f"{prefix}{label}: {values[0]}" if label != "-" else f"{prefix}- {values[0]}"
            )
            lines.extend(" " * (indent + 2) + line for line in values[1:])
    return lines


def format_log(line):
    """Render JSON application messages without changing ordinary journal lines."""
    if line.lstrip().startswith(("{", "[")):
        prefix, message = "", line
    else:
        prefix, separator, message = line.partition(": ")
        if not separator:
            return line
    message = message.strip()
    if not message.startswith(("{", "[")):
        return line
    try:
        data = json.loads(message)
    except (TypeError, ValueError):
        return line
    if not isinstance(data, (dict, list)):
        return line
    heading = prefix + ":" if prefix else "Logs"
    indent = len(prefix) - len(prefix.lstrip()) + 2
    fields = _log_fields(data, indent)
    return "\n".join([heading, *(fields or [" " * indent + "None"])]) + "\n"


def render(data, *, view="checks", summary=False):
    if view == "status":
        return _status_text(data, summary)
    if view == "usage":
        return _usage_text(data)
    if view == "subscriptions":
        return "Device subscription URLs\n" + "\n".join(
            f"  {entry['name']} ({identifier}): {entry['url']}"
            for identifier, entry in data.items()
        )
    if view == "devices":
        return "Devices\n" + "\n".join(
            f"  {entry['name']} | {entry['id']} | {entry['platform']} | {'active' if entry['active'] else 'revoked'}"
            for entry in data
        )
    if view == "device-sync":
        return f"Saved device configuration applied; {data['active']} active devices."
    if view == "device":
        text = f"{data['name']} | {data['id']} | {data['platform']} | {'active' if data['active'] else 'revoked'}"
        if "url" in data:
            text += "\nSubscription: " + data["url"]
        elif data["active"]:
            text += "\nRun device show " + data["id"] + " to reveal this device's subscription."
        return text
    if view == "checks":
        return "\n".join(
            "\n".join(_lines(f"[{item['state']}] {item['name']}", item["detail"])) for item in data
        )
    if view == "plan":
        parts = [
            "Deployment plan for " + data["name"] + " (" + data["target"] + ")",
            "Access: "
            + {
                "tailscale": "Tailscale",
                "mihomo": "Clash (Mihomo)",
                "both": "Tailscale and Clash (Mihomo)",
            }[data["mode"]],
            "TCP fingerprints: " + ("enabled" if data["fingerprint"] else "disabled"),
            "System: security upgrades, time synchronization, SSH key verification and firewall",
        ]
        if data["mihomo"]:
            parts.append(
                "Clash full TCP path (RTT): "
                + ("enabled via WireGuard" if data["rtt"] else "disabled")
            )
        if data["wireguard"]:
            parts.append(
                "Clash: WireGuard device nodes selected by default; VLESS, Hysteria2 and AnyTLS also available"
            )
            parts.append(
                "VLESS, Hysteria2 and AnyTLS keep separate TCP connections; select WireGuard for the full device-to-destination TCP latency path."
            )
        elif data["mihomo"]:
            parts.append(
                "Clash: VLESS, Hysteria2 and AnyTLS; HTTPS subscription and automatic certificate renewal"
            )
        if data["tailscale"]:
            parts.append(
                "Tailscale: use the sign-in link, approve the exit node, then select it on devices"
            )
            parts.append(
                "Tailscale uses native packet forwarding and includes device-to-server latency"
            )
        parts.append("Public ports: " + ", ".join(data["ports"]) + "; existing SSH port preserved")
        return "\n".join(parts)
    if view == "deployment":
        parts = [render(data["checks"])]
        authorization = data["tailscale"]
        if authorization:
            if authorization["state"] in ("login", "approval"):
                parts.append(
                    "After authorization and exit-node approval, run check tailscale in this session; deployment does not need to be repeated."
                )
        if all(item["state"] != "fail" for item in data["checks"]):
            if data["readiness"] == "pending":
                parts.append(
                    "Node configured; Tailscale "
                    + (
                        "is still starting"
                        if authorization["state"] == "starting"
                        else "authorization is pending"
                    )
                    + ". The SSH management session remains open."
                )
            else:
                parts.append("Deployment ready. The SSH management session remains open.")
            if data.get("subscription", True):
                parts.append(
                    (
                        "Clash and WireGuard are ready."
                        if data.get("wireguard")
                        else "Clash is ready."
                    )
                    + " Run device list, then device show DEVICE to import that device's private URL into its Clash client."
                )
            if data.get("wireguard"):
                parts.append(
                    "The default WireGuard nodes preserve device-to-server latency. Switch Windows / Apple in Nodes if needed."
                )
            parts.append("Use status and check for service and connection results.")
        return "\n".join(parts)
    if view == "member":
        text = f"Member materials created in {data['output']} (pending registration).\nRegister server-user.pending.json on the server before publishing the subscription."
    elif view == "profile":
        text = f"{data['kind'].capitalize()} created: {data['output']}"
    elif view == "subscription":
        return f"Subscriptions processed: {data['processed']}; updated: {data['updated']}"
    elif view == "certificate":
        return f"[pass] Certificate: {data['hostname']}\n  Valid from: {data['not_before']}\n  Valid until: {data['not_after']}\nRun check subscription to verify the HTTPS service."
    elif view == "listener":
        return f"[pass] {data['service']}: TCP {data['port']} is listening"
    elif view == "controller":
        return f"[pass] Private controller directory: {data['directory']}"
    elif view == "init":
        text = f"Private node configuration saved: {data['output']}"
        if "plan" in data:
            text += "\n" + render(data["plan"], view="plan")
        text += f'\nDeploy with: vps-ops deploy apply "{data["output"]}"'
    else:
        raise ValueError("Unknown output view")
    if os.name == "nt":
        text += "\nCheck the output path's Windows ACL to restrict access to your account."
    return text


def emit(data, machine=False, *, view="checks", summary=False):
    print(
        json.dumps(data, ensure_ascii=False)
        if machine
        else render(data, view=view, summary=summary)
    )


def emit_log(record, *, machine=False):
    if machine:
        print(json.dumps(record, ensure_ascii=False), flush=True)
    else:
        print(format_log(record), end="", flush=True)


def write_line(line):
    print(line.rstrip("\r\n"), flush=True)


def notice(event):
    messages = {
        "preparing": "Preparing the private deployment bundle; SSH authentication follows.",
        "rebooting": "Rebooting; the SSH connection will close. Deployment resumes after SSH returns.",
        "ssh_closed": "The SSH management session has ended; reconnect to review node status.",
    }
    print(messages[event], flush=True)


def error(exc):
    if isinstance(exc, (RuntimeError, ValueError)):
        detail = str(exc)
    elif isinstance(exc, KeyError):
        detail = "Required configuration field is missing: " + str(exc.args[0])
    elif isinstance(exc, OSError):
        detail = exc.strerror or str(exc)
        if exc.filename:
            detail += ": " + str(exc.filename)
    else:
        detail = type(exc).__name__ + ": operation failed"
    print("[fail] " + detail, file=sys.stderr)
