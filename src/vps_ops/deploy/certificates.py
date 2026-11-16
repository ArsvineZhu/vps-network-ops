"""Shared ACME DNS-01 issuance, installation and renewal setup."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from .components import command
from .render import save


def configure(c, work):
    cert = Path("/etc/caddy/certs") / c["domain"] / "current"
    command(
        "install",
        "-d",
        "-m",
        "0750",
        "-o",
        "root",
        "-g",
        "caddy",
        "/etc/caddy/certs",
        str(cert.parent),
        str(cert),
    )
    command("chown", "root:caddy", str(cert.parent), str(cert))
    command("chmod", "0750", str(cert.parent), str(cert))
    hook = (
        "#!/bin/sh\nset -eu\nchown root:caddy "
        + str(cert)
        + "/*.pem\nchmod 640 "
        + str(cert)
        + "/*.pem\nif systemctl is-active --quiet caddy; then systemctl restart caddy; fi\nif systemctl is-active --quiet mihomo; then systemctl restart mihomo; fi\n"
    )
    save("/usr/local/lib/tcpfp/cert-refresh", hook, 0o700)
    credentials = json.loads((work / "dns.json").read_text())
    env = os.environ | credentials
    acme = ["/bin/sh", "/opt/acme.sh/acme.sh", "--home", "/root/.acme.sh"]

    def run_acme(*arguments):
        result = subprocess.run([*acme, *arguments], env=env, capture_output=True, text=True)
        if result.returncode:
            detail = "\n".join((result.stdout + "\n" + result.stderr).splitlines()[-20:])
            for value in credentials.values():
                if isinstance(value, str) and value:
                    detail = detail.replace(value, "[REDACTED]")
            raise RuntimeError(
                "Certificate operation failed (" + str(result.returncode) + "): \n" + detail
            )

    Path("/root/.acme.sh").mkdir(mode=0o700, exist_ok=True)
    # The pinned client installs its DNS plugins next to its managed home.
    shutil.copytree("/opt/acme.sh/dnsapi", "/root/.acme.sh/dnsapi", dirs_exist_ok=True)
    domain_dir = Path("/root/.acme.sh") / (c["domain"] + "_ecc")
    if not (domain_dir / (c["domain"] + ".cer")).exists():
        run_acme(
            "--register-account",
            "--server",
            "letsencrypt",
            "-m",
            c["email"],
        )
        run_acme(
            "--issue",
            "--server",
            "letsencrypt",
            "--dns",
            c["dns_plugin"],
            "-d",
            c["domain"],
            "--keylength",
            "ec-256",
        )
    elif subprocess.run(
        [
            "openssl",
            "x509",
            "-in",
            str(domain_dir / (c["domain"] + ".cer")),
            "-noout",
            "-checkend",
            "604800",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode:
        run_acme(
            "--renew",
            "--force",
            "--ecc",
            "-d",
            c["domain"],
        )
    run_acme(
        "--install-cert",
        "--ecc",
        "-d",
        c["domain"],
        "--key-file",
        str(cert / "key.pem"),
        "--fullchain-file",
        str(cert / "fullchain.pem"),
        "--reloadcmd",
        "/usr/local/lib/tcpfp/cert-refresh",
    )
    save(
        "/etc/cron.d/vps-acme",
        "23 3 * * * root /bin/sh /opt/acme.sh/acme.sh --cron --home /root/.acme.sh >/dev/null 2>&1\n",
        0o600,
    )

    (work / "dns.json").unlink(missing_ok=True)
