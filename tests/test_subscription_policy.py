import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from vps_ops import subscription_policy


def profile():
    return {
        "proxies": [{"name": "VPS", "type": "vless", "uuid": "private-test-value"}],
        "proxy-groups": [{"name": "VPS-Select", "type": "select", "proxies": ["VPS"]}],
        "rules": ["MATCH,VPS-Select"],
    }


def policy_path():
    return Path(__file__).parents[1] / "system/subscriptions/rules.yaml"


def test_configured_policy_is_shared_without_changing_nodes():
    original = profile()
    saved = copy.deepcopy(original)
    policy = yaml.safe_load(policy_path().read_text(encoding="utf-8"))
    policy["base-url"] = "https://rules.example.test:9443"
    policy["variables"]["server_ipv4"] = "203.0.113.5"
    result = subscription_policy.configure(original, policy)

    assert original == saved
    assert result["proxies"] == saved["proxies"]
    assert result["proxy-groups"][0] == saved["proxy-groups"][0]
    assert result["rule-providers"]["google-ai"]["url"].startswith(
        "https://rules.example.test:9443/rules/"
    )
    assert "203.0.113.5/32" in result["rules"][0]
    assert result["hosts"] == {"rules.example.test": "203.0.113.5"}
    assert subscription_policy.configure(result, policy) == result


def test_cli_updates_profile_without_exposing_credentials(tmp_path):
    source = tmp_path / "profile.yaml"
    source.write_text(yaml.safe_dump(profile()), encoding="utf-8")
    source.chmod(0o640)
    result = subprocess.run(
        [sys.executable, "-m", "vps_ops.subscription_policy", source, "--policy", policy_path()],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "private-test-value" not in result.stdout + result.stderr
    assert json.loads(source.read_text(encoding="utf-8"))["proxies"] == profile()["proxies"]
    if os.name != "nt":
        assert source.stat().st_mode & 0o777 == 0o640
