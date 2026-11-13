#!/usr/bin/env python3
"""Apply the shared routing policy to a Mihomo subscription."""

import argparse
import copy
import json
import os
import stat
import tempfile
from pathlib import Path
from string import Template
from urllib.parse import urljoin, urlsplit

import yaml


def configure(profile, policy):
    """Keep the profile's nodes and apply the configured groups and rules."""
    if not isinstance(profile, dict) or not isinstance(policy, dict):
        raise ValueError("配置必须是对象")
    base = policy["base-url"]
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("规则分发地址必须是 HTTPS 地址")
    variables = {
        **policy.get("variables", {}),
        "subscription_host": parsed.hostname,
        "subscription_port": parsed.port or 443,
    }
    current_groups = profile["proxy-groups"]
    if not isinstance(current_groups, list):
        raise ValueError("订阅缺少代理组")
    primary = [
        group
        for group in current_groups
        if isinstance(group, dict) and group.get("name") == policy["node-group"]
    ]
    if len(primary) != 1:
        raise ValueError("订阅中的节点选择组必须唯一")

    providers = copy.deepcopy(policy["rule-providers"])
    for provider in providers.values():
        if provider.get("type") == "http":
            provider["url"] = urljoin(base.rstrip("/") + "/", provider["url"])
    rules = [Template(rule).substitute(variables) for rule in policy["rules"]]
    result = copy.deepcopy(profile)
    hosts = {
        Template(name).substitute(variables): Template(address).substitute(variables)
        for name, address in policy.get("hosts", {}).items()
    }
    if hosts:
        result["hosts"] = hosts
    else:
        result.pop("hosts", None)
    result["proxy-groups"] = copy.deepcopy(primary + policy["proxy-groups"])
    result["rule-providers"] = providers
    result["rules"] = rules
    return result


def write_profile(path: Path, profile: dict) -> None:
    """Replace a profile atomically and retain its existing access permissions."""
    if path.is_symlink():
        raise ValueError("订阅不能是符号链接")
    previous = path.stat() if path.exists() else None
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(profile, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        if previous is not None:
            if hasattr(os, "chown"):
                os.chown(temporary, previous.st_uid, previous.st_gid)
            temporary.chmod(stat.S_IMODE(previous.st_mode))
        else:
            temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", nargs="?", type=Path, help="Mihomo 订阅配置")
    parser.add_argument("--directory", type=Path, help="订阅目录中的所有 YAML 配置")
    parser.add_argument("--policy", required=True, type=Path, help="共享规则配置")
    parser.add_argument("--output", type=Path, help="输出路径；省略时更新订阅")
    args = parser.parse_args()
    if bool(args.profile) == bool(args.directory) or (args.directory and args.output):
        parser.error("请选择一个订阅文件或订阅目录")
    try:
        policy = yaml.safe_load(args.policy.read_text(encoding="utf-8"))
        profiles = sorted(args.directory.glob("*.yaml")) if args.directory else [args.profile]
        if not profiles:
            raise ValueError("订阅目录中没有配置")
        for path in profiles:
            profile = yaml.safe_load(path.read_text(encoding="utf-8"))
            result = configure(profile, policy)
            if args.output or result != profile:
                write_profile(args.output or path, result)
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        parser.exit(1, f"更新订阅失败：{type(exc).__name__}\n")
    print("订阅已更新。")


if __name__ == "__main__":
    main()
