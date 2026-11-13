import json
import subprocess
import sys
from pathlib import Path

import clash_profile


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
    assert profile["rules"] == ["MATCH,VPS-Select"]


def test_member_generation_uses_a_distinct_identity(tmp_path):
    script = Path(clash_profile.__file__).with_name("new_member.py")
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
            [sys.executable, script, source, name, output, "--policy", policy],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        client = json.loads((output / "profile.yaml").read_text(encoding="utf-8"))
        server = json.loads((output / "server-user.pending.json").read_text(encoding="utf-8"))
        assert client["proxies"][0]["uuid"] == server["uuid"]
        assert server["uuid"] not in result.stdout
        identities.append(server["uuid"])
    assert identities[0] != identities[1]
