"""Compare Mihomo SOCKS and WireGuard against an observable HTTPS destination."""

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

from lab import ns, run

NAMES = ("wg-client-lab", "wg-server-lab", "wg-site-lab")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mihomo", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fingerprint", type=Path)
    parser.add_argument("--profile", choices=("windows", "ios"), default="windows")
    parser.add_argument("--count", type=int, default=30)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")
    if any(n in run("ip", "netns", "list").split() for n in NAMES):
        parser.error("WireGuard experiment namespace already exists")
    out = args.output.resolve()
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    processes, logs, created = [], [], []
    with tempfile.TemporaryDirectory(prefix="vps-wg-private-") as private:
        private = Path(private)

        def start(name, label, *command):
            log = (out / label).open("w")
            logs.append(log)
            process = subprocess.Popen(
                ["ip", "netns", "exec", name, *command], stdout=log, stderr=subprocess.STDOUT
            )
            processes.append(process)
            return process

        def key(name):
            secret = run("wg", "genkey")
            path = private / name
            path.write_text(secret + "\n")
            path.chmod(0o600)
            public = subprocess.run(
                ["wg", "pubkey"], input=secret, text=True, capture_output=True, check=True
            ).stdout.strip()
            return path, secret, public

        try:
            for name in NAMES:
                run("ip", "netns", "add", name)
                created.append(name)
                ns(name, "ip", "link", "set", "lo", "up")
            for left, right, la, ra, lip, rip in (
                (NAMES[0], NAMES[1], "wc", "ws", "10.234.1.2", "10.234.1.1"),
                (NAMES[1], NAMES[2], "wt", "we", "10.231.2.1", "10.231.2.2"),
            ):
                run(
                    "ip",
                    "link",
                    "add",
                    la,
                    "netns",
                    left,
                    "type",
                    "veth",
                    "peer",
                    "name",
                    ra,
                    "netns",
                    right,
                )
                for name, dev, address in ((left, la, lip), (right, ra, rip)):
                    ns(name, "ip", "addr", "add", address + "/24", "dev", dev)
                    ns(name, "ip", "link", "set", dev, "up")
            ns(NAMES[2], "ip", "route", "add", "10.234.0.0/16", "via", "10.231.2.1")
            ns(NAMES[1], "sysctl", "-qw", "net.ipv4.ip_forward=1")
            server_path, _, server_public = key("server.key")
            _, client_secret, client_public = key("client.key")
            ns(NAMES[1], "ip", "link", "add", "wg0", "type", "wireguard")
            ns(
                NAMES[1],
                "wg",
                "set",
                "wg0",
                "listen-port",
                "51821",
                "private-key",
                str(server_path),
                "peer",
                client_public,
                "allowed-ips",
                "10.234.10.2/32",
            )
            ns(NAMES[1], "ip", "addr", "add", "10.234.10.1/24", "dev", "wg0")
            ns(NAMES[1], "ip", "link", "set", "wg0", "up")
            for name, dev, delay in (
                (NAMES[0], "wc", 100),
                (NAMES[1], "ws", 100),
                (NAMES[1], "wt", 25),
                (NAMES[2], "we", 25),
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
                )
            server = private / "server.json"
            server.write_text(
                json.dumps(
                    {
                        "mixed-port": 8889,
                        "allow-lan": True,
                        "bind-address": "10.234.1.1",
                        "log-level": "silent",
                        "rules": ["MATCH,DIRECT"],
                    }
                )
            )
            start(
                NAMES[1],
                "mihomo-server.log",
                str(args.mihomo.resolve()),
                "-d",
                str(private / "server"),
                "-f",
                str(server),
            )
            ca = private / "ca.pem"
            start(
                NAMES[2],
                "server.jsonl",
                str(args.probe.resolve()),
                "-mode",
                "server",
                "-ca",
                str(ca),
            )
            capture = start(
                NAMES[2],
                "capture.log",
                "tcpdump",
                "-U",
                "-i",
                "we",
                "-w",
                str(out / "destination.pcap"),
                "tcp",
                "port",
                "4433",
            )
            deadline = time.monotonic() + 15
            while not ca.exists() or "listening on" not in (out / "capture.log").read_text():
                if time.monotonic() > deadline or any(p.poll() is not None for p in processes):
                    raise RuntimeError("Experiment startup failed")
                time.sleep(0.05)
            if args.fingerprint:
                fingerprint = private / "fingerprint.json"
                fingerprint.write_text(
                    json.dumps(
                        {
                            "interface": "wt",
                            "syn": {
                                "enabled": True,
                                "queue_num": 4949,
                                "profile": args.profile,
                                "failure_mode": "strict",
                                "status_interval": "1s",
                            },
                        }
                    )
                )
                start(
                    NAMES[1],
                    "fingerprint.log",
                    str(args.fingerprint.resolve()),
                    "run",
                    "-c",
                    str(fingerprint),
                )
                time.sleep(0.2)
                if processes[-1].poll() is not None:
                    raise RuntimeError("Fingerprint engine failed")
                ns(NAMES[1], "nft", "add", "table", "ip", "wg_fp")
                ns(
                    NAMES[1],
                    "nft",
                    "add",
                    "chain",
                    "ip",
                    "wg_fp",
                    "forward",
                    "{ type filter hook forward priority -150; }",
                )
                ns(
                    NAMES[1],
                    "nft",
                    "add",
                    "rule",
                    "ip",
                    "wg_fp",
                    "forward",
                    "iifname",
                    "wg0",
                    "ip",
                    "protocol",
                    "tcp",
                    "ip",
                    "ttl",
                    "set",
                    "128" if args.profile == "windows" else "64",
                )
                ns(
                    NAMES[1],
                    "nft",
                    "add",
                    "rule",
                    "ip",
                    "wg_fp",
                    "forward",
                    "iifname",
                    "wg0",
                    "tcp",
                    "flags",
                    "&",
                    "(",
                    "syn",
                    "|",
                    "ack",
                    ")",
                    "==",
                    "syn",
                    "queue",
                    "num",
                    "4949",
                )
            for mode in ("socks", "wireguard"):
                node = {"name": "exit", "type": "socks5", "server": "10.234.1.1", "port": 8889}
                if mode == "wireguard":
                    node = {
                        "name": "exit",
                        "type": "wireguard",
                        "server": "10.234.1.1",
                        "port": 51821,
                        "ip": "10.234.10.2",
                        "private-key": client_secret,
                        "public-key": server_public,
                        "allowed-ips": ["10.231.2.2/32"],
                        "udp": True,
                        "mtu": 1280,
                    }
                config = private / (mode + ".json")
                config.write_text(
                    json.dumps(
                        {
                            "mixed-port": 8888,
                            "log-level": "silent",
                            "proxies": [node],
                            "rules": ["MATCH,exit"],
                        }
                    )
                )
                config.chmod(0o600)
                client = start(
                    NAMES[0],
                    mode + ".log",
                    str(args.mihomo.resolve()),
                    "-d",
                    str(private / mode),
                    "-f",
                    str(config),
                )
                time.sleep(0.5)
                if client.poll() is not None:
                    raise RuntimeError("Mihomo client failed to start")
                with (out / ("client-" + mode + ".jsonl")).open("w") as result:
                    subprocess.run(
                        [
                            "ip",
                            "netns",
                            "exec",
                            NAMES[0],
                            str(args.probe.resolve()),
                            "-ca",
                            str(ca),
                            "-proxy",
                            "http://127.0.0.1:8888",
                            "-count",
                            str(args.count + 1),
                        ],
                        stdout=result,
                        check=True,
                        timeout=max(120, args.count * 5),
                    )
                client.terminate()
                client.wait(timeout=10)
                print(mode, "complete", flush=True)
            handshake = ns(NAMES[1], "wg", "show", "wg0", "latest-handshakes")
            (out / "environment.json").write_text(
                json.dumps(
                    {
                        "kernel": run("uname", "-r"),
                        "mihomo": run(str(args.mihomo.resolve()), "-v"),
                        "wireguard_handshake": any(
                            int(line.split()[-1]) > 0 for line in handshake.splitlines()
                        ),
                    },
                    indent=2,
                )
            )
            capture.terminate()
            capture.wait(timeout=5)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for log in logs:
                log.close()
            for name in reversed(created):
                run("ip", "netns", "del", name)


if __name__ == "__main__":
    main()
