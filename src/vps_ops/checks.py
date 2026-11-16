import json
import subprocess
from pathlib import Path

from .capabilities import Capabilities
from .runtime import curl, published_subscriptions, run


class CheckWarning(Exception):
    pass


def _checks(c, section):
    results = []
    plan = Capabilities.from_config(c)

    def check(name, fn):
        try:
            results.append(dict(name=name, state="pass", detail=str(fn())))
        except CheckWarning as exc:
            results.append(dict(name=name, state="warning", detail=str(exc)))
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as e:
            results.append(
                dict(
                    name=name,
                    state="fail",
                    detail=str(e) if isinstance(e, RuntimeError) else type(e).__name__,
                )
            )

    if section == "all":
        for service in c["services"]:
            check(service, lambda s=service: run(["systemctl", "is-active", s]))
    if plan.mihomo and plan.fingerprint and section in ("all", "dns", "proxy"):
        for role in ("windows", "ios"):
            ns = "tcpfp-" + role + "-test"
            if section in ("all", "dns"):
                check(
                    ns + " DNS",
                    lambda n=ns: (
                        "Resolved"
                        if run(
                            ["ip", "netns", "exec", n, "getent", "ahostsv4", "www.cloudflare.com"]
                        )
                        else (_ for _ in ()).throw(RuntimeError("DNS returned no addresses"))
                    ),
                )
                check(
                    ns + " HTTPS",
                    lambda n=ns: run(
                        [
                            "ip",
                            "netns",
                            "exec",
                            n,
                            "curl",
                            "-fsS",
                            "-o",
                            "/dev/null",
                            "--max-time",
                            "20",
                            "-w",
                            "%{http_code}",
                            c["probe_url"],
                        ]
                    ),
                )
            if section in ("all", "proxy"):

                def backend(r=role):
                    b = json.loads(
                        Path(f"/run/credentials/tcpfp-{r}-test.service/config.json").read_text()
                    )
                    listener = next(x for x in b["listeners"] if x["type"] == "socks")
                    user = listener["users"][0]
                    return curl(
                        c["probe_url"],
                        f"socks5h://{listener['listen']}:{listener['port']}",
                        user["username"] + ":" + user["password"],
                    )

                check(role + " SOCKS", backend)
        if section in ("all", "proxy"):
            check(
                "Windows SYN",
                lambda: run(
                    [
                        "ip",
                        "netns",
                        "exec",
                        "tcpfp-windows-test",
                        "/usr/local/lib/tcpfp/mirage-syn",
                        "check",
                        "-c",
                        "/etc/tcpfp/syn-windows.json",
                    ]
                ),
            )
            check(
                "Windows capture",
                lambda: (
                    run(
                        [
                            "ip",
                            "netns",
                            "exec",
                            "tcpfp-windows-test",
                            "python3",
                            "/usr/local/lib/tcpfp/syn_capture.py",
                            "check",
                            "--config",
                            "/etc/tcpfp/syn-windows.json",
                        ]
                    )
                    or "OK"
                ),
            )
            check(
                "iPhone eBPF",
                lambda: (
                    "Attached"
                    if "tc_ios"
                    in run(
                        [
                            "ip",
                            "netns",
                            "exec",
                            "tcpfp-ios-test",
                            "tc",
                            "filter",
                            "show",
                            "dev",
                            "e0",
                            "egress",
                        ]
                    )
                    else (_ for _ in ()).throw(RuntimeError("Program is not attached"))
                ),
            )
    if section in ("all", "proxy") and plan.forwarding_fingerprint:
        check(
            "Forwarding fingerprint",
            lambda: run(["nft", "list", "table", "ip", "vps_fingerprint_forward"]) and "Active",
        )
    if section in ("all", "proxy") and plan.mihomo:
        from .fingerprint_profiles import PROFILES
        from .probes import frontend, wireguard_peer

        for device_id, device in published_subscriptions(c).items():
            for profile in PROFILES:
                for protocol in ("vless", "hysteria2", "anytls"):
                    check(
                        device["name"] + " · " + profile.label + " " + protocol + " authentication",
                        lambda protocol=protocol, target=profile.label, device_id=device_id: (
                            frontend(c, protocol, target, device_id=device_id)
                        ),
                    )
            if plan.wireguard:

                def peer(device_id=device_id):
                    handshakes = [wireguard_peer(device_id, profile.key) for profile in PROFILES]
                    if not any(handshakes):
                        raise CheckWarning(
                            "Device peers configured; awaiting the first client connection"
                        )
                    return "Both profile peers configured; authenticated device handshake observed"

                check(device["name"] + " WireGuard peer configuration", peer)
    if section in ("all", "subscription"):
        from .probes import subscription

        for device_id, device in published_subscriptions(c).items():
            for role, agent in (
                ("Apple", "clash.meta/1.19 Clash/v1 Darwin/25.0 iPhone18,2"),
                ("Windows", "clash-verge/v2.5.10"),
                ("", "curl/8.11.0"),
            ):
                check(
                    "Subscription " + device["name"] + " · " + (role or "Saved default"),
                    lambda role=role, agent=agent, device_id=device_id, device=device: subscription(
                        c,
                        device_id,
                        device["url"],
                        device["files"][role],
                        user_agent=agent,
                        target=role,
                    ),
                )
    if section in ("all", "certificate"):

        def cert():
            from .certificate_check import check

            path = "/run/credentials/mihomo.service/tls-fullchain.pem"
            try:
                check(path, c["subscription_host"], 7)
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            return run(["openssl", "x509", "-in", path, "-noout", "-dates"])

        check("Certificate", cert)
    if section in ("all", "tailscale"):

        def ts():
            from .tailscale import status

            current = status()
            detail = current["detail"]
            if current["auth_url"]:
                detail += "\nSign in: " + current["auth_url"]
            if current["state"] == "stopped":
                raise RuntimeError(detail)
            if current["state"] != "ready":
                raise CheckWarning(detail)
            return detail

        check("Tailscale", ts)
        if plan.forwarding_fingerprint and not plan.mihomo:
            check(
                "Forwarding fingerprint",
                lambda: run(["nft", "list", "table", "ip", "vps_fingerprint_forward"]) and "Active",
            )
    return results


def checks(c, section):
    plan = Capabilities.from_config(c)
    enabled = []
    if plan.mihomo:
        enabled.extend(("proxy", "subscription", "certificate"))
        if plan.fingerprint:
            enabled.append("dns")
    if plan.tailscale:
        enabled.append("tailscale")
    if section != "all":
        if section not in enabled:
            return [
                dict(
                    name=section, state="skip", detail="This capability is not enabled on this node"
                )
            ]
        return _checks(c, section)
    result = []
    for unit in c["services"]:
        try:
            run(["systemctl", "is-active", unit])
            result.append(dict(name=unit, state="pass", detail="active"))
        except (RuntimeError, OSError, subprocess.SubprocessError):
            result.append(dict(name=unit, state="fail", detail="Service is not running"))
    for part in ("dns", "proxy", "subscription", "certificate", "tailscale"):
        result.extend(checks(c, part))
    return result
