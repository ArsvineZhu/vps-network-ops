#!/usr/bin/env python3
"""Linux: wait for a TCP listener owned by current systemd MainPID. No connections."""

import argparse
import re
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("service")
p.add_argument("port", type=int)
p.add_argument("--seconds", type=float, default=10)
a = p.parse_args()
if (
    not re.fullmatch(r"[A-Za-z0-9_.@-]+", a.service)
    or not 1 <= a.port <= 65535
    or not 0 < a.seconds <= 120
):
    p.error("invalid arguments")
end = time.monotonic() + a.seconds
try:
    while time.monotonic() < end:
        pid = subprocess.check_output(
            ["systemctl", "show", a.service, "-p", "MainPID", "--value"], text=True, timeout=3
        ).strip()
        sockets = subprocess.check_output(
            ["ss", "-H", "-lntp", f"( sport = :{a.port} )"], text=True, timeout=3
        )
        if pid.isdigit() and int(pid) > 0 and re.search(r"pid=" + re.escape(pid) + r",", sockets):
            print("READY: listener belongs to current service process")
            raise SystemExit(0)
        time.sleep(0.2)
except (OSError, subprocess.SubprocessError):
    p.exit(2, "Unable to inspect service or sockets; readiness unknown.\n")
p.exit(1, "Listener did not become ready before the deadline.\n")
