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
            observed_usage.ingest(db, item, "2026-01-01T00:00:00+00:00", "vless", {"owner"}, "vps")
        assert db.execute("SELECT user,up,down FROM totals").fetchall() == [("owner", 15, 25)]
        assert "private.invalid" not in "\n".join(db.iterdump())
        with pytest.raises(ValueError, match="scope"):
            observed_usage.ingest(db, snapshot(), "2", "other", {"owner"}, "vps")
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

    config = {"socket": str(path), "inbound": "vless", "instance": "vps", "users": ["owner"]}
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
