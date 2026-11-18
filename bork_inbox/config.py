"""Runtime settings for bork-inbox, read from environment variables only.

No secret is ever read from a hard-coded path. Tokens and webhook secrets come
from the process environment (for example a systemd EnvironmentFile with mode
600). This module never logs a secret value.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ENV_PREFIX = "BORK_INBOX_"
DEFAULT_PARTIES = ("alice-bot", "bob-bot")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8800
DEFAULT_TZ = "UTC"
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
MIN_TOKEN_LEN = 32

_PARTY_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


class ConfigError(Exception):
    """A configuration problem. The message never contains a secret."""


def env_suffix(party: str) -> str:
    """Map a party name to its env var suffix: alice-bot -> ALICE_BOT."""

    return party.upper().replace("-", "_")


def parties() -> tuple[str, ...]:
    raw = os.environ.get(ENV_PREFIX + "PARTIES", "")
    names = [part.strip() for part in raw.split(",") if part.strip()] or list(DEFAULT_PARTIES)
    seen: list[str] = []
    for name in names:
        if not _PARTY_RE.fullmatch(name):
            raise ConfigError(f"party name is not allowed: {name!r} (use a-z, 0-9 and -)")
        if name not in seen:
            seen.append(name)
    if len(seen) < 2:
        raise ConfigError("at least two parties are required")
    return tuple(seen)


def routes() -> set[tuple[str, str]]:
    """Allowed (sender, recipient) pairs.

    BORK_INBOX_ROUTES is an optional comma list such as
    ``alice-bot>bob-bot,bob-bot>alice-bot``. When it is unset, every party may
    send to every other party (never to itself).
    """

    names = parties()
    raw = os.environ.get(ENV_PREFIX + "ROUTES", "").strip()
    if not raw:
        return {(a, b) for a in names for b in names if a != b}
    found: set[tuple[str, str]] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        sender, sep, recipient = item.partition(">")
        sender, recipient = sender.strip(), recipient.strip()
        if sep != ">" or sender not in names or recipient not in names or sender == recipient:
            raise ConfigError(f"route is not allowed: {item!r}")
        found.add((sender, recipient))
    return found


def token_for(party: str) -> bytes:
    """Return the bearer token bytes for one party, or empty bytes."""

    value = os.environ.get(ENV_PREFIX + "TOKEN_" + env_suffix(party), "")
    data = value.strip().encode("utf-8", errors="replace")
    if not data or any(byte < 33 or byte > 126 for byte in data):
        return b""
    return data


def webhook_for(party: str) -> tuple[str, str] | None:
    """Return (url, key) for one party's wake webhook, or None when unset."""

    suffix = env_suffix(party)
    url = os.environ.get(ENV_PREFIX + "WEBHOOK_URL_" + suffix, "").strip()
    key = os.environ.get(ENV_PREFIX + "WEBHOOK_KEY_" + suffix, "").strip()
    if not url or not key:
        return None
    return url, key


def data_dir() -> Path:
    default = Path.home() / ".local" / "share" / "bork-inbox" / "tasks"
    raw = os.environ.get(ENV_PREFIX + "DATA_DIR", str(default))
    return Path(raw).expanduser().resolve()


def host() -> str:
    return os.environ.get(ENV_PREFIX + "HOST", DEFAULT_HOST).strip()


def port() -> int:
    raw = os.environ.get(ENV_PREFIX + "PORT", str(DEFAULT_PORT)).strip()
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(ENV_PREFIX + "PORT is not an integer") from None
    if value < 1 or value > 65535:
        raise ConfigError(ENV_PREFIX + "PORT is out of range")
    return value


def public_hosts() -> list[str]:
    """Extra Host names a TLS reverse proxy may forward (DNS rebinding allowlist)."""

    raw = os.environ.get(ENV_PREFIX + "PUBLIC_HOSTS", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def timezone_name() -> str:
    return os.environ.get(ENV_PREFIX + "TZ", DEFAULT_TZ).strip() or DEFAULT_TZ
