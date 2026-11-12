#!/usr/bin/env python3
"""Read-only validation before Ansible is permitted to contact a target host.

The bundle is executable deployment input, not a sandbox. Only use bundles
generated from reviewed source. This check constrains paths and permissions;
it cannot establish that a root-owned service or script is benign.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys


MIHOMO_SHA256 = "817f50b3ac6a8b1c4360c5cf2961906057f3a883d970ebbcb0028a01632b620f"
ROOTS = ("/etc/vps-network", "/usr/local/lib/vps-network", "/srv/vps-network")
SERVICES = {
    "vps-network", "vps-tcpfp-windows", "vps-tcpfp-ios", "vps-guard",
    "vps-mihomo", "vps-usage", "caddy", "vps-cert-check",
}
USERS = {"root", "vps-mihomo", "vps-usage", "caddy"}
GROUPS = USERS | {"vps-controller", "vps-tls"}
PROTOCOLS = {"vless", "hysteria2", "anytls"}


class InvalidBundle(ValueError):
    """The input must not be deployed."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidBundle(message)


def safe_path(value: object, *, absolute: bool) -> PurePosixPath:
    require(isinstance(value, str) and bool(value), "A path is missing")
    require(not any(c in value for c in "\x00\n\r\\"), "Invalid path character")
    path = PurePosixPath(value)
    require(path.is_absolute() == absolute, "Incorrect absolute/relative path")
    require(str(path) == value, "Non-canonical path")
    require(all(p not in (".", "..") for p in value.split("/") if p), "Path traversal")
    return path


def regular_file(path: Path, base: Path | None = None) -> None:
    if base is not None:
        require(path.is_relative_to(base), "Source escapes bundle")
        parts = path.relative_to(base).parts
        cursor = base
        for part in parts:
            cursor /= part
            require(not cursor.is_symlink(), "Source symlinks are forbidden")
    else:
        require(not path.is_symlink(), "File symlinks are forbidden")
    require(path.is_file() and stat.S_ISREG(path.stat().st_mode), "Expected regular file")


def unit_name(name: object) -> str:
    require(isinstance(name, str), "Invalid service name")
    base = name.removesuffix(".service")
    if name == "vps-cert-check.timer":
        return name
    require(base in SERVICES, "Unsupported service")
    return base + ".service"


def valid_target(value: object, *, bbr_host: bool = False) -> PurePosixPath:
    path = safe_path(value, absolute=True)
    if str(path) == "/etc/sysctl.d/80-vps-network-bbr.conf":
        require(bbr_host, "Host BBR file requires explicit bbr_host")
        return path
    if any(path.is_relative_to(root) and str(path) != root for root in ROOTS):
        return path
    prefix = PurePosixPath("/etc/systemd/system")
    require(path.is_relative_to(prefix), "Target is outside deployment roots")
    rel = str(path.relative_to(prefix))
    allowed_units = {s + ".service" for s in SERVICES if s != "caddy"}
    allowed_units.add("vps-cert-check.timer")
    require(rel in allowed_units or rel == "caddy.service.d/vps-network.conf",
            "Unapproved systemd target")
    return path


def read_manifest(bundle: Path) -> dict:
    manifest_path = bundle / "manifest.json"
    regular_file(manifest_path, bundle)
    require(manifest_path.stat().st_size <= 2 * 1024 * 1024, "Manifest is too large")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise InvalidBundle("Invalid manifest JSON") from exc
    require(isinstance(manifest, dict) and type(manifest.get("schema")) is int
            and manifest["schema"] == 1, "Unsupported manifest schema")
    require(isinstance(manifest.get("files"), list) and 0 < len(manifest["files"]) <= 4096,
            "Manifest files must be a non-empty bounded list")
    require(type(manifest.get("tcpfp_enabled")) is bool, "tcpfp_enabled must be boolean")
    require(type(manifest.get("bbr_host", False)) is bool, "bbr_host must be boolean")
    for field in ("services", "prerequisites", "enabled_protocols"):
        require(isinstance(manifest.get(field), list)
                and all(isinstance(x, str) and x for x in manifest[field]),
                f"Invalid {field}")
        require(len(manifest[field]) == len(set(manifest[field])), f"Duplicate {field}")
    require(bool(manifest["enabled_protocols"])
            and set(manifest["enabled_protocols"]) <= PROTOCOLS, "Unsupported protocol")
    return manifest


def validate(bundle_path: str, binary_path: str | None = None) -> dict:
    bundle = Path(bundle_path).expanduser().absolute()
    require(bundle.is_dir() and not bundle.is_symlink(), "Bundle must be a real directory")
    require(bundle.resolve() == bundle, "Bundle ancestors must not be symlinks")
    require(bundle.stat().st_mode & 0o077 == 0, "Bundle directory must have mode 0700")
    manifest = read_manifest(bundle)
    files = []
    targets: set[str] = set()
    sources: set[str] = set()
    directories: dict[str, dict] = {
        "/usr/local/lib/vps-network": {"path": "/usr/local/lib/vps-network", "owner": "root",
                                       "group": "root", "mode": "0755"}}
    for index, item in enumerate(manifest["files"]):
        require(isinstance(item, dict), f"File entry {index} is not an object")
        require(set(item) == {"source", "target", "owner", "group", "mode", "sha256"},
                f"Unexpected file entry fields at {index}")
        source = safe_path(item["source"], absolute=False)
        require(source.parts[0] == "artifacts", "Sources must be under artifacts/")
        source_path = bundle / source
        regular_file(source_path, bundle)
        require(isinstance(item["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]),
                "Invalid artifact SHA256")
        require(hashlib.sha256(source_path.read_bytes()).hexdigest() == item["sha256"],
                "Artifact SHA256 mismatch")
        target = valid_target(item["target"], bbr_host=manifest.get("bbr_host", False))
        require(item["source"] not in sources and str(target) not in targets,
                "Duplicate source or target")
        sources.add(item["source"])
        targets.add(str(target))
        require(item["owner"] in USERS and item["group"] in GROUPS, "Unapproved file identity")
        require(isinstance(item["mode"], str)
                and re.fullmatch(r"0?[0-7]{3}", item["mode"]) is not None,
                "File mode must be an octal string")
        mode = int(item["mode"], 8)
        require(mode & 0o022 == 0, "Group/world-writable deployment file")
        if target.is_relative_to("/etc/vps-network"):
            require(mode & 0o137 == 0, "Private config must not be executable or world-readable")
            require(item["owner"] == "root", "Private config must be root-owned")
        if (target.is_relative_to("/usr/local/lib/vps-network")
                or target.is_relative_to("/etc/systemd/system")
                or target.is_relative_to("/etc/sysctl.d")):
            require(item["owner"] == "root" and item["group"] == "root",
                    "Executable and systemd trees must be root-owned")
        files.append({**item, "mode": f"{mode:04o}", "local_source": str(source_path)})
        parent = target.parent
        while str(parent) not in ("/etc", "/usr/local/lib", "/srv", "/etc/systemd/system", "/etc/sysctl.d", "/"):
            if parent.is_relative_to("/srv/vps-network"):
                group, directory_mode = "caddy", "0750"
            elif parent.is_relative_to("/etc/vps-network"):
                group, directory_mode = "vps-tls", "0750"
            else:
                group, directory_mode = "root", "0755"
            directories[str(parent)] = {"path": str(parent), "owner": "root",
                                        "group": group, "mode": directory_mode}
            parent = parent.parent
    require(not any(str(Path(t).parent) in targets for t in targets), "Target file/directory collision")
    for target in targets:
        require(not any(str(p) in targets for p in PurePosixPath(target).parents),
                "Target ancestor is another file")
    services = [unit_name(s) for s in manifest["services"]]
    require(len(set(services)) == len(services), "Duplicate normalized service")
    require("vps-mihomo.service" in services and "vps-guard.service" in services,
            "Mihomo and guard are mandatory")
    require("vps-cert-check.service" not in services, "Activate the certificate timer, not its one-shot service")
    for name in services:
        if name == "caddy.service":
            require("/etc/systemd/system/caddy.service.d/vps-network.conf" in targets,
                    "Caddy requires its explicit configuration override")
        else:
            require("/etc/systemd/system/" + name in targets, "Missing enabled service unit")
    for required in ("/etc/vps-network/mihomo.json", "/etc/vps-network/guard.nft",
                     "/usr/local/lib/vps-network/guard.py"):
        require(required in targets, "Missing required configuration")
    require(("vps-network.service" in services) == manifest["tcpfp_enabled"],
            "Network service must match tcpfp_enabled")
    if not manifest["tcpfp_enabled"]:
        require(not any(s.startswith("vps-tcpfp-") for s in services),
                "TCP fingerprint backend enabled without network setup")
    else:
        require(any(s.startswith("vps-tcpfp-") for s in services), "TCP fingerprint backend missing")
        for required in ("/usr/local/lib/vps-network/network.py", "/etc/vps-network/network.json",
                         "/etc/vps-network/forward.nft", "/usr/local/lib/vps-network/ebpf/Makefile",
                         "/usr/local/lib/vps-network/ebpf/syn_rewrite.c"):
            require(required in targets, "TCP fingerprint runtime artifact missing")
        for profile in ("windows", "ios"):
            if f"vps-tcpfp-{profile}.service" in services:
                require(f"/etc/vps-network/{profile}.json" in targets
                        and f"/etc/vps-network/namespace-{profile}.nft" in targets,
                        "TCP fingerprint backend configuration missing")
    cert_path = "/etc/vps-network/tls/fullchain.pem"
    key_path = "/etc/vps-network/tls/privkey.pem"
    require((cert_path in targets) == (key_path in targets), "TLS certificate/key must be a pair")
    if ("caddy.service" in services or "vps-cert-check.timer" in services
            or set(manifest["enabled_protocols"]) & {"hysteria2", "anytls"}):
        require(cert_path in targets and key_path in targets, "TLS artifacts required before service start")
    if "vps-cert-check.timer" in services:
        require("/etc/systemd/system/vps-cert-check.service" in targets, "Certificate timer service missing")
        require("/usr/local/lib/vps-network/certificate.py" in targets, "Certificate checker missing")
    if "caddy.service" in services:
        require("/etc/vps-network/Caddyfile" in targets, "Caddy configuration missing")
    if "vps-usage.service" in services:
        for required in ("/etc/vps-network/collector.json", "/usr/local/lib/vps-network/usage.py",
                         "/usr/local/lib/vps-network/usage_daemon.py", "/usr/local/lib/vps-network/observed_usage.py"):
            require(required in targets, "Private collector runtime artifact missing")
    require(("/etc/sysctl.d/80-vps-network-bbr.conf" in targets) == manifest.get("bbr_host", False),
            "Host BBR artifact must match explicit bbr_host")
    result = {**manifest, "files": files, "services": services,
              "directories": sorted(directories.values(), key=lambda x: (x["path"].count("/"), x["path"]))}
    if binary_path is not None:
        binary = Path(binary_path).expanduser().absolute()
        regular_file(binary)
        require(binary.resolve() == binary, "Binary ancestors must not be symlinks")
        digest = hashlib.sha256()
        with binary.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        require(digest.hexdigest() == MIHOMO_SHA256, "Mihomo v1.19.33 binary SHA256 mismatch")
        result["mihomo_binary"] = str(binary)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", help="Private generated bundle directory (0700)")
    parser.add_argument("--mihomo-binary", help="Optional decompressed pinned local Linux amd64 binary")
    parser.add_argument("--json", action="store_true", help="Print validated manifest (treat as private)")
    args = parser.parse_args()
    try:
        result = validate(args.bundle, args.mihomo_binary)
    except (InvalidBundle, OSError) as exc:
        print(f"Bundle rejected: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"Bundle valid: {len(result['files'])} files; protocols: {', '.join(result['enabled_protocols'])}; "
              f"TCP fingerprint backends: {result['tcpfp_enabled']}. No host contacted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
