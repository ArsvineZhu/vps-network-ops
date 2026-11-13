#!/usr/bin/env python3
"""Fail closed before mihomo can auto-create a public controller directory."""

import os
import pathlib
import stat
import sys


def main():
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
    except Exception:
        print(
            "Private controller directory missing or unsafe; refusing mihomo startup.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
