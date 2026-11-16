"""Render registered-device authentication, subscriptions and service configuration."""

import copy
import json
from pathlib import Path

import yaml

from vps_ops import identity
from vps_ops.capabilities import Capabilities
from vps_ops.clash_profile import generate
from vps_ops.files import save
from vps_ops.fingerprint_profiles import PROFILES
from vps_ops.subscription_policy import configure
from vps_ops.wireguard import client_node, server_configuration


def profile_nodes(c, state, device):
    nodes = []
    for profile in PROFILES:
        principal = device["profiles"][profile.key]
        generated = generate(
            dict(
                server=c["public_ipv4"],
                port=8443,
                uuid=principal["uuid"],
                servername=c.get("reality_host", "www.microsoft.com"),
                public_key=state["reality"]["public"],
                short_id=state["reality"]["short"],
            ),
            target=profile.label,
        )
        if Capabilities.from_config(c).wireguard:
            nodes.append(client_node(state, device["id"], profile.key, c["public_ipv4"]))
        nodes.extend(generated["proxies"])
        for kind, port, field in (("hysteria2", 8443, "hy"), ("anytls", 9444, "tls")):
            nodes.append(
                dict(
                    name=profile.label + (" · HY2" if kind == "hysteria2" else " · AnyTLS"),
                    type=kind,
                    server=c["public_ipv4"],
                    port=port,
                    password=principal[field],
                    sni=c["domain"],
                    **{"skip-cert-verify": False},
                )
            )
    return nodes


def render(c, assets, state=None):
    import grp

    state = identity.ensure(c) if state is None else state
    plan = Capabilities.from_config(c)
    mihomo_group = grp.getgrnam("mihomo").gr_gid
    caddy_group = grp.getgrnam("caddy").gr_gid
    active = [device for device in state["devices"].values() if device["active"]]

    def text(name):
        return (assets / name).read_text(encoding="utf-8")

    if plan.wireguard:
        save("/etc/wireguard/vps-ops.conf", server_configuration(state))
    cfg = yaml.safe_load(text("mihomo/config.example.yaml"))
    substitutions = {
        "REPLACE_WITH_PUBLIC_IPV4": c["public_ipv4"],
        "REPLACE_WITH_SUBSCRIPTION_DOMAIN": c["domain"],
        "REPLACE_WITH_REALITY_TARGET": c.get("reality_host", "www.microsoft.com"),
        "REPLACE_WITH_REALITY_HOSTNAME": c.get("reality_host", "www.microsoft.com"),
        "REPLACE_WITH_REALITY_PRIVATE_KEY": state["reality"]["private"],
        "REPLACE_WITH_SHORT_ID": state["reality"]["short"],
    }
    for profile, prefix in (("windows", "WINDOWS"), ("ios", "IOS")):
        substitutions["REPLACE_WITH_" + prefix + "_BACKEND_PASSWORD"] = state["backends"][profile]
    encoded = yaml.safe_dump(cfg)
    for key, value in substitutions.items():
        encoded = encoded.replace(key, value)
    cfg = yaml.safe_load(encoded)
    for listener in cfg["listeners"]:
        if listener["type"] == "vless":
            listener["users"] = [
                {
                    "username": device["profiles"][profile.key]["user"],
                    "uuid": device["profiles"][profile.key]["uuid"],
                    "flow": "xtls-rprx-vision",
                }
                for device in active
                for profile in PROFILES
            ]
        else:
            field = "hy" if listener["type"] == "hysteria2" else "tls"
            listener["users"] = {
                device["profiles"][profile.key]["user"]: device["profiles"][profile.key][field]
                for device in active
                for profile in PROFILES
            }
    cfg["rules"] = [
        rule for rule in cfg["rules"] if "IN-USER," not in rule and rule != "MATCH,DIRECT"
    ]
    if not plan.fingerprint:
        cfg["proxies"] = []
    for device in active:
        for profile in PROFILES:
            user = device["profiles"][profile.key]["user"]
            cfg["rules"].extend(
                (
                    "AND,((IN-USER," + user + "),(NETWORK,UDP)),DIRECT",
                    "IN-USER," + user + "," + (profile.label if plan.fingerprint else "DIRECT"),
                )
            )
    cfg["rules"].append("MATCH,DIRECT")
    if not active:
        cfg["listeners"] = []
    save("/etc/mihomo/config.yaml", yaml.safe_dump(cfg), 0o640, group=mihomo_group)
    policy = yaml.safe_load(text("subscriptions/rules.yaml"))
    policy["base-url"] = "https://" + c["domain"] + ":9443"
    policy["variables"].update(server_ipv4=c["public_ipv4"], ssh_port=c["port"])
    save("/etc/vps-rules/rules.yaml", yaml.safe_dump(policy))
    for profile in PROFILES:
        if plan.fingerprint:
            backend = yaml.safe_load(text("tcpfp/backend.example.yaml"))
            backend["listeners"][0].update(
                listen=profile.backend_address,
                users=[{"username": profile.key, "password": state["backends"][profile.key]}],
            )
            save("/etc/tcpfp/" + profile.key + ".json", backend)
    root = Path("/srv/vps-subscriptions")
    root.mkdir(parents=True, exist_ok=True)
    index_path = Path("/etc/vps-ops/subscriptions.json")
    previous = json.loads(index_path.read_text()) if index_path.exists() else {}
    index = {}
    for device in active:
        nodes = profile_nodes(c, state, device)
        for target, path in identity.subscription_files(root, device["token"]).items():
            selected = target or device["platform"]
            source = next(profile for profile in PROFILES if profile.label == selected)
            principal = device["profiles"][source.key]
            profile = generate(
                dict(
                    server=c["public_ipv4"],
                    port=8443,
                    uuid=principal["uuid"],
                    servername=c.get("reality_host", "www.microsoft.com"),
                    public_key=state["reality"]["public"],
                    short_id=state["reality"]["short"],
                ),
                target=selected,
            )
            profile["proxies"] = copy.deepcopy(nodes)
            profile["proxy-groups"][0]["proxies"] = [node["name"] for node in nodes]
            profile = configure(profile, policy)
            primary = next(group for group in profile["proxy-groups"] if group["name"] == "Nodes")
            primary["default-selected"] = selected + (
                " · WireGuard" if plan.wireguard else " · VLESS"
            )
            save(
                path,
                json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
                0o640,
                group=caddy_group,
            )
        index[device["id"]] = {
            "name": device["name"],
            "platform": device["platform"],
            "url": "https://" + c["domain"] + ":9443/s/" + device["token"] + ".yaml",
        }
    for identifier, entry in previous.items():
        if identifier not in index:
            token = entry["url"].rsplit("/", 1)[-1].removesuffix(".yaml")
            for path in identity.subscription_files(root, token).values():
                path.unlink(missing_ok=True)
    save(index_path, index)
    uid = str(__import__("pwd").getpwnam("mihomo").pw_uid)
    guard = text("mihomo/mihomo-guard.nft")
    for key, value in {
        "MIHOMO_UID": uid,
        "VPS_IPV4": c["public_ipv4"],
        "LISTEN_PORT": "8443",
        "SUBSCRIPTION_PORT": "9443",
    }.items():
        guard = guard.replace(key, value)
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
    dependencies = Path("/etc/systemd/system/mihomo.service.d/45-fingerprint.conf")
    if plan.fingerprint:
        backends = " ".join(profile.namespace + ".service" for profile in PROFILES)
        save(dependencies, "[Unit]\nWants=" + backends + "\nAfter=" + backends + "\n", 0o644)
    else:
        dependencies.unlink(missing_ok=True)
    save(
        "/etc/mihomo-observed/collector.json",
        {
            "socket": "/var/lib/mihomo/controller/control.sock",
            "db": "/var/lib/mihomo-observed/usage.sqlite",
            "scope": "vless-in",
            "inbounds": ["vless-in", "hysteria2-in", "anytls-in"],
            "instance": c["name"],
            "users": [
                device["profiles"][profile.key]["user"] for device in active for profile in PROFILES
            ],
            "user_labels": identity.user_labels(state),
            "interval": 2,
            "wireguard_snapshot": "/run/vps-ops/wireguard-usage.json" if plan.wireguard else None,
        },
        0o640,
        group=mihomo_group,
    )
