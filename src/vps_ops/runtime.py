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
    "probe_url": "https://www.cloudflare.com/cdn-cgi/trace",
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
    result = DEFAULT | (yaml.safe_load(Path(path).read_text()) or {})
    if "mode" in result:
        from .deploy.config import services

        selected = services(result["mode"])
        if "services" not in (yaml.safe_load(Path(path).read_text()) or {}):
            result["services"] = selected
    return result


def resolver():
    sys.path.insert(0, "/usr/local/lib/tcpfp")
    from resolver import repair

    repair()


def curl(url, proxy=None, auth=None, resolve=None, user_agent=None):
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
    if user_agent:
        lines.append("user-agent = " + json.dumps(user_agent))
    code = run(["curl", "--config", "-"], input="\n".join(lines) + "\n")
    if code != "200":
        raise RuntimeError("HTTP " + code)
    return "HTTP 200"


def filtered_logs(args, c, *, machine=False):
    import re

    from .output import format_log

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

    def redact(value):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[隐藏]")
                value = value.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[隐藏]")
        value = re.sub(r"https?://[^\s\"']+", "[URL隐藏]", value)
        return re.sub(r"/s/(?:auto/)?[A-Za-z0-9_-]{43}[.]yaml", "/s/[隐藏].yaml", value)

    def redact_tree(value):
        if isinstance(value, dict):
            return {redact(str(key)): redact_tree(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redact_tree(item) for item in value]
        if isinstance(value, str):
            if value.lstrip().startswith(("{", "[")):
                try:
                    embedded = json.loads(value)
                except ValueError:
                    pass
                else:
                    return json.dumps(redact_tree(embedded), ensure_ascii=False)
            return redact(value)
        return value

    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        if process.stdout is not None:
            for line in process.stdout:
                if machine:
                    try:
                        record = json.loads(line)
                    except ValueError:
                        record = {"message": line.rstrip()}
                    print(json.dumps(redact_tree(record), ensure_ascii=False), flush=True)
                else:
                    print(format_log(line, redact), end="", flush=True)
        return process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
