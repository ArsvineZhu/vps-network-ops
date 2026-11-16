"""Pinned downloads and installation of compiled fingerprint components."""

import hashlib
import shutil
import subprocess
import urllib.request
from pathlib import Path

GO = (
    "https://go.dev/dl/go1.27.4.linux-amd64.tar.gz",
    "7226736c2339719cda28fbf3a54d71aa63bcefe376e98cef00034268dab24840",
)
MIHOMO = (
    "https://github.com/MetaCubeX/mihomo/releases/download/v1.19.34/mihomo-linux-amd64-v1-v1.19.34.gz",
    "0c07340a01408d033dda4088ea2a4c1e4d82aeed7b2f84f7c046e93b6ff3290c",
)
ACME = (
    "https://github.com/acmesh-official/acme.sh/archive/refs/tags/3.1.6.tar.gz",
    "0d3f9000ac44a6331314742a88c475f79134e24fc991997883652adc59efc486",
)


def command(*args, **kw):
    subprocess.run(list(args), check=True, **kw)


def download(spec, path):
    with urllib.request.urlopen(spec[0], timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != spec[1]:
        raise RuntimeError("Download checksum mismatch")
    path.write_bytes(data)


def install(source, target, mode=0o644):
    import filecmp
    import os
    import tempfile

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and filecmp.cmp(source, target, shallow=False):
        target.chmod(mode)
        return
    fd, name = tempfile.mkstemp(dir=target.parent, prefix="." + target.name)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copyfile(source, temporary)
        temporary.chmod(mode)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
