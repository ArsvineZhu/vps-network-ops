"""Resolve requested node capabilities into installation and runtime dependencies."""

from dataclasses import dataclass

MODES = ("tailscale", "mihomo", "both")
PROXY_SERVICES = ("mihomo", "mihomo-guard", "caddy", "mihomo-observed", "vps-rules.path")
FINGERPRINT_SERVICES = (
    "tcpfp-network",
    "tcpfp-windows-test",
    "tcpfp-ios-test",
    "tcpfp-syn-windows",
    "tcpfp-syn-capture-windows",
)


@dataclass(frozen=True)
class Capabilities:
    mode: str
    fingerprint: bool
    rtt: bool

    @classmethod
    def from_config(cls, config):
        mode = config.get("mode", "both")
        if mode not in MODES:
            raise ValueError("Select Tailscale, Clash, or both")
        features = config.get("features", {})
        if not isinstance(features, dict) or set(features) - {"fingerprint", "rtt"}:
            raise ValueError("Features must contain fingerprint and/or rtt")
        fingerprint = features.get("fingerprint", mode != "tailscale")
        rtt = features.get("rtt", False)
        if not isinstance(fingerprint, bool) or not isinstance(rtt, bool):
            raise ValueError("Feature values must be true or false")
        return cls(mode, fingerprint, rtt)

    @property
    def mihomo(self):
        return self.mode in ("mihomo", "both")

    @property
    def tailscale(self):
        return self.mode in ("tailscale", "both")

    @property
    def wireguard(self):
        return self.mihomo and self.rtt

    @property
    def forwarding_fingerprint(self):
        return self.fingerprint and (self.wireguard or self.tailscale)

    @property
    def services(self):
        result: list[str] = list(PROXY_SERVICES) if self.mihomo else []
        if self.mihomo and self.fingerprint:
            result.extend(FINGERPRINT_SERVICES)
        if self.tailscale:
            result.append("tailscaled")
        if self.wireguard:
            result.extend(
                ("vps-wireguard-network", "wg-quick@vps-ops", "vps-wireguard-usage.timer")
            )
        if self.forwarding_fingerprint:
            result.extend(
                ("vps-fingerprint-windows", "vps-fingerprint-apple", "vps-fingerprint-forward")
            )
        return result

    @property
    def ports(self):
        result = ["8443/tcp", "8443/udp", "9444/tcp", "9443/tcp"] if self.mihomo else []
        if self.tailscale:
            result.append("41641/udp")
        if self.wireguard:
            result.append("51820/udp")
        return result

    def installation(self):
        return {
            "mihomo": self.mihomo,
            "tailscale": self.tailscale,
            "fingerprint": self.fingerprint,
            "rtt": self.rtt,
            "wireguard": self.wireguard,
            "forwarding_fingerprint": self.forwarding_fingerprint,
            "local_fingerprint": self.mihomo and self.fingerprint,
            "services": self.services,
            "ports": self.ports,
        }
