"""Native OpenSSH connection policy shared by deployment and daily operations."""

import socket
import subprocess
import time


def ssh_command(target, port=None, user=None, identity=None, tty=False, key_only=False):
    if not target or target.startswith("-"):
        raise ValueError("Invalid SSH target")
    result = [
        "ssh",
        "-tt" if tty else "-T",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=6",
    ]
    for flag, value in (("-p", port), ("-l", user), ("-i", identity)):
        if value is not None and value != "":
            result += [flag, str(value)]
    if key_only and identity:
        result += ["-o", "IdentitiesOnly=yes"]
    if key_only:
        result += ["-o", "PreferredAuthentications=publickey", "-o", "PasswordAuthentication=no"]
    return result + [target]


def wait_ssh(command, seconds):
    result = subprocess.run(
        [command[0], "-G", *command[1:]], capture_output=True, text=True, check=True, timeout=15
    )
    opts = dict(line.split(" ", 1) for line in result.stdout.splitlines())
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(
                (opts["hostname"], int(opts["port"])), timeout=2
            ) as connection:
                connection.settimeout(2)
                if b"SSH-" in connection.recv(255):
                    return
        except OSError:
            pass
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    raise RuntimeError("Timed out waiting for SSH")
