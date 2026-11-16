#!/usr/bin/env python3
"""Generate a local Mihomo profile from a private JSON node descriptor. Fixed VLESS TCP REALITY xtls-rprx-vision; no networking."""

import argparse
import base64
import ipaddress
import json
import os
import re
import uuid
from pathlib import Path

import yaml

from .subscription_policy import configure


def generate(d, *, target=None):
    if target not in (None, "win", "Apple"):
        raise ValueError("target must be win or Apple")
    required = {"server", "port", "uuid", "servername", "public_key", "short_id"}
    if not isinstance(d, dict) or not required <= d.keys():
        raise ValueError("missing required descriptor fields")
    if set(d) - required - {"name", "fingerprint"}:
        raise ValueError("unknown descriptor fields (never supply server private keys)")
    if not isinstance(d["port"], int) or isinstance(d["port"], bool) or not 1 <= d["port"] <= 65535:
        raise ValueError("port must be 1..65535")

    def host(s):
        if not isinstance(s, str) or not s or len(s) > 253:
            return False
        try:
            ipaddress.ip_address(s)
            return True
        except ValueError:
            return all(
                re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", p)
                for p in s.split(".")
            )

    if not host(d["server"]) or not host(d["servername"]):
        raise ValueError("invalid server or servername")
    if not isinstance(d["uuid"], str):
        raise ValueError("uuid must be text")
    ident = str(uuid.UUID(d["uuid"]))
    key = d["public_key"]
    if (
        not isinstance(key, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", key)
        or len(base64.urlsafe_b64decode(key + "=")) != 32
    ):
        raise ValueError("public_key must be a 32-byte base64url public key")
    sid = d["short_id"]
    if not isinstance(sid, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}){0,8}", sid):
        raise ValueError("short_id must be even-length hex, at most 16 digits")
    name = f"{target} · VLESS" if target else d.get("name", "node")
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 80
        or any(ord(c) < 32 for c in name)
        or name.startswith("Route-")
        or name in {"DIRECT", "REJECT", "GLOBAL", "VPS-Select"}
    ):
        raise ValueError("invalid node name")
    fp = d.get("fingerprint", "ios" if target == "Apple" else "chrome")
    if fp not in {"chrome", "firefox", "safari", "ios", "android", "edge", "random"}:
        raise ValueError("unsupported fingerprint")
    node = {
        "name": name,
        "type": "vless",
        "server": d["server"],
        "port": d["port"],
        "uuid": ident,
        "network": "tcp",
        "tls": True,
        "udp": True,
        "flow": "xtls-rprx-vision",
        "servername": d["servername"],
        "client-fingerprint": fp,
        "reality-opts": {"public-key": key, "short-id": sid},
    }
    tun = {"enable": True}
    if target != "Apple":
        tun.update(
            {
                "stack": "mips",
                "auto-route": True,
                "auto-detect-interface": True,
                "strict-route": True,
                "dns-mode": "hijack",
                "dns-hijack": ["any:53", "tcp://any:53"],
            }
        )
    return {
        "mixed-port": 7897,
        "allow-lan": False,
        "bind-address": "127.0.0.1",
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "tun": tun,
        "dns": {
            "enable": True,
            "ipv6": False,
            "enhanced-mode": "fake-ip",
            "fake-ip-filter": ["+.lan", "+.local"],
            "nameserver": ["https://1.1.1.1/dns-query#节点"],
            "proxy-server-nameserver": ["https://1.1.1.1/dns-query"],
        },
        "proxies": [node],
        "proxy-groups": [{"name": "节点", "type": "select", "proxies": [name], "default-selected": name}],
        "rules": ["MATCH,节点"],
    }


def main():
    p = argparse.ArgumentParser(description="从节点信息生成客户端配置")
    p.add_argument("descriptor", type=Path, help="节点信息 JSON 文件")
    p.add_argument("output", type=Path, help="尚不存在的输出文件")
    p.add_argument(
        "--policy",
        type=Path,
        help="完整配置使用的共享路由策略文件",
    )
    p.add_argument(
        "--kind",
        choices=["profile", "provider"],
        default="profile",
        help="profile 为完整配置，provider 为节点提供者文件",
    )
    p.add_argument(
        "--target", choices=["win", "Apple"], help="设备目标；使用对应身份名称和客户端配置"
    )
    a = p.parse_args()
    if a.kind == "profile" and not a.policy:
        p.error("生成完整配置需要 --policy")
    try:
        profile = generate(json.loads(a.descriptor.read_text(encoding="utf-8-sig")), target=a.target)
        if a.kind == "provider":
            profile = {"proxies": profile["proxies"]}
        else:
            profile = configure(profile, yaml.safe_load(a.policy.read_text(encoding="utf-8")))
        # Exclusive creation prevents overwriting or following an existing symlink.
        fd = os.open(a.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError) as e:
        # Exception messages from parsing may contain credentials; print type only.
        p.exit(1, "生成失败（" + type(e).__name__ + "）。请检查节点信息和输出路径。\n")
    if a.kind == "provider":
        print("已生成节点提供者文件，请在客户端配置中引用。")
    else:
        print("已生成客户端配置，请在客户端导入并启用。")
    if os.name == "nt":
        print("请检查输出目录的 Windows 访问权限（ACL）。")


if __name__ == "__main__":
    main()
