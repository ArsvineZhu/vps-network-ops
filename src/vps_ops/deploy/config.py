"""Fresh-node deployment input and capability ownership."""

import ipaddress
import re
from pathlib import Path

import yaml

from vps_ops.capabilities import MODES, Capabilities

DNS = {
    "cloudflare": ("dns_cf", ["CF_Token"]),
    "aliyun": ("dns_ali", ["Ali_Key", "Ali_Secret"]),
    "dnspod": ("dns_tencent", ["Tencent_SecretId", "Tencent_SecretKey"]),
    "dnspod-token": ("dns_dp", ["DP_Id", "DP_Key"]),
}


def load(path):
    c = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(c, dict) or c.get("mode") not in MODES:
        raise ValueError("Invalid deployment mode")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*", c.get("target", "")):
        raise ValueError("Invalid SSH target")
    if (
        not isinstance(c.get("port", 22), int)
        or isinstance(c.get("port", 22), bool)
        or not 1 <= c.get("port", 22) <= 65535
    ):
        raise ValueError("Invalid SSH port")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", c.get("name", "vps-node")):
        raise ValueError("Node name must contain at most 63 lowercase letters, digits or hyphens")
    public = Path(c["public_key"]).expanduser()
    c["authorized_key"] = public.read_text().strip()
    if not re.fullmatch(
        r"(?:ssh-|ecdsa-|sk-)[^\s]+ [A-Za-z0-9+/=]+(?: [^\n]*)?", c["authorized_key"]
    ):
        raise ValueError("An OpenSSH public key is required")
    plan = Capabilities.from_config(c)
    if plan.mihomo:
        from vps_ops.identity import validate_device

        first = c.get("device")
        if not isinstance(first, dict):
            raise ValueError(
                "The first device name and platform are required; use deploy configure"
            )
        validate_device(first.get("name"), first.get("platform"))
        ipaddress.IPv4Address(c["public_ipv4"])
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]+", c["domain"]):
            raise ValueError("Invalid subscription domain")
        if not isinstance(c.get("email"), str) or "@" not in c["email"]:
            raise ValueError("An ACME contact email is required")
        provider = c["dns_provider"]
        plugin, names = DNS.get(provider, (provider, c.get("dns_credentials", [])))
        if not re.fullmatch(r"dns_[a-zA-Z0-9_]+", plugin) or not names:
            raise ValueError("DNS plugin and credential fields are required")
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n) for n in names):
            raise ValueError("Invalid DNS credential field")
        c["dns_plugin"], c["dns_names"] = plugin, names
    c.setdefault("name", "vps-node")
    c.setdefault("port", 22)
    if c.get("identity"):
        c["identity"] = str(Path(c["identity"]).expanduser().resolve())
    c["work"] = "/var/lib/vps-ops/deploy"
    c["features"] = {"fingerprint": plan.fingerprint, "rtt": plan.rtt}
    c["plan"] = plan.installation()
    c["services"] = plan.services
    return c


def preview(c):
    plan = Capabilities.from_config(c)
    return {
        "name": c["name"],
        "target": c["target"],
        "mode": plan.mode,
        "fingerprint": plan.fingerprint,
        "rtt": plan.rtt,
        "wireguard": plan.wireguard,
        "services": plan.services,
        "ports": plan.ports,
        "tailscale": plan.tailscale,
        "mihomo": plan.mihomo,
    }
