"""Interactive input for node capabilities and deployment credentials."""

import getpass

from .capabilities import MODES, Capabilities


def deployment(existing=None):
    previous = existing or {}
    values = dict(previous)

    def ask(label, default="", *, optional=False):
        value = input(label + (" [" + str(default) + "]" if default != "" else "") + ": ").strip()
        return "" if optional and value == "-" else value or default

    def choose(label, choices, default):
        while True:
            value = ask(label, default).lower()
            if value in choices:
                return value
            print("Choose " + ", ".join(choices) + ".")

    def yes(label, default=True):
        return choose(label + " (yes/no)", ("yes", "no", "y", "n"), "yes" if default else "no") in (
            "yes",
            "y",
        )

    print(
        "Update the saved node choices."
        if previous
        else "Set up an Ubuntu 24.04 AMD64 node. Keep your provider console available."
    )
    access = choose(
        "Access: 1 Tailscale / 2 Clash (Mihomo) / 3 Both",
        ("1", "2", "3"),
        str(MODES.index(previous.get("mode", "mihomo")) + 1),
    )
    values["mode"] = MODES[int(access) - 1]
    selected = Capabilities.from_config(values)
    prior = Capabilities.from_config(previous) if previous else None
    fingerprint = yes(
        "Normalize IPv4 TCP fingerprints for Windows and Apple devices",
        prior.fingerprint if prior else True,
    )
    rtt = prior.rtt if prior else False
    if selected.mihomo:
        rtt = yes(
            "Enable the full device-to-destination TCP path (RTT) for Clash",
            prior.rtt if prior else True,
        )
        if rtt:
            print(
                "WireGuard will be selected by default. VLESS, Hysteria2 and AnyTLS remain available; their separate TCP connections measure latency in segments."
            )
    if selected.tailscale:
        print("Tailscale already preserves TCP latency through native forwarding.")
    values["features"] = {"fingerprint": fingerprint, "rtt": rtt}
    details = not previous or yes("Change SSH, node, domain or DNS settings", False)
    if details:
        print("Press Enter to keep a saved value; use - to clear an optional file path.")
        while True:
            port = ask("Initial SSH port", previous.get("port", 22))
            try:
                if 1 <= int(port) <= 65535:
                    break
            except ValueError:
                pass
            print("Enter a port between 1 and 65535.")
        values.update(
            target=ask("SSH target (root@host or SSH alias)", previous.get("target", "")),
            port=int(port),
            name=ask("Node name", previous.get("name", "vps-node")),
            public_key=ask("Management public key file (.pub)", previous.get("public_key", "")),
            identity=ask(
                "Private key file (empty uses OpenSSH configuration)",
                previous.get("identity", ""),
                optional=True,
            ),
        )
    if selected.mihomo and (
        details
        or not all(
            values.get(field) for field in ("domain", "public_ipv4", "email", "dns_provider")
        )
    ):
        values.update(
            domain=ask(
                "Subscription domain (A record must point to this node)", previous.get("domain", "")
            ),
            public_ipv4=ask("Node public IPv4", previous.get("public_ipv4", "")),
            email=ask("Certificate contact email", previous.get("email", "")),
            dns_provider=ask(
                "DNS: cloudflare / aliyun / dnspod / dnspod-token / dns_PLUGIN",
                previous.get("dns_provider", "dnspod"),
            ),
        )
        if values["dns_provider"].startswith("dns_"):
            values["dns_credentials"] = [
                name.strip()
                for name in ask(
                    "Credential field names, separated by commas",
                    ",".join(previous.get("dns_credentials", [])),
                ).split(",")
            ]
        credentials = ask(
            "DNS credential JSON file (empty uses hidden prompts during apply)",
            previous.get("credential_file", ""),
            optional=True,
        )
        if credentials:
            values["credential_file"] = credentials
        else:
            values.pop("credential_file", None)
    if selected.mihomo and not values.get("device"):
        print(
            "Register the first physical device. Other devices receive separate subscriptions with device add."
        )
        values["device"] = client_device()
    return values


def client_device(name=None, platform=None):
    from .identity import validate_device

    name = name or input("Physical device name [My device]: ").strip() or "My device"
    if platform is None:
        while True:
            choice = input("Default platform: 1 Windows / 2 Apple [1]: ").strip() or "1"
            if choice in ("1", "2"):
                platform = "Windows" if choice == "1" else "Apple"
                break
            print("Choose 1 or 2.")
    validate_device(name, platform)
    return {"name": name, "platform": platform}


def dns_secret(name):
    return getpass.getpass("DNS credential " + name + ": ")
