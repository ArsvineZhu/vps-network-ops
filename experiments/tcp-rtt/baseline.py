"""Measure real Windows proxy paths through the existing Mihomo controller."""

import argparse
import glob
import http.client
import json
import subprocess
from pathlib import Path


class PipeConnection:
    def __init__(self, path):
        self.file = open(path, "r+b", buffering=0)

    def sendall(self, data):
        self.file.write(data)

    def makefile(self, *args, **kwargs):
        return self.file

    def close(self):
        self.file.close()


def request(pipe, method, path, data=None):
    connection = http.client.HTTPConnection("localhost", timeout=10)
    connection.sock = PipeConnection(pipe)
    try:
        connection.request(
            method,
            path,
            body=json.dumps(data) if data else None,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = response.read()
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Controller returned HTTP {response.status}")
        return json.loads(body) if body else None
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pipe", default="auto")
    parser.add_argument("--platform", choices=("Windows", "Apple"), default="Windows")
    parser.add_argument("--observer", choices=("cleanip", "onems"), default="cleanip")
    parser.add_argument("--count", type=int, default=30)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")
    pipes = glob.glob(r"//./pipe/verge-mihomo-production-*") if args.pipe == "auto" else [args.pipe]
    if len(pipes) != 1:
        parser.error("Specify --pipe when exactly one controller cannot be discovered")
    pipe = pipes[0]
    group = request(pipe, "GET", "/proxies/Nodes")
    if not isinstance(group, dict):
        raise RuntimeError("Controller returned no node selector")
    original = group["now"]
    nodes = [n for n in group["all"] if n.startswith(args.platform + " · ")]
    if len(nodes) != 3:
        parser.error("Expected all three protocols for the selected platform")
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    url = {
        "cleanip": "https://fp.cleanip.io:8443/api/probe",
        "onems": "https://who.1ms.dog/api/me",
    }[args.observer]
    try:
        for node in nodes:
            request(pipe, "PUT", "/proxies/Nodes", {"name": node})
            protocol = node.split(" · ", 1)[1]
            for fresh in (False, True):
                command = [
                    str(args.probe.resolve()),
                    "-ca",
                    "",
                    "-url",
                    url,
                    "-count",
                    str(args.count if fresh else args.count + 1),
                ]
                if fresh:
                    command.append("-fresh")
                with (args.output / f"{protocol}-{'fresh' if fresh else 'reuse'}.jsonl").open(
                    "w"
                ) as output:
                    subprocess.run(command, stdout=output, check=True, timeout=args.count * 32 + 10)
                print(protocol, "fresh" if fresh else "reuse", "complete", flush=True)
    finally:
        request(pipe, "PUT", "/proxies/Nodes", {"name": original})


if __name__ == "__main__":
    main()
