#!/usr/bin/env python3
"""Fail closed before mihomo can auto-create a public controller directory."""

import os
import pathlib
import stat


def check():
    try:
        p = pathlib.Path("/var/lib/mihomo/controller")
        if p.is_symlink():
            raise ValueError()
        s = p.stat()
        if (
            not stat.S_ISDIR(s.st_mode)
            or s.st_uid != os.getuid()
            or stat.S_IMODE(s.st_mode) != 0o700
        ):
            raise ValueError()
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "Private controller directory is missing or unsafe; refusing startup"
        ) from exc
    return {"directory": str(p), "state": "pass"}
