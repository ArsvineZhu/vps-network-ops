"""Register, inspect and revoke physical devices in the running node."""

import http.client
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path

import yaml

from . import identity
from .capabilities import Capabilities
from .files import save
from .mihomo import connection_rows
from .runtime import run
from .transport import UnixHTTP


@contextmanager
def node_lock():
    import fcntl

    path = Path("/var/lib/vps-ops/deploy.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(
                "A deployment or device change is running; retry after it finishes"
            ) from None
        yield


def controller(method, path, value=None):
    connection = UnixHTTP("/var/lib/mihomo/controller/control.sock")
    try:
        body = None if value is None else json.dumps(value)
        connection.request(method, path, body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(8 * 1024 * 1024 + 1)
        if response.status not in (200, 204) or len(raw) > 8 * 1024 * 1024:
            raise RuntimeError(
                "Mihomo controller operation failed (HTTP " + str(response.status) + ")"
            )
        return json.loads(raw) if raw else None
    finally:
        connection.close()


def reconcile(config, state, revoked_users=()):
    from .deploy.render import render
    from .deploy.server import asset_directory

    caddy = Path("/etc/caddy/Caddyfile")
    previous_caddy = caddy.read_text(encoding="utf-8") if caddy.exists() else None
    render(config, asset_directory(), state)
    caddy_changed = previous_caddy != caddy.read_text(encoding="utf-8")
    subprocess.run(
        ["/usr/local/bin/mihomo", "-t", "-d", "/var/lib/mihomo", "-f", "/etc/mihomo/config.yaml"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if caddy_changed:
        subprocess.run(
            ["caddy", "validate", "--config", str(caddy)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    controller(
        "PUT",
        "/configs?force=true",
        {"payload": Path("/etc/mihomo/config.yaml").read_text(encoding="utf-8")},
    )
    if revoked_users:
        current = controller("GET", "/connections")
        for connection in connection_rows(current):
            if connection.get("metadata", {}).get("inboundUser") in revoked_users:
                controller("DELETE", "/connections/" + connection["id"])
    if Capabilities.from_config(config).wireguard:
        from .forwarding import refresh_peers

        stripped = run(["wg-quick", "strip", "/etc/wireguard/vps-ops.conf"])
        run(["wg", "syncconf", "vps-ops", "/dev/stdin"], input=stripped + "\n")
        from .wireguard import NETWORK

        run(["ip", "route", "replace", NETWORK, "dev", "vps-ops"])
        refresh_peers(config, state)
    if caddy_changed:
        run(["systemctl", "kill", "--kill-whom=main", "--signal=USR1", "caddy"])


def node_config():
    config = json.loads(Path("/etc/vps-ops/deployment.json").read_text(encoding="utf-8"))
    if not Capabilities.from_config(config).mihomo:
        raise ValueError("Device subscriptions require Clash; enable it with deploy configure")
    return config


def list_devices():
    return [identity.public(device) for device in identity.load()["devices"].values()]


def show(identifier):
    device = identity.find(identity.load(), identifier)
    result = identity.public(device)
    if device["active"]:
        index = json.loads(Path("/etc/vps-ops/subscriptions.json").read_text(encoding="utf-8"))
        result["url"] = index[device["id"]]["url"]
    return result


def add(name, platform):
    with node_lock():
        config = node_config()
        state = identity.load()
        device = identity.add(state, name, platform)
        save(identity.IDENTITY, state)
        try:
            reconcile(config, state)
        except (
            OSError,
            RuntimeError,
            ValueError,
            subprocess.SubprocessError,
            http.client.HTTPException,
            yaml.YAMLError,
        ) as exc:
            detail = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__
            raise RuntimeError(
                "Device "
                + device["id"]
                + " was saved; live configuration failed ("
                + detail
                + "). Fix the error and run device sync"
            ) from exc
        return identity.public(device)


def revoke(identifier):
    from .exit_profiles import PROFILES

    with node_lock():
        config = node_config()
        state = identity.load()
        device = identity.revoke(state, identifier)
        save(identity.IDENTITY, state)
        users = {device["id"] + "." + profile.key for profile in PROFILES}
        try:
            reconcile(config, state, users)
        except (
            OSError,
            RuntimeError,
            ValueError,
            subprocess.SubprocessError,
            http.client.HTTPException,
            yaml.YAMLError,
        ) as exc:
            detail = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__
            raise RuntimeError(
                "Revocation of "
                + device["id"]
                + " was saved; live configuration failed ("
                + detail
                + "). Fix the error and run device sync"
            ) from exc
        return identity.public(device)


def sync():
    from .exit_profiles import PROFILES

    with node_lock():
        config = node_config()
        state = identity.load()
        revoked = {
            device["id"] + "." + profile.key
            for device in state["devices"].values()
            if not device["active"]
            for profile in PROFILES
        }
        reconcile(config, state, revoked)
        return {"active": sum(device["active"] for device in state["devices"].values())}
