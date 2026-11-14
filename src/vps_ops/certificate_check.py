#!/usr/bin/env python3
"""Read-only local leaf certificate check. Does not establish trust or inspect keys."""

import argparse
import datetime
import re
import subprocess
from pathlib import Path


def check(cert, hostname, min_days=7):
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", hostname):
        raise ValueError("主机名格式无效，请填写不含协议、端口或通配符的 DNS 名称")
    if min_days < 0 or min_days > 3650:
        raise ValueError("最短有效期必须为 0 至 3650 天")
    path = Path(cert)
    if not path.is_file():
        raise ValueError("证书文件不存在")

    def run(*args):
        return subprocess.run(
            ["openssl", "x509", "-in", str(path), "-noout", *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout

    # x509 reads the first certificate only; never claim fullchain trust from this.
    dates = dict(line.split("=", 1) for line in run("-dates").strip().splitlines())

    def parse(value):
        return datetime.datetime.strptime(value, "%b %d %H:%M:%S %Y GMT").replace(
            tzinfo=datetime.UTC
        )

    now = datetime.datetime.now(datetime.UTC)
    if parse(dates["notBefore"]) > now:
        raise ValueError("证书尚未生效")
    if parse(dates["notAfter"]) <= now + datetime.timedelta(days=min_days):
        raise ValueError("证书已过期或剩余有效期不足")
    # Older OpenSSL versions may exit successfully even for a hostname mismatch.
    # Require the explicit positive result instead of trusting the exit code alone.
    result = run("-checkhost", hostname).strip()
    if result != f"Hostname {hostname} does match certificate":
        raise ValueError("证书主机名不匹配，或无法识别 OpenSSL 的检查结果")


def main():
    parser = argparse.ArgumentParser(description="检查证书文件的主机名和有效期")
    parser.add_argument("--cert", required=True, help="证书文件路径")
    parser.add_argument("--hostname", required=True, help="需要匹配的 DNS 主机名")
    parser.add_argument("--min-days", type=int, default=7, help="最少剩余天数，默认 7 天")
    args = parser.parse_args()
    try:
        check(args.cert, args.hostname, args.min_days)
    except ValueError as exc:
        print(f"[失败] 证书：{exc}")
        return 1
    except (OSError, KeyError, subprocess.SubprocessError):
        print("[失败] 证书：无法读取或解析文件，请检查证书和 OpenSSL。")
        return 1
    print("[通过] 证书：主机名和有效期正常。")
    print("检查实际 HTTPS 服务，请运行 check subscription。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
