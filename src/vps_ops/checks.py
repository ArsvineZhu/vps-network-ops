import json
import subprocess
from pathlib import Path

from .runtime import curl, run


def checks(c, section):
    results = []

    def check(name, fn):
        try:
            results.append(dict(name=name, state="通过", detail=str(fn())))
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
        files = list(Path(c["subscription_root"]).glob("*.yaml"))
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
    if section in ("all", "certificate"):

        def cert():
            from .certificate_check import check

            for p in Path("/run/credentials/mihomo.service").iterdir():
                if run(["openssl", "x509", "-in", str(p), "-noout", "-subject"]):
                    check(str(p), c["subscription_host"], 7)
                    return run(["openssl", "x509", "-in", str(p), "-noout", "-dates"])
            raise RuntimeError("证书不存在")

        check("证书", cert)
    if section in ("all", "tailscale"):

        def ts():
            state = json.loads(run(["tailscale", "status", "--json"]))
            if state["BackendState"] != "Running":
                raise RuntimeError("Tailscale " + state["BackendState"])
            return "在线"

        check("Tailscale", ts)
    return results
