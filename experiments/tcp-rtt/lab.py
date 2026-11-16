"""Isolated split-TCP experiment. Run as root on Linux."""

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

NAMES = ("rtt-client", "rtt-edge", "rtt-site", "rtt-wire1", "rtt-wire2")


def run(*args, timeout=30, output=None):
    result = subprocess.run(
        args,
        check=True,
        stdout=output or subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    return result.stdout or ""


def ns(name, *args, timeout=30, output=None):
    return run("ip", "netns", "exec", name, *args, timeout=timeout, output=output)


def cleanup():
    existing = run("ip", "netns", "list")
    for name in NAMES:
        if name not in existing.split():
            continue
        for pid in run("ip", "netns", "pids", name).split():
            os.kill(int(pid), 15)
        run("ip", "netns", "del", name)


def stop(signum, _frame):
    raise SystemExit(128 + signum)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("run", "cleanup"))
    p.add_argument("--probe", type=Path)
    p.add_argument("--mihomo", type=Path)
    p.add_argument("--output", type=Path, default=Path("temp/tcp-rtt"))
    p.add_argument("--count", type=int, default=30)
    p.add_argument("--ack-policy", choices=("handshake", "data", "none"))
    p.add_argument("--ack-delay", type=int, default=50)
    p.add_argument("--size", type=int, default=1024)
    p.add_argument("--timestamps", type=int, choices=(0, 1), default=1)
    p.add_argument("--client-delay-ms", type=int, default=25)
    p.add_argument("--server-delay-ms", type=int, default=25)
    p.add_argument("--handshake-control", action="store_true")
    p.add_argument("--rate-mbit", type=int, default=0)
    p.add_argument("--queue-limit", type=int, default=1000)
    p.add_argument("--cc", choices=("bbr", "cubic"), default="bbr")
    a = p.parse_args()
    if a.action == "cleanup":
        cleanup()
        return
    if not a.probe or not a.mihomo or a.count < 1:
        p.error("--probe, --mihomo and a positive --count are required")
    existing = run("ip", "netns", "list").split()
    if any(n in existing for n in NAMES):
        p.error("Experiment namespace exists; run cleanup first")
    out = a.output.resolve()
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    signal.signal(signal.SIGTERM, stop)
    processes = []
    handles = []
    completed = False

    def start(name, log, *cmd):
        handle = (out / log).open("w")
        handles.append(handle)
        process = subprocess.Popen(
            ["ip", "netns", "exec", name, *cmd], stdout=handle, stderr=subprocess.STDOUT
        )
        processes.append(process)
        return process

    try:
        for name in NAMES:
            run("ip", "netns", "add", name)
            ns(name, "ip", "link", "set", "lo", "up")
            ns(name, "sysctl", "-qw", f"net.ipv4.tcp_timestamps={a.timestamps}")
            ns(name, "sysctl", "-qw", f"net.ipv4.tcp_congestion_control={a.cc}")
        for left, right, subnet, ln, rn, wire in [
            (NAMES[0], NAMES[1], 1, "rc", "ec", NAMES[3]),
            (NAMES[1], NAMES[2], 2, "es", "rs", NAMES[4]),
        ]:
            ns(wire, "ip", "link", "add", "br0", "type", "bridge")
            ns(wire, "ip", "link", "set", "br0", "up")
            for name, dev, host in ((left, ln, 1), (right, rn, 2)):
                peer = "w" + dev
                run(
                    "ip",
                    "link",
                    "add",
                    dev,
                    "netns",
                    name,
                    "type",
                    "veth",
                    "peer",
                    "name",
                    peer,
                    "netns",
                    wire,
                )
                ns(name, "ip", "addr", "add", f"10.231.{subnet}.{host}/24", "dev", dev)
                ns(name, "ip", "link", "set", dev, "up")
                ns(wire, "ip", "link", "set", peer, "master", "br0")
                ns(wire, "ip", "link", "set", peer, "up")
                ns(name, "ethtool", "-K", dev, "tso", "off", "gso", "off", "gro", "off")
                ns(wire, "ethtool", "-K", peer, "tso", "off", "gso", "off", "gro", "off")
        ns(NAMES[0], "ip", "route", "add", "default", "via", "10.231.1.2")
        ns(NAMES[2], "ip", "route", "add", "default", "via", "10.231.2.1")
        ns(NAMES[1], "sysctl", "-qw", "net.ipv4.ip_forward=1")
        config = out / "mihomo.json"
        config.write_text(
            json.dumps(
                {
                    "mixed-port": 8888,
                    "allow-lan": True,
                    "bind-address": "10.231.1.2",
                    "log-level": "silent",
                    "rules": ["MATCH,DIRECT"],
                }
            )
        )
        config.chmod(0o600)
        start(NAMES[1], "mihomo.log", str(a.mihomo.resolve()), "-d", str(out), "-f", str(config))
        ca = out / "ca.pem"
        start(NAMES[2], "server.jsonl", str(a.probe.resolve()), "-mode", "server", "-ca", str(ca))
        deadline = time.monotonic() + 15
        while not ca.exists():
            if time.monotonic() > deadline or any(x.poll() is not None for x in processes):
                raise RuntimeError("Experiment startup failed; inspect output logs")
            time.sleep(0.1)
        (out / "environment.json").write_text(
            json.dumps(
                {
                    "kernel": run("uname", "-r").strip(),
                    "tc": run("tc", "-V").strip(),
                    "count": a.count,
                    "timestamps": a.timestamps,
                    "congestion_control": a.cc,
                    "ack_policy": a.ack_policy,
                    "rate_mbit": a.rate_mbit,
                    "handshake_control": a.handshake_control,
                    "queue_limit": a.queue_limit,
                    "ack_delay_ms": a.ack_delay,
                    "response_bytes": a.size,
                    "client_delay_ms": a.client_delay_ms,
                    "server_delay_ms": a.server_delay_ms,
                    "mihomo_version": run(str(a.mihomo.resolve()), "-v").strip(),
                    "topology": "client -> wire1 -> split proxy -> wire2 -> site",
                },
                indent=2,
            )
        )
        if a.ack_policy and a.ack_policy != "none":
            start(
                NAMES[1],
                "ack.jsonl",
                str(a.probe.resolve()),
                "-mode",
                "ack",
                "-ack-policy",
                a.ack_policy,
                "-delay",
                f"{a.ack_delay}ms",
            )
            time.sleep(0.5)
            if processes[-1].poll() is not None:
                raise RuntimeError("ACK queue failed to start")
            ns(NAMES[1], "nft", "add", "table", "ip", "rtt_lab")
            ns(
                NAMES[1],
                "nft",
                "add",
                "chain",
                "ip",
                "rtt_lab",
                "out",
                "{ type filter hook output priority 0; }",
            )
            ns(
                NAMES[1],
                "nft",
                "add",
                "chain",
                "ip",
                "rtt_lab",
                "in",
                "{ type filter hook input priority 0; }",
            )
            ns(
                NAMES[1],
                "nft",
                "add",
                "rule",
                "ip",
                "rtt_lab",
                "out",
                "ip",
                "daddr",
                "10.231.2.2",
                "tcp",
                "dport",
                "4433",
                "queue",
                "num",
                "9500",
            )
            ns(
                NAMES[1],
                "nft",
                "add",
                "rule",
                "ip",
                "rtt_lab",
                "in",
                "ip",
                "saddr",
                "10.231.2.2",
                "tcp",
                "sport",
                "4433",
                "tcp",
                "flags",
                "&",
                "(",
                "syn",
                "|",
                "ack",
                ")",
                "==",
                "(",
                "syn",
                "|",
                "ack",
                ")",
                "queue",
                "num",
                "9500",
            )
        for name, dev in ((NAMES[1], "es"), (NAMES[2], "rs")):
            start(
                name,
                name + "-capture.log",
                "tcpdump",
                "-U",
                "-i",
                dev,
                "-w",
                str(out / (name + ".pcap")),
                "tcp",
                "port",
                "4433",
            )
        capture_deadline = time.monotonic() + 10
        while any(
            "listening on" not in (out / (name + "-capture.log")).read_text()
            for name in (NAMES[1], NAMES[2])
        ):
            if time.monotonic() > capture_deadline or any(p.poll() is not None for p in processes):
                raise RuntimeError("Capture failed to become ready")
            time.sleep(0.05)
        cases = (
            ((a.client_delay_ms, a.server_delay_ms),)
            if a.ack_policy
            else ((0, 0), (25, 0), (50, 0), (0, 25), (0, 50))
        )
        for client_delay, server_delay in cases:
            for name, dev, delay in (
                (NAMES[3], "wrc", client_delay),
                (NAMES[3], "wec", client_delay),
                (NAMES[4], "wes", server_delay),
                (NAMES[4], "wrs", server_delay),
            ):
                ns(
                    name,
                    "tc",
                    "qdisc",
                    "replace",
                    "dev",
                    dev,
                    "root",
                    "netem",
                    "delay",
                    f"{delay}ms",
                    "limit",
                    str(a.queue_limit),
                    *(["rate", f"{a.rate_mbit}mbit"] if a.rate_mbit else []),
                )
            for proxy in (
                (False,) if a.handshake_control else ((True,) if a.ack_policy else (False, True))
            ):
                for fresh in (True,) if a.handshake_control else (False, True):
                    label = f"client{client_delay}-site{server_delay}-proxy{int(proxy)}-fresh{int(fresh)}"
                    cmd = [
                        str(a.probe.resolve()),
                        "-ca",
                        str(ca),
                        "-count",
                        str(a.count if fresh else a.count + 1),
                        "-size",
                        str(a.size),
                    ]
                    if a.handshake_control:
                        cmd += ["-pre-tls-delay", "150ms"]
                    if proxy:
                        cmd += ["-proxy", "http://10.231.1.2:8888"]
                    if fresh:
                        cmd += ["-fresh", "-h1"]
                    with (out / (label + ".jsonl")).open("w") as output:
                        ns(
                            NAMES[1] if a.handshake_control else NAMES[0],
                            *cmd,
                            timeout=max(120, a.count * 5),
                            output=output,
                        )
                    queues = {
                        f"{n}/{dev}": json.loads(
                            ns(n, "tc", "-j", "-s", "qdisc", "show", "dev", dev)
                        )
                        for n, dev in (
                            (NAMES[3], "wrc"),
                            (NAMES[3], "wec"),
                            (NAMES[4], "wes"),
                            (NAMES[4], "wrs"),
                        )
                    }
                    (out / (label + "-queues.json")).write_text(json.dumps(queues))
                    print(label, flush=True)
        completed = True
    finally:
        environment = out / "environment.json"
        if environment.exists():
            metadata = json.loads(environment.read_text())
            metadata["run_completed"] = completed
            environment.write_text(json.dumps(metadata, indent=2))
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for handle in handles:
            handle.close()
        cleanup()


if __name__ == "__main__":
    main()
