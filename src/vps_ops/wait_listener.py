#!/usr/bin/env python3
"""Linux: wait for a TCP listener owned by current systemd MainPID. No connections."""

import argparse
import re
import subprocess
import time


def main():
    p = argparse.ArgumentParser(description="等待指定服务的 TCP 监听就绪")
    p.add_argument("service", help="systemd 服务名称")
    p.add_argument("port", type=int, help="TCP 端口")
    p.add_argument("--seconds", type=float, default=10, help="等待时间，默认 10 秒")
    a = p.parse_args()
    if (
        not re.fullmatch(r"[A-Za-z0-9_.@-]+", a.service)
        or not 1 <= a.port <= 65535
        or not 0 < a.seconds <= 120
    ):
        p.error("服务名、端口或等待时间无效")
    end = time.monotonic() + a.seconds
    try:
        while time.monotonic() < end:
            pid = subprocess.check_output(
                ["systemctl", "show", a.service, "-p", "MainPID", "--value"], text=True, timeout=3
            ).strip()
            sockets = subprocess.check_output(
                ["ss", "-H", "-lntp", f"( sport = :{a.port} )"], text=True, timeout=3
            )
            if (
                pid.isdigit()
                and int(pid) > 0
                and re.search(r"pid=" + re.escape(pid) + r",", sockets)
            ):
                print(f"[通过] {a.service} 的 TCP {a.port} 已开始监听。")
                raise SystemExit(0)
            time.sleep(0.2)
    except (OSError, subprocess.SubprocessError):
        p.exit(2, "[失败] 无法读取服务或监听状态。\n")
    p.exit(1, "[失败] 等待超时，服务监听尚未就绪。\n")


if __name__ == "__main__":
    main()
