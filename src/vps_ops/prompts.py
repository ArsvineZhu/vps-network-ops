"""Interactive input for deployment commands."""

import getpass


def deployment():
    def ask(label, default=""):
        return input(label + (" [" + default + "]" if default else "") + ": ").strip() or default

    values = {
        "mode": ask("Mode: tailscale / mihomo / both", "both"),
        "target": ask("SSH target (root@host or SSH alias)"),
        "port": int(ask("Initial SSH port", "22")),
        "name": ask("New node name", "vps-node"),
        "public_key": ask("Management public key file (.pub)"),
        "identity": ask("Private key file (security-key references are supported)"),
    }
    if values["mode"] != "tailscale":
        values.update(
            domain=ask("Subscription domain"),
            public_ipv4=ask("Node public IPv4"),
            email=ask("ACME contact email"),
            dns_provider=ask(
                "DNS: cloudflare / aliyun / dnspod / dnspod-token / dns_PLUGIN", "dnspod"
            ),
        )
        if values["dns_provider"].startswith("dns_"):
            values["dns_credentials"] = ask("Credential field names, separated by commas").split(
                ","
            )
    return values


def dns_secret(name):
    return getpass.getpass("DNS credential " + name + ": ")
