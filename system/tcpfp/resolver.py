"""Namespace resolver configuration owned by the fingerprint network."""

from pathlib import Path

NAMES = ("tcpfp-windows-test", "tcpfp-ios-test")
CONTENT = "nameserver 1.1.1.1\noptions timeout:2 attempts:2\n"


def repair(root=Path("/etc/netns")):
    for name in NAMES:
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "resolv.conf"
        if path.is_symlink():
            raise ValueError("Namespace resolver must be a regular file")
        path.write_text(CONTENT)
        path.chmod(0o644)
