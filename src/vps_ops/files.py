"""Atomic service and private configuration writes."""

import json
import os
from pathlib import Path


def save(path, data, mode=0o600, *, group: int | None = None):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    content = data if isinstance(data, str) else json.dumps(data, indent=2) + "\n"
    if p.exists() and p.read_bytes() == content.encode("utf-8"):
        if group is not None:
            os.chown(p, -1, group)
        p.chmod(mode)
        return
    import tempfile

    fd, name = tempfile.mkstemp(dir=p.parent, prefix="." + p.name)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            if group is not None:
                os.fchown(stream.fileno(), -1, group)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, p)
    finally:
        temporary.unlink(missing_ok=True)
