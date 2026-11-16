#!/usr/bin/env python3
"""Generate a local Mihomo profile from a private JSON node descriptor. Fixed VLESS TCP REALITY xtls-rprx-vision; no networking."""

import base64
import ipaddress
import json
import os
import re
import uuid

import yaml

from .subscription_policy import configure


def generate(d, *, target=None):
    if target not in (None, "Windows", "Apple"):
        raise ValueError("target must be Windows or Apple")
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
        or name in {"DIRECT", "REJECT", "GLOBAL", "Nodes"}
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
    tun: dict[str, bool | str | list[str]] = {"enable": True}
    if target == "Windows":
        tun.update(
            {
                "stack": "mixed",
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
            "nameserver": ["https://1.1.1.1/dns-query#Nodes"],
            "proxy-server-nameserver": ["https://1.1.1.1/dns-query"],
        },
        "proxies": [node],
        "proxy-groups": [
            {"name": "Nodes", "type": "select", "proxies": [name], "default-selected": name}
        ],
        "rules": ["MATCH,Nodes"],
    }


def generate_file(descriptor, output, *, policy=None, kind="profile"):
    if kind == "profile" and policy is None:
        raise ValueError("A complete profile requires --policy")
    try:
        profile = generate(json.loads(descriptor.read_text(encoding="utf-8-sig")))
        if kind == "provider":
            profile = {"proxies": profile["proxies"]}
        else:
            if policy is None:
                raise ValueError("A complete profile requires --policy")
            profile = configure(profile, yaml.safe_load(policy.read_text(encoding="utf-8")))
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(profile, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError) as exc:
        raise RuntimeError(
            "Profile generation failed; check the descriptor and output path"
        ) from exc
    return {"kind": kind, "output": str(output)}
