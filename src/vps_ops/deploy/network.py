"""Install capability-owned forwarding units and queue profiles."""

from pathlib import Path

from vps_ops.capabilities import Capabilities
from vps_ops.files import save

from .components import command


def unit(name, body):
    save("/etc/systemd/system/" + name, body, 0o644)


def install(c):
    plan = Capabilities.from_config(c)
    if not (plan.mihomo and plan.fingerprint):
        Path("/etc/systemd/system/tcpfp-network.service.d/30-cleanup.conf").unlink(missing_ok=True)
    if not plan.wireguard:
        for path in (
            "/etc/systemd/system/wg-quick@vps-ops.service.d/30-forwarding.conf",
            "/etc/sysctl.d/90-vps-wireguard.conf",
            "/etc/tmpfiles.d/vps-wireguard.conf",
        ):
            Path(path).unlink(missing_ok=True)
    # The interpreter is the same installed environment as the public CLI.
    import sys

    python = sys.executable
    entry = python + " -m vps_ops.forwarding "
    if plan.mihomo and plan.fingerprint:
        unit(
            "tcpfp-network.service.d/30-cleanup.conf",
            "[Service]\nExecStop=" + entry + "local stop\n",
        )
    if plan.wireguard:
        save("/etc/sysctl.d/90-vps-wireguard.conf", "net.ipv4.ip_forward=1\n", 0o644)
        command("sysctl", "-w", "net.ipv4.ip_forward=1")
        unit(
            "vps-wireguard-network.service",
            f"""[Unit]
Description=WireGuard forwarding policy
After=network-online.target ufw.service
Wants=network-online.target
Before=wg-quick@vps-ops.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart={entry}wireguard start
ExecStop={entry}wireguard stop
[Install]
WantedBy=multi-user.target
""",
        )
        dependencies = "vps-wireguard-network.service"
        if plan.forwarding_fingerprint:
            dependencies += " vps-fingerprint-forward.service"
        unit(
            "wg-quick@vps-ops.service.d/30-forwarding.conf",
            "[Unit]\nRequires=" + dependencies + "\nAfter=" + dependencies + "\n",
        )
        unit(
            "vps-wireguard-usage.service",
            f"""[Unit]
Description=Private WireGuard usage snapshot
After=wg-quick@vps-ops.service
Requisite=wg-quick@vps-ops.service
[Service]
Type=oneshot
ExecStart={entry}snapshot
UMask=0027
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/run/vps-ops
CapabilityBoundingSet=CAP_NET_ADMIN CAP_CHOWN CAP_DAC_OVERRIDE
RestrictAddressFamilies=AF_UNIX AF_NETLINK
""",
        )
        unit(
            "vps-wireguard-usage.timer",
            """[Unit]
Description=Sample WireGuard counters
After=wg-quick@vps-ops.service
PartOf=wg-quick@vps-ops.service
[Timer]
OnBootSec=5s
OnUnitActiveSec=5s
AccuracySec=1s
[Install]
WantedBy=multi-user.target
""",
        )
        save("/etc/tmpfiles.d/vps-wireguard.conf", "d /run/vps-ops 0750 root mihomo -\n", 0o644)
        command("systemd-tmpfiles", "--create", "/etc/tmpfiles.d/vps-wireguard.conf")
    if plan.forwarding_fingerprint:
        for profile, role, queue in (("windows", "windows", 4947), ("ios", "apple", 4948)):
            path = "/etc/vps-ops/fingerprint-" + role + ".json"
            save(
                path,
                {
                    "interface": c["wan"],
                    "syn": {
                        "enabled": True,
                        "queue_num": queue,
                        "profile": profile,
                        "failure_mode": "strict",
                        "status_interval": "30s",
                    },
                },
            )
            unit(
                "vps-fingerprint-" + role + ".service",
                f"""[Unit]
Description=Forwarded {role} SYN queue
After=network-online.target
Wants=network-online.target
Before=vps-fingerprint-forward.service
[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/local/lib/tcpfp/mirage-syn run -c {path}
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
CapabilityBoundingSet=CAP_NET_ADMIN
RestrictAddressFamilies=AF_INET AF_UNIX AF_NETLINK
[Install]
WantedBy=multi-user.target
""",
            )
        unit(
            "vps-fingerprint-forward.service",
            f"""[Unit]
Description=Forwarded TCP fingerprint capture
Requires=vps-fingerprint-windows.service vps-fingerprint-apple.service
After=vps-fingerprint-windows.service vps-fingerprint-apple.service
BindsTo=vps-fingerprint-windows.service vps-fingerprint-apple.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart={entry}fingerprint start
ExecStop={entry}fingerprint stop
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
CapabilityBoundingSet=CAP_NET_ADMIN
RestrictAddressFamilies=AF_UNIX AF_NETLINK
[Install]
WantedBy=multi-user.target
""",
        )
