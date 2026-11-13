import json
import subprocess
import sys
from pathlib import Path

import yaml

SERVICES = [
    "mihomo",
    "mihomo-guard",
    "caddy",
    "tailscaled",
    "mihomo-observed",
    "tcpfp-network",
    "tcpfp-windows-test",
    "tcpfp-ios-test",
    "tcpfp-syn-windows",
    "tcpfp-syn-capture-windows",
    "vps-rules.path",
]
DEFAULT = {
    "services": SERVICES,
    "probe_url": "https://www.cloudflare.com/",
    "subscription_host": "sub.example.com",
    "subscription_port": 9443,
    "subscription_root": "/srv/vps-subscriptions",
    "frontend_config": "/etc/mihomo/config.yaml",
}


def run(args, timeout=25, input=None):
    p = subprocess.run(args, input=input, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"{args[0]} 执行失败（{p.returncode}）")
    return p.stdout.strip()


def config(path):
    return DEFAULT | (yaml.safe_load(Path(path).read_text()) or {})


def emit(data, machine=False):
    if machine:
        print(json.dumps(data, ensure_ascii=False))
    elif isinstance(data, list):
        for item in data:
            print(f"[{item['state']}] {item['name']}: {item['detail']}")
    elif isinstance(data, dict):
        for key, value in data.items():
            print(
                f"{key}: {value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}"
            )
    else:
        print(data)


def resolver():
    sys.path.insert(0, "/usr/local/lib/tcpfp")
    from resolver import repair

    repair()


def curl(url, proxy=None, auth=None, resolve=None):
    lines = [
        "silent",
        "show-error",
        'output = "/dev/null"',
        "connect-timeout = 8",
        "max-time = 20",
        'write-out = "%{http_code}"',
        "url = " + json.dumps(url),
    ]
    if proxy:
        lines.append("proxy = " + json.dumps(proxy))
    if auth:
        lines.append("proxy-user = " + json.dumps(auth))
    if resolve:
        lines.append("resolve = " + json.dumps(resolve))
    code = run(["curl", "--config", "-"], input="\n".join(lines) + "\n")
    if code != "200":
        raise RuntimeError("HTTP " + code)
    return "HTTP 200"


def filtered_logs(args, c):
    import re

    secrets = set()

    def collect(value, key=""):
        if isinstance(value, dict):
            for k, v in value.items():
                collect(v, k)
        elif isinstance(value, list):
            for v in value:
                collect(v, key)
        elif isinstance(value, str) and any(
            k in key.lower() for k in ("password", "uuid", "private-key", "secret", "token")
        ):
            secrets.add(value)

    path = Path(c["frontend_config"])
    if path.exists():
        collect(yaml.safe_load(path.read_text()))
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        if process.stdout is not None:
            for line in process.stdout:
                for secret in secrets:
                    if secret:
                        line = line.replace(secret, "[隐藏]")
                line = re.sub(r"https?://[^\s\"']+", "[URL隐藏]", line)
                print(line, end="", flush=True)
        return process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
