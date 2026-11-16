import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from .capabilities import Capabilities

SERVICES = Capabilities.from_config({}).services
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
        raise RuntimeError(f"{args[0]} failed ({p.returncode})")
    return p.stdout.strip()


def config(path):
    result = DEFAULT | (yaml.safe_load(Path(path).read_text()) or {})
    if "mode" in result:
        result["services"] = Capabilities.from_config(result).services
    return result


def published_subscriptions(c):
    from .identity import subscription_files

    index = json.loads(Path("/etc/vps-ops/subscriptions.json").read_text(encoding="utf-8"))
    result = {}
    for identifier, entry in index.items():
        token = entry["url"].rsplit("/", 1)[-1].removesuffix(".yaml")
        result[identifier] = dict(
            entry, files=subscription_files(Path(c["subscription_root"]), token)
        )
    return result


def resolver():
    sys.path.insert(0, "/usr/local/lib/tcpfp")
    from resolver import repair

    repair()


def curl(url, proxy=None, auth=None, resolve=None, user_agent=None, *, body=False):
    lines = [
        "silent",
        "show-error",
        "connect-timeout = 8",
        "max-time = 20",
        'write-out = "\\n%{http_code}"',
        "url = " + json.dumps(url),
    ]
    if not body:
        lines.append('output = "/dev/null"')
    else:
        lines.append("max-filesize = 4194304")
    if proxy:
        lines.append("proxy = " + json.dumps(proxy))
    if auth:
        lines.append("proxy-user = " + json.dumps(auth))
    if resolve:
        lines.append("resolve = " + json.dumps(resolve))
    if user_agent:
        lines.append("user-agent = " + json.dumps(user_agent))
    response = run(["curl", "--config", "-"], input="\n".join(lines) + "\n")
    content, _, code = response.rpartition("\n")
    code = code or response
    if len(code) != 3 or not code.isdecimal():
        raise RuntimeError("Invalid HTTP status")
    if code != "200":
        raise RuntimeError("HTTP " + code)
    return content if body else "HTTP " + code


def journal(args, c, *, machine=False):

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
                value = value.replace(secret, "[REDACTED]")
                value = value.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[REDACTED]")
        value = re.sub(r"https?://[^\s\"']+", "[URLREDACTED]", value)
        return re.sub(r"/s/[A-Za-z0-9_-]{43}[.]yaml", "/s/[REDACTED].yaml", value)

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
                    yield redact_tree(record)
                else:
                    yield redact(line)
        code = process.wait()
        if code:
            raise RuntimeError(f"Journal query failed ({code})")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
