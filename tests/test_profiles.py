import json
import subprocess
import sys
from pathlib import Path

import yaml

from vps_ops import clash_profile, subscription_policy


def test_profile_routes_through_the_node():
    node = {
        "server": "example.invalid",
        "port": 8443,
        "uuid": "11111111-1111-4111-8111-111111111111",
        "servername": "example.com",
        "public_key": "A" * 43,
        "short_id": "aabb",
    }
    profile = clash_profile.generate(node)
    assert profile["proxies"][0]["uuid"] == node["uuid"]
    assert profile["rules"] == ["MATCH,节点"]
    assert profile["dns"]["nameserver"] == ["https://1.1.1.1/dns-query#节点"]
    assert profile["tun"]["enable"] is True
    assert "strict-route" not in profile["tun"]
    assert profile["proxy-groups"][0]["default-selected"] == profile["proxies"][0]["name"]


def test_target_controls_identity_and_client_tun():
    node = {
        "server": "192.0.2.5",
        "port": 8443,
        "uuid": "11111111-1111-4111-8111-111111111111",
        "servername": "example.com",
        "public_key": "A" * 43,
        "short_id": "aabb",
    }
    win = clash_profile.generate(node, target="win")
    apple = clash_profile.generate(node, target="Apple")
    assert win["proxies"][0]["name"] == "win · VLESS"
    assert apple["proxies"][0]["name"] == "Apple · VLESS"
    assert apple["proxies"][0]["client-fingerprint"] == "ios"
    assert win["tun"]["strict-route"] is True
    assert apple["tun"] == {"enable": True}
    assert apple["proxy-groups"][0]["default-selected"] == "Apple · VLESS"
    assert apple["profile"]["store-selected"] is False

    policy = yaml.safe_load(
        (Path(__file__).parents[1] / "system/subscriptions/rules.yaml").read_text()
    )
    complete = subscription_policy.configure(apple, policy)
    names = [node["name"] for node in complete["proxies"]]
    names += [group["name"] for group in complete["proxy-groups"]]
    assert len(names) == len(set(names))
    assert complete["proxy-groups"][1]["name"] == "GLOBAL"


def test_member_generation_uses_a_distinct_identity(tmp_path):
    source = tmp_path / "server.json"
    source.write_text(
        json.dumps(
            {
                "server": "example.invalid",
                "port": 8443,
                "servername": "example.com",
                "public_key": "A" * 43,
                "short_id": "aabb",
            }
        ),
        encoding="utf-8",
    )
    identities = []
    for name in ("first", "second"):
        output = tmp_path / name
        policy = Path(__file__).parents[1] / "system/subscriptions/rules.yaml"
        result = subprocess.run(
            [sys.executable, "-m", "vps_ops.new_member", source, name, output, "--target", "win", "--policy", policy],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        client = json.loads((output / "profile.yaml").read_text(encoding="utf-8"))
        server = json.loads((output / "server-user.pending.json").read_text(encoding="utf-8"))
        assert client["proxies"][0]["uuid"] == server["uuid"]
        assert client["proxies"][0]["name"] == "win · VLESS"
        assert server["uuid"] not in result.stdout
        identities.append(server["uuid"])
    assert identities[0] != identities[1]
