"""Tailscale exit-node configuration and authorization state."""

import json
import subprocess


def status():
    response = subprocess.run(
        ["tailscale", "status", "--json"], capture_output=True, text=True, timeout=20
    )
    try:
        current = json.loads(response.stdout)
    except ValueError:
        raise RuntimeError("Tailscale state is unavailable; check tailscaled logs") from None
    if not isinstance(current, dict):
        raise RuntimeError("Tailscale returned an invalid state")
    backend = current.get("BackendState")
    if backend == "Running":
        ready = current.get("Self", {}).get("ExitNodeOption", False)
        state = "ready" if ready else "approval"
        detail = (
            "Online; exit-node capability approved"
            if ready
            else "Online; approve the exit node in the Tailscale admin console"
        )
    elif backend == "NeedsLogin":
        state, detail = "login", "Sign-in required; Tailscale is not ready"
    elif backend == "NeedsMachineAuth":
        state, detail = "approval", "Device authorization required in the Tailscale admin console"
    elif backend == "Starting":
        state, detail = "starting", "Tailscale is starting; run check tailscale again shortly"
    elif backend in ("Stopped", "NoState"):
        state, detail = "stopped", "Tailscale is stopped"
    else:
        raise RuntimeError("Tailscale is not running: " + str(backend or "unknown state"))
    return {
        "state": state,
        "backend": backend,
        "detail": detail,
        "auth_url": current.get("AuthURL") or None,
    }


def configure(name):
    current = status()
    arguments = [
        "tailscale",
        "set" if current["backend"] == "Running" else "up",
        "--advertise-exit-node",
        "--hostname=" + name,
    ]
    if arguments[1] == "up":
        arguments.append("--timeout=5s")
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=20)
    current = status()
    if current["state"] == "stopped" or (
        result.returncode
        and (arguments[1] != "up" or current["state"] not in ("login", "approval", "starting"))
    ):
        raise RuntimeError("Tailscale configuration failed; check tailscaled logs")
    return current
