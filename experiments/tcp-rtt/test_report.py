import json

from report import summarize_observer


def test_zero_tcp_rtt_is_preserved_and_quic_is_not_reported_as_tcp(tmp_path):
    rows = [
        {
            "reused": True,
            "status": 200,
            "total_ns": 100_000_000,
            "observer": {"cf": {"httpProtocol": "HTTP/2", "clientTcpRtt": 0}},
        },
        {
            "reused": True,
            "status": 200,
            "total_ns": 200_000_000,
            "observer": {"cf": {"httpProtocol": "HTTP/3", "clientTcpRtt": 0}},
        },
        {"reused": False, "error": "connection timed out", "total_ns": 30_000_000_000},
    ]
    (tmp_path / "observer.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    result = summarize_observer(tmp_path)
    cold, warm = result
    assert cold["errors"] == 1 and cold["total_p50_ms"] is None
    assert warm["paired"] == 1
    assert warm["server_rtt_p50_ms"] == 0
    assert warm["difference_p50_ms"] == 100
