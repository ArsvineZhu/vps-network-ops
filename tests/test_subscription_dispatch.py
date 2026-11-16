"""Check the Caddy subscription matchers against actual client-style headers."""

import re
from pathlib import Path

import pytest


CADDYFILE = Path(__file__).parents[1] / "system/caddy/Caddyfile.example"


def matcher(name):
    text = CADDYFILE.read_text(encoding="utf-8")
    pattern = re.search(
        rf'^\\s*@{name} header_regexp User-Agent "([^"]+)"$',
        text,
        re.MULTILINE,
    )
    assert pattern is not None
    return re.compile(pattern.group(1))


@pytest.mark.parametrize(
    ("user_agent", "target"),
    [
        ("clash.meta/1.19.33 Clash/v1.0 Darwin/25.0.0 iPhone18,2", "Apple"),
        ("CFNetwork/1568 Darwin/25.0.0", "Apple"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0)", "Apple"),
        ("clash-verge/v2.5.10", "WIN"),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "WIN"),
        ("curl/8.11.0", None),
    ],
)
def test_subscription_platform_selection(user_agent, target):
    apple = bool(matcher("apple_subscription").search(user_agent))
    windows = bool(matcher("win_subscription").search(user_agent))
    assert not (apple and windows)
    assert ("Apple" if apple else "WIN" if windows else None) == target


def test_only_tokenized_auto_url_is_public():
    text = CADDYFILE.read_text(encoding="utf-8")
    pattern = re.search(r"path_regexp auto_subscription (\\S+)", text)
    assert pattern is not None
    route = re.compile(pattern.group(1))
    token = "A" * 43
    assert route.fullmatch(f"/s/auto/{token}.yaml")
    assert not route.fullmatch(f"/s/auto/{token}.Apple.yaml")
    assert not route.fullmatch(f"/s/auto/{token}.WIN.yaml")
    assert not route.fullmatch(f"/s/auto/{token}.yaml/anything")
