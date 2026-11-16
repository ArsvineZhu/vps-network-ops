import json

import pytest
import yaml

from vps_ops.capabilities import Capabilities
from vps_ops.checks import checks
from vps_ops.deploy.config import load
from vps_ops.files import save


def test_tailscale_needs_no_domain_or_dns_credentials(tmp_path):
    key = tmp_path / "key.pub"
    key.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKtest public")
    config = tmp_path / "node.yaml"
    config.write_text(
        yaml.safe_dump(dict(mode="tailscale", target="root@host", port=22, public_key=str(key)))
    )
    c = load(config)
    assert c["services"] == ["tailscaled"]
    assert "dns_names" not in c
    assert checks(c, "proxy")[0]["state"] == "skip"


def test_deployment_mode_must_enable_a_capability():
    with pytest.raises(ValueError):
        Capabilities.from_config({"mode": "none"})
    assert "tailscaled" not in Capabilities.from_config({"mode": "mihomo"}).services
    assert "mihomo" in Capabilities.from_config({"mode": "both"}).services


def test_identity_write_is_atomic_and_repeatable(tmp_path):
    target = tmp_path / "identity.json"
    save(target, {"secret": "first"})
    before = target.stat().st_mtime_ns
    save(target, {"secret": "first"})
    assert target.stat().st_mtime_ns == before
    assert json.loads(target.read_text()) == {"secret": "first"}
    assert list(tmp_path.iterdir()) == [target]


def test_binary_install_can_be_repeated_without_decoding(tmp_path):
    from vps_ops.deploy.components import install

    source = tmp_path / "source"
    target = tmp_path / "program"
    source.write_bytes(bytes(range(256)))
    install(source, target, 0o755)
    install(source, target, 0o755)
    assert source.read_bytes() == target.read_bytes()
    source.write_bytes(b"new-binary")
    install(source, target, 0o755)
    assert target.read_bytes() == b"new-binary"


def test_mihomo_mode_does_not_require_tailscale(monkeypatch):
    from vps_ops import checks as module

    monkeypatch.setattr(module, "run", lambda args: "active")
    monkeypatch.setattr(
        module, "_checks", lambda c, section: [{"name": section, "state": "pass", "detail": "ok"}]
    )
    result = module.checks({"mode": "mihomo", "services": ["mihomo"]}, "all")
    assert next(x for x in result if x["name"] == "tailscale")["state"] == "skip"


def test_wait_requires_an_ssh_banner_not_only_an_open_port(monkeypatch):
    import socket
    import subprocess
    import threading

    from vps_ops.transport import wait_ssh

    responses = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        listener.settimeout(6)
        port = listener.getsockname()[1]

        def serve():
            for banner in (b"HTTP/1.1 not SSH\r\n", b"SSH-2.0-lab\r\n"):
                connection, _ = listener.accept()
                with connection:
                    responses.append(banner)
                    connection.sendall(banner)

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(
                [], 0, stdout=f"hostname 127.0.0.1\nport {port}\n"
            ),
        )
        wait_ssh(["ssh", "lab"], 5)
        worker.join(timeout=1)
        assert len(responses) == 2
        assert not worker.is_alive()


def test_diagnostics_redact_subscription_paths_and_known_credentials(monkeypatch, tmp_path, capsys):
    import io
    import subprocess
    from types import SimpleNamespace

    from vps_ops.runtime import journal

    config = tmp_path / "frontend.yaml"
    config.write_text("password: sample-credential\n")
    token = "x" * 43
    record = f"caddy request /s/{token}.yaml password=sample-credential status=200\n"
    process = SimpleNamespace(stdout=io.StringIO(record), wait=lambda: 0, poll=lambda: 0)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: process)
    lines = []
    for record in journal(["journalctl"], {"frontend_config": str(config)}):
        assert isinstance(record, str)
        lines.append(record)
    output = "".join(lines)
    assert capsys.readouterr().out == ""
    assert token not in output
    assert "sample-credential" not in output
    assert "status=200" in output


def test_windows_build_transfers_linux_shell_scripts(tmp_path):
    import shutil
    import tarfile
    import zipfile

    from vps_ops.deploy.client import bundle

    payload = bundle({"plan": {"mihomo": False}}, lambda _: "unused", tmp_path / "install.tar.gz")
    with tarfile.open(payload) as archive:
        for name in ("bootstrap.sh", "base.yaml", "apply.yaml", "preflight.py"):
            script = archive.extractfile(name)
            assert script is not None
            assert b"\r" not in script.read(), name
        wheel = next(member for member in archive.getmembers() if member.name.endswith(".whl"))
        package = archive.extractfile(wheel)
        assert package is not None
        target = tmp_path / wheel.name
        with target.open("wb") as output:
            shutil.copyfileobj(package, output)
    with zipfile.ZipFile(target) as archive:
        resources = [name for name in archive.namelist() if name.startswith("vps_ops/")]
        assert resources
        for name in resources:
            assert b"\r" not in archive.read(name), name


def test_configure_wizard_preserves_private_settings_and_rejects_invalid_replacement(
    tmp_path, monkeypatch, capsys
):
    from vps_ops.cli import execute
    from vps_ops.deploy import client

    public = tmp_path / "management.pub"
    public.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKtest management")
    path = tmp_path / "node.yaml"
    previous = {
        "mode": "mihomo",
        "features": {"fingerprint": True, "rtt": True},
        "target": "root@host",
        "public_key": str(public),
        "identity": "private-key-reference",
        "domain": "node.example.com",
        "public_ipv4": "192.0.2.5",
        "email": "a@example.com",
        "dns_provider": "cloudflare",
        "credential_file": "private-dns.json",
        "custom": {"keep": "private-node-setting"},
        "device": {"name": "Primary", "platform": "Windows"},
    }
    path.write_text(yaml.safe_dump(previous))
    answers = iter(("", "no", "no", ""))
    labels = []

    def answer(label):
        labels.append(label)
        return next(answers)

    monkeypatch.setattr("builtins.input", answer)
    assert execute(["deploy", "configure", str(path)]) == 0
    expected = previous | {"features": {"fingerprint": False, "rtt": False}}
    assert yaml.safe_load(path.read_text()) == expected
    assert len(labels) == 4
    output = capsys.readouterr().out
    assert "Clash (Mihomo)" in output and "private-dns.json" not in output
    content = path.read_bytes()
    with pytest.raises(ValueError, match="SSH port"):
        client.init(path, expected | {"port": 70000}, replace=True)
    assert path.read_bytes() == content


def test_fresh_wizard_defaults_to_clash_fingerprint_and_wireguard(tmp_path, monkeypatch):
    from vps_ops.cli import execute

    public = tmp_path / "management.pub"
    public.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKtest management")
    answers = iter(
        (
            "",
            "",
            "",
            "",
            "root@host",
            "",
            str(public),
            "",
            "node.example.com",
            "192.0.2.5",
            "a@example.com",
            "",
            "",
            "",
            "",
        )
    )
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    path = tmp_path / "node.yaml"
    assert execute(["deploy", "init", str(path)]) == 0
    selected = load(path)
    assert selected["mode"] == "mihomo"
    assert selected["features"] == {"fingerprint": True, "rtt": True}
    assert selected["device"]["platform"] == "Default"
    assert "wg-quick@vps-ops" in selected["services"]
    assert "tailscaled" not in selected["services"]


@pytest.mark.parametrize("mode", ("tailscale", "both"))
def test_saved_wizard_keeps_explicit_tailscale_choices(mode, monkeypatch):
    from vps_ops.prompts import deployment

    saved = {
        "mode": mode,
        "features": {"fingerprint": False, "rtt": False},
        "target": "saved-host",
        "public_key": "saved.pub",
        "identity": "saved-key",
        "domain": "node.example.com",
        "public_ipv4": "192.0.2.5",
        "email": "a@example.com",
        "dns_provider": "dnspod",
        "credential_file": "private.json",
        "device": {"name": "Primary", "platform": "Windows"},
    }
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert deployment(saved) == saved
