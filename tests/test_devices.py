"""Physical device isolation, revocation and live credential reconciliation."""

import pytest

from vps_ops import devices, identity
from vps_ops.wireguard import client_node, peers, server_configuration


def test_devices_have_independent_profile_credentials_and_monotonic_addresses(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(identity, "IDENTITY", tmp_path / "identity.json")
    state = identity.ensure({"device": {"name": "Laptop one", "platform": "Windows"}})
    first = next(iter(state["devices"].values()))
    second = identity.add(state, "Laptop two", "Windows")
    assert "token" in second and "profiles" in second
    assert first["id"] != second["id"] and first["token"] != second["token"]
    for key in ("windows", "ios"):
        left, right = first["profiles"][key], second["profiles"][key]
        for field in ("uuid", "hy", "tls"):
            assert left[field] != right[field]
        assert left["wireguard"] != right["wireguard"]
        assert left["user"] == first["id"] + "." + key
    server_key = state["wireguard"]["server"].copy()
    old_address = first["profiles"]["windows"]["wireguard"]["address"]
    old_public = first["profiles"]["windows"]["wireguard"]["public"]
    assert len(peers(state)) == 6
    assert "Address = 10.220.0.1/15" in server_configuration(state)
    assert client_node(state, first["id"], "windows", "192.0.2.5")["ip"] == old_address
    identity.revoke(state, first["id"])
    assert set(first) == {"id", "name", "platform", "active"}
    assert len(peers(state)) == 3
    assert old_public not in server_configuration(state)
    assert first["id"] + ".windows" in identity.user_labels(state)
    third = identity.add(state, "Laptop three", "Windows")
    assert "profiles" in third
    assert third["profiles"]["windows"]["wireguard"]["address"] not in {
        old_address,
        second["profiles"]["windows"]["wireguard"]["address"],
    }
    assert state["wireguard"]["server"] == server_key
    from vps_ops.files import save

    save(identity.IDENTITY, state)
    assert identity.ensure({"device": {"name": "Laptop one", "platform": "Windows"}}) == state
    assert not identity.load()["devices"][first["id"]]["active"]


def test_active_device_names_are_unique_without_spending_addresses():
    state = identity.create()
    identity.add(state, "My laptop", "Windows")
    index = state["wireguard"]["next_peer"]
    with pytest.raises(ValueError, match="already uses"):
        identity.add(state, "my LAPTOP", "Apple")
    assert state["wireguard"]["next_peer"] == index


def test_new_profile_provisioning_preserves_registered_devices(tmp_path, monkeypatch):
    import copy

    monkeypatch.setattr(identity, "IDENTITY", tmp_path / "identity.json")
    state = identity.create()
    current = identity.add(state, "Linux desktop", "Default")
    lost = identity.add(state, "Lost", "Apple")
    identity.revoke(state, lost["id"])
    assert "profiles" in current
    current["profiles"].pop("default")
    original = copy.deepcopy(current)
    identity.ensure_profiles(state)
    assert "token" in current and "token" in original
    assert current["token"] == original["token"]
    assert current["profiles"]["windows"] == original["profiles"]["windows"]
    assert current["profiles"]["ios"] == original["profiles"]["ios"]
    assert current["profiles"]["default"]["wireguard"]["address"].startswith("10.221.")
    assert "profiles" not in lost
    persisted = identity.load()
    identity.ensure_profiles(state)
    assert state == persisted


@pytest.mark.parametrize("changed", (False, True))
@pytest.mark.parametrize("empty", (False, True))
def test_hot_reconciliation_syncs_peers_and_closes_only_revoked_connections(
    tmp_path, monkeypatch, changed, empty
):
    from contextlib import nullcontext

    from vps_ops import forwarding
    from vps_ops.deploy import render, server

    state = identity.create()
    revoked = identity.add(state, "Lost", "Windows")
    revoked_user = revoked["id"] + ".windows"
    identity.revoke(state, revoked["id"])
    monkeypatch.setattr(devices, "node_lock", nullcontext)
    monkeypatch.setattr(
        devices, "node_config", lambda: {"mode": "mihomo", "features": {"rtt": True}}
    )
    monkeypatch.setattr(identity, "load", lambda: state)

    def path(value):
        return tmp_path / str(value).lstrip("/")

    caddy = path("/etc/caddy/Caddyfile")
    caddy.parent.mkdir(parents=True)
    caddy.write_text("current")
    frontend = path("/etc/mihomo/config.yaml")
    frontend.parent.mkdir(parents=True)
    frontend.write_text("listeners: []\n")
    monkeypatch.setattr(devices, "Path", path)
    monkeypatch.setattr(server, "asset_directory", lambda: tmp_path)
    monkeypatch.setattr(
        render, "render", lambda *args: caddy.write_text("changed" if changed else "current")
    )
    commands, requests, refreshed = [], [], []
    monkeypatch.setattr(
        devices.subprocess, "run", lambda arguments, **kwargs: commands.append(arguments)
    )

    def run(arguments, **kwargs):
        commands.append(arguments)
        return (
            "[Interface]\nPrivateKey = private-test-key"
            if arguments[:2] == ["wg-quick", "strip"]
            else ""
        )

    monkeypatch.setattr(devices, "run", run)

    def request(method, route, value=None):
        requests.append((method, route, value))
        return (
            {
                "connections": [
                    {"id": "revoked-session", "metadata": {"inboundUser": revoked_user}},
                    {"id": "kept-session", "metadata": {"inboundUser": "kept.windows"}},
                ]
                if not empty
                else None
            }
            if method == "GET"
            else None
        )

    monkeypatch.setattr(devices, "controller", request)
    monkeypatch.setattr(forwarding, "refresh_peers", lambda config, state: refreshed.append(state))
    assert devices.sync() == {"active": 0}
    assert requests[0] == ("PUT", "/configs?force=true", {"payload": "listeners: []\n"})
    assert (("DELETE", "/connections/revoked-session", None) in requests) == (not empty)
    assert not any(route.endswith("kept-session") for _, route, _ in requests)
    assert ["wg", "syncconf", "vps-ops", "/dev/stdin"] in commands
    assert ["ip", "route", "replace", "10.220.0.0/15", "dev", "vps-ops"] in commands
    assert refreshed == [state]
    assert not any("restart" in command for command in commands)
    assert (["caddy", "validate", "--config", str(caddy)] in commands) == changed
    assert (
        ["systemctl", "kill", "--kill-whom=main", "--signal=USR1", "caddy"] in commands
    ) == changed


def test_nonintrusive_wireguard_health_never_loads_a_client_key():
    from vps_ops.probes import frontend

    with pytest.raises(ValueError, match="without loading device private keys"):
        frontend({}, "wireguard", "Windows", device_id="device")


def test_sync_retries_all_historical_revocations_without_their_secrets(tmp_path, monkeypatch):
    from contextlib import nullcontext

    state = identity.create()
    first = identity.add(state, "Lost laptop", "Windows")
    second = identity.add(state, "Current laptop", "Windows")
    identity.revoke(state, first["id"])
    monkeypatch.setattr(devices, "node_lock", nullcontext)
    monkeypatch.setattr(devices, "node_config", lambda: {"mode": "mihomo"})
    monkeypatch.setattr(identity, "load", lambda: state)
    calls = []
    monkeypatch.setattr(
        devices, "reconcile", lambda config, current, revoked: calls.append((current, revoked))
    )
    result = devices.sync()
    assert result == {"active": 1}
    assert calls == [
        (state, {first["id"] + ".default", first["id"] + ".windows", first["id"] + ".ios"})
    ]
    assert "profiles" not in first and "token" not in first
    assert second["active"]


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"connections": {}},
        {"connections": False},
        {"connections": [None]},
        {"connections": [{"metadata": None}]},
    ),
)
def test_malformed_connection_collections_are_rejected_by_shared_contract(payload):
    from vps_ops.mihomo import connection_rows

    with pytest.raises(ValueError, match="Mihomo connection"):
        connection_rows(payload)
