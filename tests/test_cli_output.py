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
    assert "系统\n" in output and "资源\n" in output and "服务\n" in output
    assert "运行时间：1 天, 15 小时 25 分钟" in output
    assert "平均负载（1/5/15 分钟）：0.00 / 0.01 / 0.02" in output
    assert "已用：410 MiB / 961 MiB" in output and "可用：550 MiB" in output
    assert "交换空间：未配置" in output and "已用：4 GiB / 20 GiB（23%）" in output
    assert "活动：2/3 项" in output
    assert "mihomo：运行中（重启 2 次）" in output
    assert "caddy：未运行（重启 0 次）" in output
    assert "系统失败单元：无" in output
    assert "ActiveState=" not in output and "\\n" not in output
    assert ["df", "-hT", "/"] in calls
    assert not {"ss", "ip", "ufw", "apt", "journalctl"} & {args[0] for args in calls}

    calls.clear()
    assert cli.execute(["status", "--service", "mihomo.service"]) == 0
    output = capsys.readouterr().out
    assert "mihomo：运行中（重启 2 次）" in output
    assert "caddy" not in output
    assert len(calls) == 1 and calls[0][:3] == ["systemctl", "show", "mihomo"]

    calls.clear()
    assert cli.execute(["status", "--network"]) == 0
    output = capsys.readouterr().out
    assert "0.0.0.0:23899（LISTEN）\n" in output
    assert "[::1]:8080（LISTEN）\n" in output
    assert "接收队列：0；发送队列：4096" in output
    assert {args[0] for args in calls} == {"ss", "ip"}

    calls.clear()
    assert cli.execute(["--json", "status", "--all"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["服务"]["mihomo"] == "NRestarts=2\nActiveState=active\nSubState=running"
    assert data["最近24小时错误数"] == 2
    assert "监听" in data and "防火墙" in data and "更新" in data
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
    assert "mihomo：运行中" in output
    assert "caddy：读取失败" in output


def test_package_list_uses_readable_text_and_supports_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "config", lambda _: {})
    packages = "Listing...\nexample/stable 2.0 amd64 [upgradable from: 1.0]"
    monkeypatch.setattr(cli, "run", lambda _: packages)
    assert cli.execute(["packages", "list"]) == 0
    output = capsys.readouterr().out
    assert "待更新软件包：" in output and "example（stable）" in output
    assert "当前：1.0\n" in output and "可更新：2.0（amd64）\n" in output
    assert "Listing..." not in output
    assert cli.execute(["--json", "packages", "list"]) == 0
    assert json.loads(capsys.readouterr().out) == {"更新": packages}


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
    assert "[失败] 证书：证书文件不存在" in capsys.readouterr().out
    assert sys.argv is original


def test_usage_report_is_readable_and_json_remains_available(monkeypatch, capsys):
    report = {
        "latest_state": ["2026-11-14T05:00:00+00:00", "gap/error"],
        "last_success": "2026-11-14T04:59:00+00:00",
        "fresh": False,
        "users": [
            {
                "user": "手机",
                "ever_observed": True,
                "upload_bytes": 1024,
                "download_bytes": 0,
                "active_connections": None,
            }
        ],
    }
    monkeypatch.setattr(cli, "dispatch_module", lambda *_: print(json.dumps(report)))
    assert cli.execute(["usage", "report"]) == 0
    output = capsys.readouterr().out
    assert "用量（近似观察值）" in output
    assert "数据状态：未更新或不可用" in output and "采集失败" in output
    assert "手机\n" in output and "上传：1.00 KiB（1,024 字节）" in output
    assert "活跃连接：未知" in output
    assert '{"' not in output and "\\n" not in output

    assert cli.execute(["usage", "report", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == report


def test_checks_and_subscription_addresses_are_formatted(monkeypatch, tmp_path, capsys):
    from vps_ops.deploy import client

    monkeypatch.setattr(cli, "config", lambda _: {})
    monkeypatch.setattr(
        cli,
        "checks",
        lambda *_: [{"state": "通过", "name": "证书", "detail": "开始：今天\n到期：明年"}],
    )
    assert cli.execute(["check", "certificate"]) == 0
    assert "[通过] 证书：\n  开始：今天\n  到期：明年" in capsys.readouterr().out

    subscription_file = tmp_path / "subscriptions.json"
    subscriptions = {
        "win": "https://example.invalid/s/private.yaml",
        "Apple": "https://example.invalid/s/other.yaml",
    }
    subscription_file.write_text(json.dumps(subscriptions))
    monkeypatch.setattr(client, "Path", lambda _: subscription_file)
    assert cli.execute(["deploy", "show", "subscriptions"]) == 0
    output = capsys.readouterr().out
    assert "win：https://example.invalid/s/private.yaml\n" in output
    assert "Apple：https://example.invalid/s/other.yaml\n" in output
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
    assert "caddy[7]:\n" in output and "级别：error" in output
    assert "信息：request failed" in output and "request：\n" in output
    assert token not in output and 'p"ss' not in output and 'p\\"ss' not in output
    assert '"request"' not in output

    assert cli.execute(["logs", "caddy", "--json"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["PRIORITY"] == "3" and "request failed" in record["MESSAGE"]
    assert token not in record["MESSAGE"] and 'p"ss' not in record["MESSAGE"]
    message = json.loads(record["MESSAGE"])
    assert message["request"]["authorization"] == "[隐藏]"
    assert message["request"]["uri"] == "/s/[隐藏].yaml"
    assert ["-o", "json"] == commands[-1][-2:]
