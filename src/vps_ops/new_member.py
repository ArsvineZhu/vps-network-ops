"""Generate private offline member materials without publishing or registration."""

import json
import os
import uuid

import yaml

from .clash_profile import generate
from .subscription_policy import configure


def create(public_template, member, output, policy):
    try:
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", member):
            raise ValueError()
        d = json.loads(public_template.read_text(encoding="utf-8-sig"))
        if set(d) - {"server", "port", "servername", "public_key", "short_id", "fingerprint"}:
            raise ValueError()
        ident = str(uuid.uuid4())
        d.update(uuid=ident, name=member)
        profile = generate(d)
        profile = configure(profile, yaml.safe_load(policy.read_text(encoding="utf-8")))
        output.mkdir(mode=0o700, parents=False, exist_ok=False)
        # Ignore before writing credentials, including when output is inside a repository.
        fd = os.open(output / ".gitignore", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("*\n")
        files = {
            "profile.yaml": profile,
            "provider.yaml": {"proxies": profile["proxies"]},
            "server-user.pending.json": {
                "username": member,
                "uuid": ident,
                "flow": "xtls-rprx-vision",
            },
        }
        for name, data in files.items():
            fd = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        raise RuntimeError(
            "Member generation failed; check the template, member name and output directory. Partial files may remain."
        ) from exc
    return {"output": str(output), "registration": "pending", "files": list(files)}
