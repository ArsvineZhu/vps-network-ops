import json
import subprocess
from pathlib import Path

from .runtime import curl, published_subscription, run


class CheckWarning(Exception):
    pass


def _checks(c, section):
    results = []

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
    if section in ("all", "dns", "proxy"):
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
    if section in ("all", "proxy"):
        from .probes import frontend

        for target in ("Windows", "Apple"):
            for protocol in ("vless", "hysteria2", "anytls"):
                check(
                    target + " " + protocol + " authentication",
                    lambda protocol=protocol, target=target: frontend(c, protocol, target),
                )
    if section in ("all", "subscription"):
        from .probes import subscription

        def delivery(role, agent):
            url, files = published_subscription(c)
            return subscription(c, url, files[role], user_agent=agent, target=role)

        for role, agent in (
            ("Apple", "clash.meta/1.19 Clash/v1 Darwin/25.0 iPhone18,2"),
            ("Windows", "clash-verge/v2.5.10"),
            ("", "curl/8.11.0"),
        ):
            check(
                "Subscription " + (role or "Unknown platform"),
                lambda role=role, agent=agent: delivery(role, agent),
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
            state = json.loads(run(["tailscale", "status", "--json"]))
            if state["BackendState"] != "Running":
                raise RuntimeError("Tailscale " + state["BackendState"])
            if c.get("mode") in ("tailscale", "both") and not state.get("Self", {}).get(
                "ExitNodeOption", False
            ):
                raise CheckWarning("Signed in; awaiting exit-node approval in the console")
            return "Online; exit-node capability approved" if c.get("mode") else "Online"

        check("Tailscale", ts)
    return results


def checks(c, section):
    mode = c.get("mode", "both")
    enabled = (
        ["tailscale"] if mode == "tailscale" else ["dns", "proxy", "subscription", "certificate"]
    )
    if mode == "both":
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
