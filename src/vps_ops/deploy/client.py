"""Native OpenSSH deployment with one streamed install session."""

import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import cast

import yaml

from vps_ops.capabilities import Capabilities

from .config import load


def settings(path):
    destination = Path(path)
    if not destination.exists():
        return None
    value = yaml.safe_load(destination.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Deployment configuration must be a YAML object")
    Capabilities.from_config(value)
    return value


def init(path, values, *, replace=False):
    from vps_ops.files import save

    from .config import preview

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(values, allow_unicode=True)
    with tempfile.TemporaryDirectory(prefix=".vps-ops-", dir=destination.parent) as folder:
        candidate = Path(folder) / "node.yaml"
        save(candidate, content)
        selected = load(candidate)
    if replace:
        save(destination, content)
    else:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    return {"output": str(destination), "plan": preview(selected)}


def ssh(c, key_only=False):
    from vps_ops.transport import ssh_command

    return ssh_command(c["target"], port=c["port"], identity=c.get("identity"), key_only=key_only)


def bundle(c, prompt_secret, payload):
    root = Path(__file__).parent
    temporary = None
    checkout = root.resolve().parents[2]
    if (checkout / "pyproject.toml").exists():
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(checkout / "build/deploy")],
            cwd=checkout,
            check=True,
            capture_output=True,
        )
        wheel = next((checkout / "build/deploy").glob("*.whl"))
    else:
        import zipfile
        from importlib.metadata import distribution

        package = distribution("vps-network-ops")
        temporary = tempfile.TemporaryDirectory(prefix="vps-ops-wheel-")
        wheel = Path(temporary.name) / ("vps_network_ops-" + package.version + "-py3-none-any.whl")
        with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as output:
            for item in package.files or []:
                if ".." in item.parts or "__pycache__" in item.parts:
                    continue
                if item.parts[0] == "vps_ops" or item.parts[0].endswith(".dist-info"):
                    output.write(str(package.locate_file(item)), str(item).replace("\\", "/"))
    try:
        credentials = {}
        if c["plan"]["mihomo"]:
            if c.get("credential_file"):
                credentials = json.loads(Path(c["credential_file"]).read_text(encoding="utf-8-sig"))
                if not isinstance(credentials, dict) or any(
                    not isinstance(name, str) or not isinstance(value, str)
                    for name, value in credentials.items()
                ):
                    raise ValueError("DNS credential_file must be a JSON object of text fields")
            for name in c["dns_names"]:
                if name not in credentials:
                    if not sys.stdin.isatty():
                        raise ValueError(
                            "Non-interactive deployment requires a DNS credential_file"
                        )
                    credentials[name] = prompt_secret(name)
                if not isinstance(credentials[name], str) or not credentials[name]:
                    raise ValueError("DNS credential is empty")
        with tarfile.open(payload, mode="w:gz") as archive:
            archive.add(wheel, arcname=wheel.name)
            for name in ("bootstrap.sh", "base.yaml", "apply.yaml", "preflight.py"):
                data = (root / name).read_text(encoding="utf-8-sig").encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o700 if name.endswith(".sh") else 0o600
                archive.addfile(info, io.BytesIO(data))
            for name, value in (("node.json", c), ("dns.json", credentials)):
                data = json.dumps(value).encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(data))
        return payload
    finally:
        if temporary is not None:
            temporary.cleanup()


def apply(path, *, prompt_secret, notify, stream):
    c = load(path)
    notify("preparing")
    with tempfile.TemporaryDirectory(prefix="vps-ops-deploy-") as folder:
        data = bundle(c, prompt_secret, Path(folder) / "deployment.tar.gz")
        _apply(c, data, notify, stream)


def _apply(c, data, notify, stream):
    key_verified = False
    for _attempt in range(3):
        command = (
            "umask 077; mkdir -p /var/lib/vps-ops/deploy; "
            "exec 9>/var/lib/vps-ops/deploy.lock; "
            "flock -n 9 || { echo 'Another deployment is running'; exit 1; }; "
            "echo VPS_OPS_TRANSFER_READY; head -c "
            + str(data.stat().st_size)
            + " | tar -xz -C /var/lib/vps-ops/deploy "
            "&& exec bash /var/lib/vps-ops/deploy/bootstrap.sh"
        )
        completed = False
        process = subprocess.Popen(
            ssh(c, key_only=key_verified) + [command], stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        try:
            assert process.stdin is not None and process.stdout is not None
            while True:
                greeting = process.stdout.readline()
                if not greeting:
                    raise RuntimeError(
                        "SSH login or deployment lock check failed (exit code "
                        + str(process.wait())
                        + ")"
                    )
                line = greeting.decode(errors="replace").rstrip()
                if line == "VPS_OPS_TRANSFER_READY":
                    break
                stream(line)
            with data.open("rb") as payload:
                while chunk := payload.read(1024 * 1024):
                    process.stdin.write(chunk)
            process.stdin.flush()
            for raw in process.stdout:
                line = raw.decode(errors="replace").rstrip()
                if line == "VPS_OPS_KEY_READY":
                    if not key_verified:
                        checked = subprocess.run(
                            ssh(c, True) + ["id -u"], capture_output=True, text=True
                        )
                        if checked.returncode or checked.stdout.strip() != "0":
                            raise RuntimeError(
                                "Public-key root login verification failed; password authentication was preserved"
                            )
                        key_verified = True
                    process.stdin.write(b"KEY_VERIFIED\n")
                    process.stdin.flush()
                elif line == "VPS_OPS_READY":
                    completed = True
                    import threading

                    def forward(pipe=process.stdin):
                        try:
                            for value in sys.stdin:
                                pipe.write(value.encode())
                                pipe.flush()
                        except (BrokenPipeError, OSError, ValueError):
                            pass
                        finally:
                            pipe.close()

                    threading.Thread(target=forward, daemon=True).start()
                    while chunk := cast(io.BufferedReader, process.stdout).read1(4096):
                        sys.stdout.buffer.write(chunk)
                        sys.stdout.buffer.flush()
                    break
                else:
                    stream(line)
            code = process.wait()
        finally:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            if process.poll() is None:
                process.terminate()
                process.wait()
        if completed:
            if code:
                notify("ssh_closed")
            return
        if code != 42:
            if code:
                raise RuntimeError(
                    "Deployment failed; fix the reported issue and apply the same configuration again"
                )
            raise RuntimeError("Deployment ended before completion was reported")
        notify("rebooting")
        time.sleep(10)
        from vps_ops.transport import wait_ssh

        wait_ssh(ssh(c, key_only=key_verified), 300)
    raise RuntimeError("Node repeatedly requests a reboot; check system updates")


def subscriptions():
    return json.loads(Path("/etc/vps-ops/subscriptions.json").read_text())
