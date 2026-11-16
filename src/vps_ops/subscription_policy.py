#!/usr/bin/env python3
"""Apply the shared routing policy to a Mihomo subscription."""

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
        raise ValueError("Configuration must be an object")
    base = policy["base-url"]
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Rule distribution URL must use HTTPS")
    variables = {
        **policy.get("variables", {}),
        "subscription_host": parsed.hostname,
        "subscription_port": parsed.port or 443,
    }
    current_groups = profile["proxy-groups"]
    if not isinstance(current_groups, list):
        raise ValueError("Subscription has no proxy groups")
    primary = [
        group
        for group in current_groups
        if isinstance(group, dict) and group.get("name") == policy["node-group"]
    ]
    if len(primary) != 1:
        raise ValueError("Subscription must have exactly one node selector")

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
        raise ValueError("Subscription must not be a symbolic link")
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


def apply(policy_path, *, profile=None, directory=None, output=None):
    if bool(profile) == bool(directory) or (directory and output):
        raise ValueError("Choose either a subscription file or a directory")
    try:
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        if directory is not None:
            profiles = sorted(directory.glob("*.yaml"))
        elif profile is not None:
            profiles = [profile]
        else:
            raise ValueError("A subscription file or directory is required")
        if not profiles:
            raise ValueError("Subscription directory contains no configurations")
        updated = 0
        for path in profiles:
            original = yaml.safe_load(path.read_text(encoding="utf-8"))
            result = configure(original, policy)
            if output or result != original:
                write_profile(output or path, result)
                updated += 1
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        raise RuntimeError(
            "Subscription update failed; check the policy and profile files"
        ) from exc
    return {"processed": len(profiles), "updated": updated}
