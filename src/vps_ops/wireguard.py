"""WireGuard keys, peer addresses and configurations for registered devices."""

import base64
import ipaddress

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from .exit_profiles import PROFILES

INTERFACE = "vps-ops"
PORT = 51820
MTU = 1400
NETWORK = "10.220.0.0/15"
SERVER_ADDRESS = "10.220.0.1/15"
PROFILE_NETWORKS = {
    "default": "10.221.0.0/17",
    "windows": "10.220.0.0/17",
    "ios": "10.220.128.0/17",
}


def key_pair():
    key = X25519PrivateKey.generate()
    return {
        "private": base64.b64encode(
            key.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
        ).decode(),
        "public": base64.b64encode(
            key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        ).decode(),
    }


def allocate_addresses(state):
    index = state["wireguard"]["next_peer"]
    if index > 32766:
        raise ValueError("This node has exhausted its device address pool")
    state["wireguard"]["next_peer"] = index + 1
    return {
        key: str(ipaddress.ip_network(network).network_address + index)
        for key, network in PROFILE_NETWORKS.items()
    }


def peers(state):
    return [
        {
            "device_id": device["id"],
            "profile": profile.key,
            "user": principal["user"],
            "address": principal["wireguard"]["address"],
            "public": principal["wireguard"]["public"],
        }
        for device in state["devices"].values()
        if device["active"]
        for profile in PROFILES
        for principal in (device["profiles"][profile.key],)
    ]


def server_configuration(state):
    lines = [
        "[Interface]",
        "Address = " + SERVER_ADDRESS,
        "ListenPort = " + str(PORT),
        "PrivateKey = " + state["wireguard"]["server"]["private"],
        f"MTU = {MTU}",
    ]
    for peer in peers(state):
        lines.extend(
            (
                "",
                "[Peer]",
                "PublicKey = " + peer["public"],
                "AllowedIPs = " + peer["address"] + "/32",
            )
        )
    return "\n".join(lines) + "\n"


def client_node(state, device_id, profile_key, server):
    profile = next(profile for profile in PROFILES if profile.key == profile_key)
    peer = state["devices"][device_id]["profiles"][profile_key]["wireguard"]
    return {
        "name": profile.label + " · WireGuard",
        "type": "wireguard",
        "server": server,
        "port": PORT,
        "ip": peer["address"],
        "private-key": peer["private"],
        "public-key": state["wireguard"]["server"]["public"],
        "udp": True,
        "allowed-ips": ["0.0.0.0/0"],
        "mtu": MTU,
        "persistent-keepalive": 25,
    }
