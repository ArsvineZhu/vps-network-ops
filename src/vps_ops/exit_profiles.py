"""Exit profiles, including the unmodified default path and optional TCP fingerprints."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExitProfile:
    key: str
    label: str
    namespace: str = ""
    backend_address: str = ""
    ttl: int = 0


PROFILES = (
    ExitProfile("default", "Default"),
    ExitProfile("windows", "Windows", "tcpfp-windows-test", "10.203.1.2", 128),
    ExitProfile("ios", "Apple", "tcpfp-ios-test", "10.203.2.2", 64),
)

FINGERPRINTS = tuple(profile for profile in PROFILES if profile.namespace)
