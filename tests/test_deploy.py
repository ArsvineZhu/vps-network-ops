import json

import pytest
import yaml

from vps_ops.checks import checks
from vps_ops.deploy.config import load, services
from vps_ops.deploy.render import save


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
        services("none")
    assert "tailscaled" not in services("mihomo")
    assert "mihomo" in services("both")


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
    record = f"caddy request /s/auto/{token}.yaml password=sample-credential status=200\n"
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
