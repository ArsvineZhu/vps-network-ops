"""Keep configured nodes usable while real Tailscale authorization is pending."""

import json
import subprocess

import pytest

from vps_ops import checks, output, tailscale
from vps_ops.deploy import server


@pytest.mark.parametrize("mode", ("both", "tailscale"))
def test_pending_authorization_keeps_deployment_and_checks_available(mode, monkeypatch):
    phase = {"signed_in": False, "auth_started": False}
    commands = []
    url = "https://login.tailscale.com/a/private-test-login"

    def command(arguments, **kwargs):
        commands.append(arguments)
        assert kwargs["timeout"] <= 20
        if arguments[:3] == ["tailscale", "status", "--json"]:
            value = (
                {"BackendState": "Running", "Self": {"ExitNodeOption": True}}
                if phase["signed_in"]
                else {"BackendState": "NeedsLogin", "AuthURL": url if phase["auth_started"] else ""}
            )
            return subprocess.CompletedProcess(arguments, 0, json.dumps(value), "")
        assert arguments[:2] == ["tailscale", "up"]
        assert "--advertise-exit-node" in arguments
        assert "--timeout=5s" in arguments
        phase["auth_started"] = True
        return subprocess.CompletedProcess(arguments, 1, "", "authorization pending")

    monkeypatch.setattr(tailscale.subprocess, "run", command)
    config = {"mode": mode, "name": "test-node", "features": {"fingerprint": False, "rtt": True}}
    monkeypatch.setattr(server, "config", lambda _: config)
    monkeypatch.setattr(server, "checks", lambda current, _: checks._checks(current, "tailscale"))
    result = server.finish(config)
    assert result["readiness"] == "pending"
    assert result["tailscale"]["state"] == "login"
    assert result["checks"][0]["state"] == "warning"
    text = output.render(result, view="deployment")
    assert text.count(url) == 1
    assert "Node configured" in text and "session remains open" in text
    assert ("Clash and WireGuard are ready" in text) == (mode == "both")
    assert "check tailscale" in text

    up_calls = sum(arguments[1] == "up" for arguments in commands)
    phase["signed_in"] = True
    assert checks.checks(config, "tailscale")[0]["state"] == "pass"
    assert sum(arguments[1] == "up" for arguments in commands) == up_calls
