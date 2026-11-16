"""Generate a node's durable identity and existing service configuration."""

import base64
import json
import os
import secrets
import sys
import uuid
from pathlib import Path

import yaml

from vps_ops.clash_profile import generate
from vps_ops.subscription_policy import configure, write_profile


def save(path, data, mode=0o600):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    content = data if isinstance(data, str) else json.dumps(data, indent=2) + "\n"
    if p.exists() and p.read_text() == content:
        return
    import tempfile

    fd, name = tempfile.mkstemp(dir=p.parent, prefix="." + p.name)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, p)
    finally:
        temporary.unlink(missing_ok=True)


def render(c, assets):
    identity = Path("/etc/vps-ops/identity.json")
    if identity.exists():
        state = json.loads(identity.read_text())
    else:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        key = X25519PrivateKey.generate()

        def raw(v):
            return base64.urlsafe_b64encode(v).decode().rstrip("=")

        state = {
            "private": raw(
                key.private_bytes(
                    serialization.Encoding.Raw,
                    serialization.PrivateFormat.Raw,
                    serialization.NoEncryption(),
                )
            ),
            "public": raw(
                key.public_key().public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw
                )
            ),
            "short": secrets.token_hex(8),
            "roles": {
                r: {
                    "uuid": str(uuid.uuid4()),
                    "hy": secrets.token_urlsafe(32),
                    "tls": secrets.token_urlsafe(32),
                    "socks": secrets.token_urlsafe(32),
                    "token": secrets.token_urlsafe(32),
                }
                for r in ("windows", "ios")
            },
        }
        save(identity, state)

    def text(name):
        return (assets / name).read_text()

    cfg = yaml.safe_load(text("mihomo/config.example.yaml"))
    substitutions = {
        "REPLACE_WITH_PUBLIC_IPV4": c["public_ipv4"],
        "REPLACE_WITH_SUBSCRIPTION_DOMAIN": c["domain"],
        "REPLACE_WITH_REALITY_TARGET": c.get("reality_host", "www.microsoft.com"),
        "REPLACE_WITH_REALITY_HOSTNAME": c.get("reality_host", "www.microsoft.com"),
        "REPLACE_WITH_REALITY_PRIVATE_KEY": state["private"],
        "REPLACE_WITH_SHORT_ID": state["short"],
    }
    for r, prefix in (("windows", "WINDOWS"), ("ios", "IOS")):
        for field, suffix in (
            ("uuid", "UUID"),
            ("hy", "HYSTERIA2_PASSWORD"),
            ("tls", "ANYTLS_PASSWORD"),
            ("socks", "BACKEND_PASSWORD"),
        ):
            substitutions["REPLACE_WITH_" + prefix + "_" + suffix] = state["roles"][r][field]
    encoded = yaml.safe_dump(cfg)
    for k, v in substitutions.items():
        encoded = encoded.replace(k, v)
    save("/etc/mihomo/config.yaml", encoded)
    policy = yaml.safe_load(text("subscriptions/rules.yaml"))
    policy["base-url"] = "https://" + c["domain"] + ":9443"
    policy["variables"].update(server_ipv4=c["public_ipv4"], ssh_port=c["port"])
    save("/etc/vps-rules/rules.yaml", yaml.safe_dump(policy))
    links = {}
    for r, target, ip in (("windows", "win", "10.203.1.2"), ("ios", "Apple", "10.203.2.2")):
        user = state["roles"][r]
        backend = yaml.safe_load(text("tcpfp/backend.example.yaml"))
        backend["listeners"][0].update(
            listen=ip, users=[{"username": r, "password": user["socks"]}]
        )
        save("/etc/tcpfp/" + r + ".json", backend)
        profile = generate(
            dict(
                server=c["public_ipv4"],
                port=8443,
                uuid=user["uuid"],
                servername=c.get("reality_host", "www.microsoft.com"),
                public_key=state["public"],
                short_id=state["short"],
            ),
            target=target,
        )
        for kind, port, password in (
            ("hysteria2", 8443, user["hy"]),
            ("anytls", 9444, user["tls"]),
        ):
            profile["proxies"].append(
                dict(
                    name=target + (" · HY2" if kind == "hysteria2" else " · AnyTLS"),
                    type=kind,
                    server=c["public_ipv4"],
                    port=port,
                    password=password,
                    sni=c["domain"],
                    **{"skip-cert-verify": False},
                )
            )
        profile["proxy-groups"][0]["proxies"] = [n["name"] for n in profile["proxies"]]
        profile = configure(profile, policy)
        path = Path("/srv/vps-subscriptions") / (user["token"] + ".yaml")
        write_profile(path, profile)
        os.chown(path, 0, __import__("grp").getgrnam("caddy").gr_gid)
        path.chmod(0o640)
        links[target] = "https://" + c["domain"] + ":9443/s/" + path.name
    save("/etc/vps-ops/subscriptions.json", links)
    uid = str(__import__("pwd").getpwnam("mihomo").pw_uid)
    guard = text("mihomo/mihomo-guard.nft")
    for k, v in {
        "MIHOMO_UID": uid,
        "VPS_IPV4": c["public_ipv4"],
        "LISTEN_PORT": "8443",
        "SUBSCRIPTION_PORT": "9443",
    }.items():
        guard = guard.replace(k, v)
    save("/etc/nftables.d/mihomo-guard.nft", guard)
    caddy = (
        text("caddy/Caddyfile.example")
        .replace("REPLACE_WITH_SUBSCRIPTION_DOMAIN", c["domain"])
        .replace("REPLACE_WITH_DOMAIN", c["domain"])
    )
    save("/etc/caddy/Caddyfile", caddy, 0o644)
    cert = "/etc/caddy/certs/" + c["domain"] + "/current"
    save(
        "/etc/systemd/system/mihomo.service.d/50-tls.conf",
        text("mihomo/mihomo-tls.conf.in").replace("@CERT_DIRECTORY@", cert),
        0o644,
    )
    save(
        "/etc/mihomo-observed/collector.json",
        {
            "socket": "/var/lib/mihomo/controller/control.sock",
            "db": "/var/lib/mihomo-observed/usage.sqlite",
            "inbound": "vless-in",
            "instance": c["name"],
            "users": ["windows-test", "ios-test"],
            "interval": 5,
        },
    )

    import grp

    collector = Path("/etc/mihomo-observed/collector.json")
    os.chown(collector, 0, grp.getgrnam("mihomo").gr_gid)
    collector.chmod(0o640)
    frontend = Path("/etc/mihomo/config.yaml")
    os.chown(frontend, 0, grp.getgrnam("mihomo").gr_gid)
    frontend.chmod(0o640)


def main():
    c = json.loads(Path(sys.argv[1]).read_text())
    render(c, Path(sys.argv[2]))


if __name__ == "__main__":
    main()
