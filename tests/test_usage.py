import http.server
import json
import os
import socketserver
import sqlite3
import threading

import pytest

from vps_ops import observed_usage


def snapshot(upload=10, download=20, user="owner"):
    return {
        "connections": [
            {
                "id": "connection-1",
                "metadata": {
                    "inboundName": "vless",
                    "inboundUser": user,
                    "host": "private.invalid",
                },
                "upload": upload,
                "download": download,
            }
        ]
    }


def test_usage_deduplicates_samples_and_keeps_scope():
    with sqlite3.connect(":memory:") as db:
        for item in (snapshot(10, 20), snapshot(10, 20), {"connections": None}, snapshot(15, 25)):
            records, ignored = observed_usage.mihomo_records(item, {"vless"}, {"owner"})
            observed_usage.ingest(
                db,
                records,
                "2026-01-01T00:00:00+00:00",
                "vless",
                "vps",
                {"mihomo"},
                ignored=ignored,
            )
        assert db.execute("SELECT user,up,down FROM totals").fetchall() == [("owner", 15, 25)]
        assert "private.invalid" not in "\n".join(db.iterdump())
        with pytest.raises(ValueError, match="scope"):
            observed_usage.ingest(db, [], "2", "other", "vps", {"mihomo"})
        assert db.execute("SELECT up,down FROM totals").fetchone() == (15, 25)


@pytest.mark.skipif(os.name == "nt", reason="Unix controller socket requires Linux")
def test_sampler_records_failure_then_reads_the_unix_controller(tmp_path):
    from vps_ops import usage_daemon

    path = tmp_path / "control.sock"
    calls = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            data = json.dumps(snapshot()).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    config = {
        "socket": str(path),
        "scope": "vless",
        "inbounds": ["vless"],
        "wireguard_snapshot": None,
        "instance": "vps",
        "users": ["owner"],
        "user_labels": {"owner": "Laptop · Windows"},
    }
    with sqlite3.connect(":memory:") as db:
        assert not usage_daemon.sample(db, config, "1")
        with socketserver.UnixStreamServer(str(path), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                assert usage_daemon.sample(db, config, "2")
            finally:
                server.shutdown()
                thread.join()
        assert calls == ["/connections"]
        assert db.execute("SELECT state FROM polls").fetchall() == [("gap/error",), ("observed",)]
        assert db.execute("SELECT up,down FROM totals").fetchone() == (10, 20)


def test_usage_preserves_persistent_totals_and_watermarks(tmp_path):
    path = tmp_path / "usage.sqlite"
    with sqlite3.connect(path) as db:
        # Existing production schema, including a disappeared connection watermark.
        db.executescript("""
            CREATE TABLE scope (singleton INTEGER PRIMARY KEY, instance TEXT, inbound TEXT);
            INSERT INTO scope VALUES (1,'vps','vless-in');
            CREATE TABLE totals (user TEXT PRIMARY KEY, up INTEGER, down INTEGER);
            INSERT INTO totals VALUES ('owner',100,200);
            CREATE TABLE watermarks (id TEXT PRIMARY KEY,user TEXT,up INTEGER,down INTEGER,active INTEGER);
            INSERT INTO watermarks VALUES ('connection-1','owner',10,20,0);
        """)
    for up in (15, 12, 18):
        with sqlite3.connect(path) as db:
            records = [observed_usage.UsageRecord("connection-1", "owner", up, 25)]
            observed_usage.ingest(db, records, "1", "vless-in", "vps", {"mihomo"})
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT up,down FROM totals").fetchone() == (108, 205)
        assert db.execute("SELECT source FROM watermarks").fetchone() == ("mihomo",)


def test_three_protocols_and_wireguard_epochs_share_user_totals():
    payload = {"connections": []}
    for name in ("vless-in", "hysteria2-in", "anytls-in"):
        row = snapshot()["connections"][0]
        row["id"] = name
        row["metadata"]["inboundName"] = name
        payload["connections"].append(row)
    records, ignored = observed_usage.mihomo_records(
        payload, {"vless-in", "hysteria2-in", "anytls-in"}, {"owner"}
    )
    with sqlite3.connect(":memory:") as db:
        for epoch in ("boot:3", "boot:4"):
            wg = observed_usage.UsageRecord(
                "wg:" + epoch + ":owner", "owner", 100, 200, "wireguard", False
            )
            observed_usage.ingest(
                db, records + [wg], "1", "vless-in", "vps", {"mihomo", "wireguard"}, ignored=ignored
            )
        assert db.execute("SELECT up,down FROM totals").fetchone() == (230, 460)
        assert db.execute("SELECT count(*) FROM watermarks WHERE active=1").fetchone() == (3,)


def test_partial_sample_accounts_working_source(tmp_path, monkeypatch):
    from vps_ops import usage_daemon

    c = {
        "socket": "unused",
        "scope": "vless",
        "instance": "vps",
        "users": ["owner"],
        "user_labels": {"owner": "Laptop · Windows"},
        "inbounds": ["vless"],
        "wireguard_snapshot": str(tmp_path / "missing"),
    }
    monkeypatch.setattr(usage_daemon, "fetch", lambda _: snapshot())
    with sqlite3.connect(":memory:") as db:
        assert not usage_daemon.sample(db, c, "1")
        assert db.execute("SELECT up,down FROM totals").fetchone() == (10, 20)
        assert db.execute("SELECT state FROM polls").fetchone() == ("partial/gap",)


def test_wireguard_snapshot_staleness_and_privacy(tmp_path):
    import time

    from vps_ops.usage_daemon import wireguard_records

    if os.name != "posix" or os.getuid() != 0:
        pytest.skip("Root-owned Linux snapshot boundary")
    path = tmp_path / "wg.json"
    payload = {
        "time": time.time(),
        "epoch": "boot:2",
        "users": [{"user": "owner", "upload": 100, "download": 200}],
    }
    path.write_text(json.dumps(payload))
    path.chmod(0o640)
    assert wireguard_records(path, {"owner"}) == [
        observed_usage.UsageRecord("wg:boot:2:owner", "owner", 100, 200, "wireguard", False)
    ]
    payload["time"] -= 30
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="stale"):
        wireguard_records(path, {"owner"})


def test_collector_schema_accepts_all_three_protocols_and_optional_tunnel():
    from vps_ops.usage_daemon import validate_config

    config = {
        "socket": "/var/lib/mihomo/controller/control.sock",
        "db": "/var/lib/mihomo-observed/usage.sqlite",
        "scope": "vless-in",
        "instance": "node",
        "users": ["owner"],
        "user_labels": {"owner": "Laptop · Windows"},
        "inbounds": ["vless-in", "hysteria2-in", "anytls-in"],
        "wireguard_snapshot": None,
        "interval": 5,
    }
    assert validate_config(config) == config
    config["wireguard_snapshot"] = "/run/vps-ops/wireguard-usage.json"
    assert validate_config(config) == config


def test_malformed_controller_does_not_discard_valid_tunnel_counters(monkeypatch):
    from vps_ops import usage_daemon

    config = {
        "socket": "unused",
        "scope": "vless-in",
        "instance": "node",
        "users": ["owner"],
        "user_labels": {"owner": "Laptop · Windows"},
        "inbounds": ["vless"],
        "wireguard_snapshot": "unused",
    }
    monkeypatch.setattr(usage_daemon, "fetch", lambda _: snapshot(upload=-1))
    monkeypatch.setattr(
        usage_daemon,
        "wireguard_records",
        lambda *_: [
            observed_usage.UsageRecord("wg:boot:2:owner", "owner", 20, 50, "wireguard", False)
        ],
    )
    with sqlite3.connect(":memory:") as db:
        assert not usage_daemon.sample(db, config, "1")
        assert db.execute("SELECT up,down FROM totals").fetchone() == (20, 50)
        assert db.execute("SELECT state FROM polls").fetchone() == ("partial/gap",)


def test_report_aggregates_tunnel_bytes_without_counting_peer_as_connection():
    from vps_ops.usage_daemon import report, stamp

    with sqlite3.connect(":memory:") as db:
        records = [
            observed_usage.UsageRecord("connection-1", "owner", 10, 20),
            observed_usage.UsageRecord("wg:boot:3:owner", "owner", 100, 200, "wireguard", False),
        ]
        observed_usage.ingest(db, records, stamp(), "vless-in", "node", {"mihomo", "wireguard"})
        result = report(
            db,
            {
                "scope": "vless-in",
                "instance": "node",
                "interval": 2,
                "users": ["owner"],
                "user_labels": {"owner": "Laptop · Windows"},
            },
        )
        assert result["fresh"]
        assert result["users"][0]["active_connections"] == 1
        assert result["users"][0]["upload_bytes"] == 110
        assert result["users"][0]["download_bytes"] == 220


def test_empty_active_registry_keeps_revoked_history():
    from vps_ops.usage_daemon import report, stamp, validate_config

    config = {
        "socket": "/var/lib/mihomo/controller/control.sock",
        "db": "/var/lib/mihomo-observed/usage.sqlite",
        "scope": "vless-in",
        "instance": "node",
        "users": [],
        "user_labels": {"retired.ios": "Old tablet · Apple"},
        "interval": 2,
        "inbounds": ["vless-in", "hysteria2-in", "anytls-in"],
        "wireguard_snapshot": None,
    }
    validate_config(config)
    with sqlite3.connect(":memory:") as db:
        observed_usage.ingest(
            db,
            [observed_usage.UsageRecord("old", "retired.ios", 100, 200)],
            stamp(),
            "vless-in",
            "node",
            {"mihomo"},
        )
        observed_usage.ingest(db, [], stamp(), "vless-in", "node", {"mihomo"})
        row = report(db, config)["users"][0]
        assert row["label"] == "Old tablet · Apple"
        assert row["active"] is False
        assert (row["upload_bytes"], row["download_bytes"], row["active_connections"]) == (
            100,
            200,
            0,
        )
