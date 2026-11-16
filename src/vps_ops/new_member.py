#!/usr/bin/env python3
"""Offline member bundle. Does NOT register/revoke a server user or publish a subscription."""

import argparse
import json
import os
import uuid
from pathlib import Path

import yaml

from .clash_profile import generate
from .subscription_policy import configure


def main():
    p = argparse.ArgumentParser(description="生成新成员的客户端配置和待注册信息")
    p.add_argument(
        "public_template",
        type=Path,
        help="服务端公开信息的 JSON 文件：server、port、servername、public_key、short_id",
    )
    p.add_argument("member", help="成员标识")
    p.add_argument("output", type=Path, help="尚不存在的私有输出目录")
    p.add_argument("--policy", required=True, type=Path, help="共享路由策略文件")
    a = p.parse_args()
    try:
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", a.member):
            raise ValueError()
        d = json.loads(a.public_template.read_text(encoding="utf-8-sig"))
        if set(d) - {"server", "port", "servername", "public_key", "short_id", "fingerprint"}:
            raise ValueError()
        ident = str(uuid.uuid4())
        d.update(uuid=ident, name=a.member)
        profile = generate(d)
        profile = configure(profile, yaml.safe_load(a.policy.read_text(encoding="utf-8")))
        a.output.mkdir(mode=0o700, parents=False, exist_ok=False)
        # Ignore before writing credentials, including when output is inside a repository.
        fd = os.open(a.output / ".gitignore", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("*\n")
        files = {
            "profile.yaml": profile,
            "provider.yaml": {"proxies": profile["proxies"]},
            "server-user.pending.json": {
                "username": a.member,
                "uuid": ident,
                "flow": "xtls-rprx-vision",
            },
        }
        for name, data in files.items():
            fd = os.open(a.output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        p.exit(
            1,
            "生成失败。请检查模板格式、成员标识和输出目录；已创建的部分文件可能保留。\n",
        )
    print("已生成成员资料（待注册）。")
    print("下一步：将 server-user.pending.json 加入服务端入口，检查配置并重启服务。")
    if os.name == "nt":
        print("请检查输出目录的 Windows 访问权限（ACL）。")


if __name__ == "__main__":
    main()
