"""Durable node identity and the registry of physical client devices."""

import json
import re
import secrets
import uuid
from pathlib import Path
from typing import NotRequired, TypedDict

from .files import save
from .fingerprint_profiles import PROFILES
from .wireguard import allocate_addresses, key_pair

IDENTITY = Path("/etc/vps-ops/identity.json")


class ClientDevice(TypedDict):
    id: str
    name: str
    platform: str
    active: bool
    token: NotRequired[str]
    profiles: NotRequired[dict]


def validate_device(name, platform):
    if (
        not isinstance(name, str)
        or not re.fullmatch(r"[^\x00-\x1f\x7f/\\]{1,64}", name)
        or name != name.strip()
    ):
        raise ValueError("Device name must contain 1 to 64 visible characters without slashes")
    if platform not in {profile.label for profile in PROFILES}:
        raise ValueError("Select Windows or Apple as the device's default platform")


def create():
    reality = key_pair()
    return {
        "reality": {
            key: value.replace("+", "-").replace("/", "_").rstrip("=")
            for key, value in reality.items()
        }
        | {"short": secrets.token_hex(8)},
        "backends": {profile.key: secrets.token_urlsafe(32) for profile in PROFILES},
        "wireguard": {"server": key_pair(), "next_peer": 2},
        "devices": {},
    }


def load():
    state = json.loads(IDENTITY.read_text(encoding="utf-8"))
    if (
        not isinstance(state, dict)
        or not {"reality", "backends", "wireguard", "devices"} <= state.keys()
    ):
        raise ValueError("Node identity does not contain a device registry")
    return state


def add(state, name, platform):
    validate_device(name, platform)
    if any(
        device["active"] and device["name"].casefold() == name.casefold()
        for device in state["devices"].values()
    ):
        raise ValueError("An active device already uses this name")
    identifier = str(uuid.uuid4())
    addresses = allocate_addresses(state)
    principals = {}
    for profile in PROFILES:
        principals[profile.key] = {
            "user": identifier + "." + profile.key,
            "uuid": str(uuid.uuid4()),
            "hy": secrets.token_urlsafe(32),
            "tls": secrets.token_urlsafe(32),
            "wireguard": key_pair() | {"address": addresses[profile.key]},
        }
    device = ClientDevice(
        id=identifier,
        name=name,
        platform=platform,
        active=True,
        token=secrets.token_urlsafe(32),
        profiles=principals,
    )
    state["devices"][identifier] = device
    return device


def find(state, identifier):
    if identifier in state["devices"]:
        return state["devices"][identifier]
    matches = [
        device
        for device in state["devices"].values()
        if device["active"] and device["name"].casefold() == identifier.casefold()
    ]
    if len(matches) != 1:
        raise ValueError("Device was not found; use device list to select its ID or active name")
    return matches[0]


def revoke(state, identifier):
    device = find(state, identifier)
    for field in ("token", "profiles"):
        device.pop(field, None)
    device["active"] = False
    return device


def public(device):
    return {key: device[key] for key in ("id", "name", "platform", "active")}


def user_labels(state):
    return {
        device["id"] + "." + profile.key: device["name"] + " · " + profile.label
        for device in state["devices"].values()
        for profile in PROFILES
    }


def ensure(config):
    if IDENTITY.exists():
        return load()
    state = create()
    first = config["device"]
    add(state, first["name"], first["platform"])
    save(IDENTITY, state)
    return state


def subscription_files(root, token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise ValueError("Invalid device subscription token")
    return {
        target: root / (token + ("." + target if target else "") + ".yaml")
        for target in ("", "Windows", "Apple")
    }
