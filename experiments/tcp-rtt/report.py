"""Summarize experiment request timings and remote RTT observations."""

import argparse
import json
import math
import statistics
from pathlib import Path


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line]


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def metrics(case, group, paired):
    valid = [r for r in group if not r.get("error") and r.get("status") == 200]
    totals = sorted(r["total_ns"] / 1e6 for r in valid)
    return {
        "case": case,
        "reused": group[0]["reused"],
        "samples": len(group),
        "errors": len(group) - len(valid),
        "paired": len(paired),
        "total_p50_ms": median(totals),
        "total_p95_ms": totals[math.ceil(len(totals) * 0.95) - 1] if totals else None,
        "server_rtt_p50_ms": median(t["rtt_ms"] for _, t in paired),
        "server_min_rtt_p50_ms": median(t.get("min_rtt_ms") for _, t in paired),
        "server_rttvar_p50_ms": median(t.get("rttvar_ms") for _, t in paired),
        "difference_p50_ms": median(r["total_ns"] / 1e6 - t["rtt_ms"] for r, t in paired),
    }


def summarize(directory):
    requests, pending = {}, {}
    for row in records(directory / "server.jsonl"):
        connection = row.get("connection")
        if row.get("phase") == "request" and "request" in row:
            pending[connection] = row["request"]
        elif row.get("phase") == "request" and "tcp_info" in row:
            tcp = row["tcp_info"]
            requests[pending[connection]] = {
                "rtt_ms": tcp["Rtt"] / 1000,
                "min_rtt_ms": tcp["Min_rtt"] / 1000,
                "rttvar_ms": tcp["Rttvar"] / 1000,
            }
    result = []
    for path in sorted(directory.glob("client*.jsonl")):
        rows = records(path)
        for reused in (False, True):
            group = [r for r in rows if r["reused"] == reused]
            if not group:
                continue
            valid = [r for r in group if not r.get("error") and r.get("status") == 200]
            result.append(
                metrics(
                    path.stem,
                    group,
                    [(r, requests[r["request"]]) for r in valid if r["request"] in requests],
                )
            )
    return result


def summarize_observer(directory):
    result = []
    for path in sorted(directory.glob("*.jsonl")):
        rows = [r for r in records(path) if "total_ns" in r]
        for reused in (False, True):
            group = [r for r in rows if r["reused"] == reused]
            if not group:
                continue
            paired = []
            for row in group:
                if row.get("error") or row.get("status") != 200:
                    continue
                observer = row.get("observer", {})
                tcp = observer.get("tcp", {})
                if "rtt_ms" in tcp:
                    remote = tcp
                else:
                    cf = observer.get("cf", {})
                    remote = (
                        {"rtt_ms": cf.get("clientTcpRtt")}
                        if str(cf.get("httpProtocol", "")).startswith(("HTTP/1", "HTTP/2"))
                        else {}
                    )
                value = remote.get("rtt_ms")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    paired.append((row, remote))
            result.append(metrics(path.stem, group, paired))
    return result


def display(rows, as_json):
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    print(
        f"{'Case':<48} {'Reuse':<5} {'N':>4} {'Errors':>6} {'p50 ms':>9} {'p95 ms':>9} {'RTT ms':>9}"
    )

    def number(value):
        return f"{value:.2f}" if value is not None else "-"

    for row in rows:
        print(
            f"{row['case']:<48} {str(row['reused']):<5} {row['samples']:>4} {row['errors']:>6} {number(row['total_p50_ms']):>9} {number(row['total_p95_ms']):>9} {number(row['server_rtt_p50_ms']):>9}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source", choices=("lab", "observer"), default="lab")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    display(
        summarize(args.directory) if args.source == "lab" else summarize_observer(args.directory),
        args.json,
    )
