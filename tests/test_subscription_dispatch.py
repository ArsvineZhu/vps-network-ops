"""Exercise generated subscriptions through a real Caddy HTTP server."""

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

from vps_ops.deploy import render
from vps_ops.probes import subscription


@pytest.fixture
def node(tmp_path, monkeypatch):
    def path(value):
        if Path(value).is_relative_to(tmp_path):
            return Path(value)
        return tmp_path / str(value).lstrip("/")

    monkeypatch.setattr(render, "Path", path)
    monkeypatch.setattr(os, "chown", lambda *args: None, raising=False)
    monkeypatch.setitem(
        sys.modules, "grp", SimpleNamespace(getgrnam=lambda _: SimpleNamespace(gr_gid=0))
    )
    monkeypatch.setitem(
        sys.modules, "pwd", SimpleNamespace(getpwnam=lambda _: SimpleNamespace(pw_uid=0))
    )
    config = dict(public_ipv4="192.0.2.5", domain="example.invalid", port=23899, name="test")
    path("/srv/vps-subscriptions").mkdir(parents=True)
    render.render(config, Path(__file__).parents[1] / "system")
    identity = json.loads(path("/etc/vps-ops/identity.json").read_text())
    render.render(config, Path(__file__).parents[1] / "system")
    assert json.loads(path("/etc/vps-ops/identity.json").read_text()) == identity
    return path, identity


def test_generated_profiles_have_all_identities_and_correct_defaults(node, monkeypatch):
    path, identity = node
    root = path("/srv/vps-subscriptions")
    config = dict(
        subscription_host="example.invalid",
        subscription_port=9443,
        frontend_config=str(path("/etc/mihomo/config.yaml")),
    )
    for target in ("", "Windows", "Apple"):
        expected = root / (identity["auto_token"] + ("." + target if target else "") + ".yaml")
        response = expected.read_text()
        if target:
            role = "windows" if target == "Windows" else "ios"
            legacy = root / (identity["roles"][role]["token"] + ".yaml")
            assert yaml.safe_load(legacy.read_text()) == yaml.safe_load(response)
        monkeypatch.setattr(
            "vps_ops.probes.curl", lambda *args, response=response, **kwargs: response
        )
        assert "identities match" in subscription(
            config, "https://example.invalid", expected, target=target
        )
        wrong = yaml.safe_load(response)
        wrong["proxies"][0]["uuid"] = "wrong-identity"
        monkeypatch.setattr(
            "vps_ops.probes.curl", lambda *args, wrong=wrong, **kwargs: yaml.safe_dump(wrong)
        )
        with pytest.raises(RuntimeError, match="does not match"):
            subscription(config, "https://example.invalid", expected, target=target)
        expected.write_text(yaml.safe_dump(wrong))
        with pytest.raises(RuntimeError, match="credentials"):
            subscription(config, "https://example.invalid", expected, target=target)
        expected.write_text(response)


def test_caddy_delivers_all_identities_with_platform_defaults(node, tmp_path):
    caddy = os.environ.get("CADDY") or shutil.which("caddy")
    if not caddy:
        pytest.skip("Caddy is required")
    path, identity = node
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    source = path("/etc/caddy/Caddyfile").read_text()
    source = source.replace("https://example.invalid:9443", f"http://127.0.0.1:{port}")
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
            base = f"http://127.0.0.1:{port}/s/auto/" + identity["auto_token"]
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
                expected = path("/srv/vps-subscriptions") / (
                    identity["auto_token"] + ("." + target if target else "") + ".yaml"
                )
                check_config = dict(
                    subscription_host="127.0.0.1",
                    subscription_port=port,
                    frontend_config=str(path("/etc/mihomo/config.yaml")),
                )
                assert "identities match" in subscription(
                    check_config, base + ".yaml", expected, user_agent=agent, target=target
                )
                for method in ("GET", "HEAD"):
                    request = Request(base + ".yaml", headers={"User-Agent": agent}, method=method)
                    with opener.open(request, timeout=5) as response:
                        assert response.status == 200
                        assert response.headers["Cache-Control"] == "no-store"
                        assert response.headers["Vary"] == "User-Agent"
                        data = response.read()
                        if method == "GET":
                            assert yaml.safe_load(data) == yaml.safe_load(expected.read_text())
                        else:
                            assert not data
            for suffix, method in (
                (".Apple.yaml", "GET"),
                (".Windows.yaml", "GET"),
                (".yaml/extra", "GET"),
                (".yaml", "POST"),
            ):
                with pytest.raises(HTTPError) as error:
                    opener.open(Request(base + suffix, method=method), timeout=5)
                assert error.value.code == 404
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
