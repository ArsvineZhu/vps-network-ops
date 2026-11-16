import subprocess
from pathlib import Path

from resolver import CONTENT, repair

from vps_ops import checks, runtime


def test_resolver_persistent_and_idempotent(tmp_path):
    repair(tmp_path)
    repair(tmp_path)
    for ns in ("tcpfp-windows-test", "tcpfp-ios-test"):
        assert (tmp_path / ns / "resolv.conf").read_text() == CONTENT


def test_partial_failure_keeps_other_results(monkeypatch):
    def command(args, **kwargs):
        if "windows" in " ".join(args):
            raise subprocess.TimeoutExpired(args, 1)
        return "200"

    monkeypatch.setattr(checks, "run", command)
    result = checks.checks(runtime.DEFAULT, "dns")
    assert any(r["state"] == "fail" for r in result)
    assert any(r["state"] == "pass" for r in result)
    assert all("TimeoutExpired" in r["detail"] for r in result if r["state"] == "fail")


def test_proxy_secret_only_in_stdin(monkeypatch):
    def command(args, **kwargs):
        assert "secret" not in str(args)
        assert "secret" in kwargs["input"]
        return "200"

    monkeypatch.setattr(runtime, "run", command)
    assert runtime.curl("https://example.com", "socks5h://127.0.0.1:1080", "u:secret") == "HTTP 200"


def test_network_cold_start_with_no_namespaces(monkeypatch):
    import runpy

    import engines
    import resolver

    calls = []
    monkeypatch.setattr(engines, "load", lambda: {"windows": "nfqueue", "ios": "tc"})
    monkeypatch.setattr(resolver, "repair", lambda: None)

    def command(args, **kwargs):
        calls.append(args)
        value = '{"nftables": []}' if args[0] == "nft" else "[]" if "link" in args else ""
        return subprocess.CompletedProcess(args, 0, stdout=value)

    monkeypatch.setattr(subprocess, "run", command)
    runpy.run_path(str(Path(__file__).parents[1] / "system/tcpfp/network.py"))
    assert ["/bin/bash", "/etc/tcpfp/network.sh"] in calls
