import json
import subprocess

import pytest

from vps_ops import cli, status


def test_status_overview_and_selected_sections(monkeypatch, capsys):
    calls = []
    services = ["mihomo", "caddy", "vps-rules.path"]
    monkeypatch.setattr(cli, "config", lambda _: {"services": services})

    def command(args):
        calls.append(args)
        if args[:2] == ["systemctl", "show"]:
            if args[2] == "caddy":
                return "NRestarts=0\nActiveState=inactive\nSubState=dead"
            if args[2] == "vps-rules.path":
                return "ActiveState=active\nSubState=waiting"
            return "NRestarts=2\nActiveState=active\nSubState=running"
        outputs = {
            "uname": "Linux 6.8",
            "uptime": "05:01:49 up 1 day, 15:25, 1 user, load average: 0.00, 0.01, 0.02",
            "free": "total used free shared buff/cache available\n"
            "Mem: 961Mi 410Mi 98Mi 2.6Mi 599Mi 550Mi\nSwap: 0B 0B 0B",
            "df": "Filesystem Type Size Used Avail Use% Mounted on\n"
            "/dev/vda1 ext4 20G 4G 15G 23% /",
            "ss": "State Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
            "LISTEN 0 4096 0.0.0.0:23899 0.0.0.0:*\n"
            "LISTEN 0 128 [::1]:8080 [::]:*",
            "ip": "default via 192.0.2.1 dev eth0",
            "ufw": "Status: active",
            "apt": "Listing...\nexample/stable 2.0 [upgradable from: 1.0]",
            "journalctl": '{"MESSAGE":"one"}\n{"MESSAGE":"two"}',
            "systemctl": "0 loaded units listed.",
        }
        return outputs[args[0]]

    monkeypatch.setattr(status, "run", command)
    assert cli.execute(["status"]) == 0
    output = capsys.readouterr().out
    assert "System\n" in output and "Resources\n" in output and "Services\n" in output
    assert "Uptime: 1 day, 15h 25m" in output
    assert "Load average (1/5/15 minutes): 0.00 / 0.01 / 0.02" in output
    assert "Used: 410 MiB / 961 MiB" in output and "Available: 550 MiB" in output
    assert "Swap: Not configured" in output and "Used: 4 GiB / 20 GiB (23%)" in output
    assert "Active: 2/3" in output
    assert "mihomo: Running (restarts: 2)" in output
    assert "caddy: Inactive (restarts: 0)" in output
    assert "Failed system units: None" in output
    assert "ActiveState=" not in output and "\\n" not in output
    assert ["df", "-hT", "/"] in calls
    assert not {"ss", "ip", "ufw", "apt", "journalctl"} & {args[0] for args in calls}

    calls.clear()
    assert cli.execute(["status", "--service", "mihomo.service"]) == 0
    output = capsys.readouterr().out
    assert "mihomo: Running (restarts: 2)" in output
    assert "caddy" not in output
    assert len(calls) == 1 and calls[0][:3] == ["systemctl", "show", "mihomo"]

    calls.clear()
    assert cli.execute(["status", "--network"]) == 0
    output = capsys.readouterr().out
    assert "0.0.0.0:23899 (LISTEN)\n" in output
    assert "[::1]:8080 (LISTEN)\n" in output
    assert "Receive queue: 0; Send queue: 4096" in output
    assert {args[0] for args in calls} == {"ss", "ip"}

    calls.clear()
    assert cli.execute(["--json", "status", "--all"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["services"]["mihomo"] == "NRestarts=2\nActiveState=active\nSubState=running"
    assert data["error_count_24h"] == 2
    assert "listeners" in data and "firewall" in data and "updates" in data
    assert ["df", "-hT"] in calls


def test_status_survives_a_single_service_query_failure(monkeypatch, capsys):
    monkeypatch.setattr(cli, "config", lambda _: {"services": ["mihomo", "caddy"]})

    def command(args):
        if args[:3] == ["systemctl", "show", "caddy"]:
            raise subprocess.TimeoutExpired(args, 1)
        return "ActiveState=active\nSubState=running\nNRestarts=0"

    monkeypatch.setattr(status, "run", command)
    assert cli.execute(["status", "--services"]) == 0
    output = capsys.readouterr().out
    assert "mihomo: Running" in output
    assert "caddy: Query failed" in output


def test_package_list_uses_readable_text_and_supports_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "config", lambda _: {})
    packages = "Listing...\nexample/stable 2.0 amd64 [upgradable from: 1.0]"
    monkeypatch.setattr(cli, "run", lambda _: packages)
    assert cli.execute(["packages", "list"]) == 0
    output = capsys.readouterr().out
    assert "Upgradable packages:" in output and "example (stable)" in output
    assert "Current: 1.0\n" in output and "Available: 2.0 (amd64)\n" in output
    assert "Listing..." not in output
    assert cli.execute(["--json", "packages", "list"]) == 0
    assert json.loads(capsys.readouterr().out) == {"updates": packages}


def test_status_help_needs_no_server_configuration(monkeypatch, capsys):
    monkeypatch.setattr(cli, "config", lambda _: pytest.fail("help should not read configuration"))
    with pytest.raises(SystemExit) as result:
        cli.execute(["status", "--help"])
    assert result.value.code == 0
    output = capsys.readouterr().out
    assert "--network" in output and "--service" in output and "--all" in output


def test_failed_certificate_check_returns_failure_without_changing_shell_arguments(
    tmp_path, capsys
):
    import sys

    original = sys.argv
    result = cli.execute(
        [
            "certificate",
            "check",
            "--cert",
            str(tmp_path / "missing.pem"),
            "--hostname",
            "example.com",
        ]
    )
    assert result == 1
    assert "[fail] Certificate file does not exist" in capsys.readouterr().err
    assert sys.argv is original


def test_usage_report_is_readable_and_json_remains_available(monkeypatch, capsys):
    report = {
        "latest_state": ["2026-11-14T05:00:00+00:00", "gap/error"],
        "last_success": "2026-11-14T04:59:00+00:00",
        "fresh": False,
        "users": [
            {
                "user": "phone",
                "ever_observed": True,
                "upload_bytes": 1024,
                "download_bytes": 0,
                "active_connections": None,
            }
        ],
    }
    from vps_ops import usage_daemon

    monkeypatch.setattr(usage_daemon, "read_report", lambda _: report)
    assert cli.execute(["usage", "report"]) == 0
    output = capsys.readouterr().out
    assert "Usage (approximate observations)" in output
    assert "Data freshness: Stale or unavailable" in output and "Sampling failed" in output
    assert "phone\n" in output and "Upload: 1.00 KiB (1,024 bytes)" in output
    assert "Active connections: Unknown" in output
    assert '{"' not in output and "\\n" not in output

    assert cli.execute(["usage", "report", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == report


def test_checks_and_subscription_addresses_are_formatted(monkeypatch, tmp_path, capsys):
    from vps_ops.deploy import client

    monkeypatch.setattr(cli, "config", lambda _: {})
    monkeypatch.setattr(
        cli,
        "checks",
        lambda *_: [
            {"state": "pass", "name": "Certificate", "detail": "Start: today\nExpires: next year"}
        ],
    )
    assert cli.execute(["check", "certificate"]) == 0
    assert "[pass] Certificate:\n  Start: today\n  Expires: next year" in capsys.readouterr().out

    subscription_file = tmp_path / "subscriptions.json"
    subscriptions = {
        "device-id": {
            "name": "Laptop",
            "platform": "Windows",
            "url": "https://example.invalid/s/private.yaml",
        }
    }
    subscription_file.write_text(json.dumps(subscriptions))
    monkeypatch.setattr(client, "Path", lambda _: subscription_file)
    assert cli.execute(["deploy", "show", "subscriptions"]) == 0
    output = capsys.readouterr().out
    assert "Laptop (device-id): https://example.invalid/s/private.yaml\n" in output
    assert '{"' not in output
    assert cli.execute(["--json", "deploy", "show", "subscriptions"]) == 0
    assert json.loads(capsys.readouterr().out) == subscriptions


def test_structured_logs_are_readable_or_json_without_exposing_secrets(
    monkeypatch, tmp_path, capsys
):
    import io
    from types import SimpleNamespace

    config = tmp_path / "frontend.yaml"
    config.write_text("password: 'p\"ss'\n")
    monkeypatch.setattr(
        cli, "config", lambda _: {"services": ["caddy"], "frontend_config": str(config)}
    )
    token = "x" * 43
    event = {
        "level": "error",
        "msg": "request failed",
        "request": {"uri": f"/s/{token}.yaml", "authorization": 'p"ss'},
    }
    commands = []

    def process(args, **_):
        commands.append(args)
        if "-o" in args:
            line = json.dumps({"MESSAGE": json.dumps(event), "PRIORITY": "3"})
        else:
            line = "Nov 14 05:01:02 host caddy[7]: " + json.dumps(event)
        return SimpleNamespace(stdout=io.StringIO(line + "\n"), wait=lambda: 0, poll=lambda: 0)

    monkeypatch.setattr(subprocess, "Popen", process)
    assert cli.execute(["logs", "caddy"]) == 0
    output = capsys.readouterr().out
    assert "caddy[7]:\n" in output and "Level: error" in output
    assert "Message: request failed" in output and "request:\n" in output
    assert token not in output and 'p"ss' not in output and 'p\\"ss' not in output
    assert '"request"' not in output

    assert cli.execute(["logs", "caddy", "--json"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["PRIORITY"] == "3" and "request failed" in record["MESSAGE"]
    assert token not in record["MESSAGE"] and 'p"ss' not in record["MESSAGE"]
    message = json.loads(record["MESSAGE"])
    assert message["request"]["authorization"] == "[REDACTED]"
    assert message["request"]["uri"] == "/s/[REDACTED].yaml"
    assert ["-o", "json"] == commands[-1][-2:]


def test_shell_continues_after_failed_operations_and_invalid_arguments(monkeypatch, capsys):
    commands = iter(
        [
            "certificate check --cert missing.pem --hostname example.com",
            "unknown-command",
            "profile generate --help",
            "exit",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    assert cli.execute(["shell"]) == 0
    captured = capsys.readouterr()
    assert "Certificate file does not exist" in captured.err
    assert "invalid choice" in captured.err
    assert "--kind" in captured.out


def test_closing_journal_stream_releases_its_process(monkeypatch, tmp_path, capsys):
    import sys

    from vps_ops.runtime import journal

    original = subprocess.Popen
    processes = []

    def start(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", start)
    records = journal(
        [sys.executable, "-u", "-c", "import time; print('ready', flush=True); time.sleep(30)"],
        {"frontend_config": str(tmp_path / "missing.yaml")},
    )
    try:
        assert next(records) == "ready\n"
        assert capsys.readouterr().out == ""
    finally:
        records.close()
    assert processes[0].poll() is not None
