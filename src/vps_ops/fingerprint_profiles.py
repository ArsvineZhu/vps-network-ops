"""Static TCP fingerprint profiles; these are independent of physical clients."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FingerprintProfile:
    key: str
    label: str
    namespace: str
    backend_address: str
    ttl: int


PROFILES = (
    FingerprintProfile("windows", "Windows", "tcpfp-windows-test", "10.203.1.2", 128),
    FingerprintProfile("ios", "Apple", "tcpfp-ios-test", "10.203.2.2", 64),
)
