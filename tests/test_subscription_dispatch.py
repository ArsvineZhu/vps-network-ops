"""Exercise per-device subscriptions through generated files and real Caddy."""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest
import yaml

from vps_ops import identity
from vps_ops.deploy import render
from vps_ops.probes import subscription


@pytest.fixture(params=[(True, False), (False, False), (True, True), (False, True)])
def node(tmp_path, monkeypatch, request):
    def path(value):
        if Path(value).is_relative_to(tmp_path):
            return Path(value)
        return tmp_path / str(value).lstrip("/")

    from vps_ops.files import save

    monkeypatch.setattr(
        render,
        "save",
        lambda name, value, mode=0o600, **kwargs: save(path(name), value, mode, **kwargs),
    )
    monkeypatch.setattr(render, "Path", path)
    monkeypatch.setattr(identity, "IDENTITY", path("/etc/vps-ops/identity.json"))
    monkeypatch.setattr(os, "chown", lambda *args: None, raising=False)
    monkeypatch.setattr(os, "fchown", lambda *args: None, raising=False)
    monkeypatch.setitem(
        sys.modules, "grp", SimpleNamespace(getgrnam=lambda _: SimpleNamespace(gr_gid=0))
    )
    monkeypatch.setitem(
        sys.modules, "pwd", SimpleNamespace(getpwnam=lambda _: SimpleNamespace(pw_uid=0))
    )
    fingerprint, rtt = request.param
    config = dict(
        public_ipv4="192.0.2.5",
        domain="example.invalid",
        port=23899,
        name="test",
        mode="mihomo",
        features={"fingerprint": fingerprint, "rtt": rtt},
        device={"name": "Primary", "platform": "Apple"},
    )
    render.render(config, Path(__file__).parents[1] / "system")
    state = identity.load()
    identity.add(state, "Second", "Windows")
    save(identity.IDENTITY, state)
    render.render(config, Path(__file__).parents[1] / "system")
    render.render(config, Path(__file__).parents[1] / "system")
    assert identity.load() == state
    assert path("/etc/tcpfp/windows.json").exists() == fingerprint
    assert path("/etc/systemd/system/mihomo.service.d/45-fingerprint.conf").exists() == fingerprint
    assert "tcpfp-" not in path("/etc/systemd/system/mihomo.service.d/50-tls.conf").read_text()
    collector = json.loads(path("/etc/mihomo-observed/collector.json").read_text())
    assert len(collector["users"]) == 4
    return path, state, config


def test_device_variants_keep_their_own_credentials_and_correct_defaults(node, monkeypatch):
    path, state, deployment = node
    root = path("/srv/vps-subscriptions")
    config = dict(
        mode=deployment["mode"],
        features=deployment["features"],
        subscription_host="example.invalid",
        subscription_port=9443,
        frontend_config=str(path("/etc/mihomo/config.yaml")),
    )
    monkeypatch.setattr("vps_ops.probes.Path", path)
    credentials = []
    for device in state["devices"].values():
        variants = []
        for target, expected in identity.subscription_files(root, device["token"]).items():
            response = expected.read_text()
            monkeypatch.setattr(
                "vps_ops.probes.curl", lambda *args, response=response, **kwargs: response
            )
            assert "identities match" in subscription(
                config, device["id"], "https://example.invalid", expected, target=target
            )
            profile = yaml.safe_load(response)
            assert len(profile["proxies"]) == (8 if deployment["features"]["rtt"] else 6)
            variants.append(profile["proxies"])
            wrong = yaml.safe_load(response)
            next(n for n in wrong["proxies"] if n["type"] == "vless")["uuid"] = "wrong-identity"
            monkeypatch.setattr(
                "vps_ops.probes.curl", lambda *args, wrong=wrong, **kwargs: yaml.safe_dump(wrong)
            )
            with pytest.raises(RuntimeError, match="does not match"):
                subscription(
                    config, device["id"], "https://example.invalid", expected, target=target
                )
            expected.write_text(yaml.safe_dump(wrong))
            with pytest.raises(RuntimeError, match="credentials"):
                subscription(
                    config, device["id"], "https://example.invalid", expected, target=target
                )
            expected.write_text(response)
        assert variants[0] == variants[1] == variants[2]
        credentials.append({p["uuid"] for p in device["profiles"].values()})
    assert credentials[0].isdisjoint(credentials[1])


def test_caddy_delivers_private_device_variants_and_revoked_url_is_removed(
    node, tmp_path, monkeypatch
):
    caddy = os.environ.get("CADDY") or shutil.which("caddy")
    if not caddy:
        pytest.skip("Caddy is required")
    path, state, deployment = node
    monkeypatch.setattr("vps_ops.probes.Path", path)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    source = (
        path("/etc/caddy/Caddyfile")
        .read_text()
        .replace("https://example.invalid:9443", f"http://127.0.0.1:{port}")
    )
    source = "\n".join(line for line in source.splitlines() if not line.strip().startswith("tls "))
    source = source.replace(
        "/srv/vps-subscriptions", '"' + path("/srv/vps-subscriptions").as_posix() + '"'
    )
    config = tmp_path / "Caddyfile"
    config.write_text(source)
    with (tmp_path / "caddy.log").open("w") as log:
        process = subprocess.Popen(
            [caddy, "run", "--config", str(config), "--adapter", "caddyfile"],
            stdout=log,
            stderr=log,
        )
        try:
            end = time.monotonic() + 10
            while True:
                assert process.poll() is None, (tmp_path / "caddy.log").read_text()
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    assert time.monotonic() < end, "Caddy startup timed out"
                    time.sleep(0.05)
            opener = build_opener(ProxyHandler({}))
            for device in state["devices"].values():
                base = f"http://127.0.0.1:{port}/s/" + device["token"]
                for agent, target in (
                    ("clash.meta/1.19.33 Clash/v1 Darwin/25 iPhone18,2", "Apple"),
                    ("clash-verge/v2.5.10 Darwin/25", "Apple"),
                    ("Windows Darwin clash-verge/v2.5.10", "Apple"),
                    ("CFNetwork/1568 Darwin/25", "Apple"),
                    ("Macintosh Intel Mac OS X 13_0", "Apple"),
                    ("clash-verge/v2.5.10", "Windows"),
                    ("Windows NT 10.0 Win64", "Windows"),
                    ("curl/8.11.0", ""),
                ):
                    expected = identity.subscription_files(
                        path("/srv/vps-subscriptions"), device["token"]
                    )[target]
                    check_config = dict(
                        mode=deployment["mode"],
                        features=deployment["features"],
                        subscription_host="127.0.0.1",
                        subscription_port=port,
                        frontend_config=str(path("/etc/mihomo/config.yaml")),
                    )
                    assert "identities match" in subscription(
                        check_config,
                        device["id"],
                        base + ".yaml",
                        expected,
                        user_agent=agent,
                        target=target,
                    )
                    for method in ("GET", "HEAD"):
                        request = Request(
                            base + ".yaml", headers={"User-Agent": agent}, method=method
                        )
                        with opener.open(request, timeout=5) as response:
                            assert response.status == 200
                            assert response.headers["Cache-Control"] == "no-store"
                            assert response.headers["Vary"] == "User-Agent"
                            data = response.read()
                            assert (
                                yaml.safe_load(data) == yaml.safe_load(expected.read_text())
                                if method == "GET"
                                else not data
                            )
                for suffix, method in (
                    (".Apple.yaml", "GET"),
                    (".Windows.yaml", "GET"),
                    (".yaml/extra", "GET"),
                    (".yaml", "POST"),
                ):
                    with pytest.raises(HTTPError) as error:
                        opener.open(Request(base + suffix, method=method), timeout=5)
                    assert error.value.code == 404
            first = next(iter(state["devices"].values()))
            old = first["token"]
            identity.revoke(state, first["id"])
            from vps_ops.files import save

            save(identity.IDENTITY, state)
            render.render(deployment, Path(__file__).parents[1] / "system")
            with pytest.raises(HTTPError) as removed:
                opener.open(f"http://127.0.0.1:{port}/s/" + old + ".yaml", timeout=5)
            assert removed.value.code == 404
        finally:
            process.terminate()
            process.wait(timeout=5)


def test_disabling_fingerprint_removes_only_its_owned_dependency(node):
    path, state, deployment = node
    unrelated = path("/etc/systemd/system/mihomo.service.d/60-user.conf")
    unrelated.write_text("[Unit]\nWants=example-user.service\n")
    changed = dict(deployment, features={"fingerprint": True, "rtt": deployment["features"]["rtt"]})
    render.render(changed, Path(__file__).parents[1] / "system")
    dependencies = path("/etc/systemd/system/mihomo.service.d/45-fingerprint.conf")
    assert "tcpfp-windows-test.service" in dependencies.read_text()
    changed["features"]["fingerprint"] = False
    render.render(changed, Path(__file__).parents[1] / "system")
    assert not dependencies.exists()
    assert "tcpfp-" not in path("/etc/systemd/system/mihomo.service.d/50-tls.conf").read_text()
    assert "example-user.service" in unrelated.read_text()
    assert identity.load() == state


def test_revoking_all_devices_removes_public_auth_and_preserves_unowned_files(node):
    path, state, deployment = node
    untouched = path("/srv/vps-subscriptions/personal-unmanaged.yaml")
    untouched.write_text("personal: data\n")
    for device in state["devices"].values():
        identity.revoke(state, device["id"])
    from vps_ops.files import save

    save(identity.IDENTITY, state)
    render.render(deployment, Path(__file__).parents[1] / "system")
    assert yaml.safe_load(path("/etc/mihomo/config.yaml").read_text())["listeners"] == []
    assert json.loads(path("/etc/mihomo-observed/collector.json").read_text())["users"] == []
    assert (
        len(json.loads(path("/etc/mihomo-observed/collector.json").read_text())["user_labels"]) == 4
    )
    assert json.loads(path("/etc/vps-ops/subscriptions.json").read_text()) == {}
    assert list(path("/srv/vps-subscriptions").glob("*.yaml")) == [untouched]
