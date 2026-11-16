import json
import re
import subprocess
from pathlib import Path

from .runtime import curl, run


class CheckWarning(Exception):
    pass


def _checks(c, section):
    results = []

    def check(name, fn):
        try:
            results.append(dict(name=name, state="通过", detail=str(fn())))
        except CheckWarning as exc:
            results.append(dict(name=name, state="警告", detail=str(exc)))
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as e:
            results.append(
                dict(
                    name=name,
                    state="失败",
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
                        "解析成功"
                        if run(
                            ["ip", "netns", "exec", n, "getent", "ahostsv4", "www.cloudflare.com"]
                        )
                        else (_ for _ in ()).throw(RuntimeError("解析结果为空"))
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
                "Windows 捕获",
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
                    or "正常"
                ),
            )
            check(
                "iPhone eBPF",
                lambda: (
                    "已挂载"
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
                    else (_ for _ in ()).throw(RuntimeError("程序未挂载"))
                ),
            )
    if section in ("all", "proxy"):
        from .probes import frontend

        for protocol in ("vless", "hysteria2", "anytls"):
            check(protocol + " 入口认证", lambda protocol=protocol: frontend(c, protocol))
    if section in ("all", "subscription"):
        files = [
            p
            for p in Path(c["subscription_root"]).glob("*.yaml")
            if re.fullmatch(r"[A-Za-z0-9_-]{43}\\.yaml", p.name)
        ]
        if not files:
            check("订阅", lambda: (_ for _ in ()).throw(RuntimeError("订阅文件不存在")))
        for i, p in enumerate(files):
            host = c["subscription_host"]
            port = c["subscription_port"]
            check(
                f"订阅 {i + 1}",
                lambda f=p, host=host, port=port: curl(
                    f"https://{host}:{port}/s/{f.name}", resolve=f"{host}:{port}:127.0.0.1"
                ),
            )
        auto = Path("/etc/vps-ops/subscriptions.json")
        if auto.exists():
            url = json.loads(auto.read_text()).get("auto")
            if url:
                for role, agent in (
                    ("Apple", "clash.meta/1.19 Clash/v1 Darwin/25.0 iPhone18,2"),
                    ("WIN", "clash-verge/v2.5.10"),
                ):
                    check(
                        "自动订阅 " + role,
                        lambda u=url, a=agent: curl(
                            u,
                            resolve=f"{host}:{port}:127.0.0.1",
                            user_agent=a,
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

        check("证书", cert)
    if section in ("all", "tailscale"):

        def ts():
            state = json.loads(run(["tailscale", "status", "--json"]))
            if state["BackendState"] != "Running":
                raise RuntimeError("Tailscale " + state["BackendState"])
            if c.get("mode") in ("tailscale", "both") and not state.get("Self", {}).get(
                "ExitNodeOption", False
            ):
                raise CheckWarning("已登录，等待控制台批准出口节点")
            return "在线，出口能力已批准" if c.get("mode") else "在线"

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
            return [dict(name=section, state="跳过", detail="此节点未启用该能力")]
        return _checks(c, section)
    result = []
    for unit in c["services"]:
        try:
            run(["systemctl", "is-active", unit])
            result.append(dict(name=unit, state="通过", detail="active"))
        except (RuntimeError, OSError, subprocess.SubprocessError):
            result.append(dict(name=unit, state="失败", detail="服务未运行"))
    for part in ("dns", "proxy", "subscription", "certificate", "tailscale"):
        result.extend(checks(c, part))
    return result
