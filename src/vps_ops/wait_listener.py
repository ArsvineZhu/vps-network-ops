#!/usr/bin/env python3
"""Linux: wait for a TCP listener owned by current systemd MainPID. No connections."""

import re
import subprocess
import time


def wait(service, port, seconds=10):
    if (
        not re.fullmatch(r"[A-Za-z0-9_.@-]+", service)
        or not 1 <= port <= 65535
        or not 0 < seconds <= 120
    ):
        raise ValueError("Invalid service, port or timeout")
    end = time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            pid = subprocess.check_output(
                ["systemctl", "show", service, "-p", "MainPID", "--value"], text=True, timeout=3
            ).strip()
            sockets = subprocess.check_output(
                ["ss", "-H", "-lntp", f"( sport = :{port} )"], text=True, timeout=3
            )
            if (
                pid.isdigit()
                and int(pid) > 0
                and re.search(r"pid=" + re.escape(pid) + r",", sockets)
            ):
                return {"service": service, "port": port}
            time.sleep(0.2)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Cannot read service or listener state") from exc
    raise RuntimeError("Timed out waiting for the service listener")
