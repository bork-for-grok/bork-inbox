"""Shared test helpers. Tokens are generated at run time, never stored."""

from __future__ import annotations

import asyncio
import os
import secrets
import tempfile

ENV_KEYS = (
    "BORK_INBOX_PARTIES",
    "BORK_INBOX_ROUTES",
    "BORK_INBOX_DATA_DIR",
    "BORK_INBOX_TOKEN_ALICE_BOT",
    "BORK_INBOX_TOKEN_BOB_BOT",
    "BORK_INBOX_TOKEN_CAROL_BOT",
    "BORK_INBOX_WEBHOOK_URL_ALICE_BOT",
    "BORK_INBOX_WEBHOOK_KEY_ALICE_BOT",
    "BORK_INBOX_WEBHOOK_URL_BOB_BOT",
    "BORK_INBOX_WEBHOOK_KEY_BOB_BOT",
    "BORK_INBOX_HOST",
    "BORK_INBOX_PORT",
    "BORK_INBOX_PUBLIC_HOSTS",
    "BORK_INBOX_TZ",
)


class EnvSandbox:
    """Save and restore the BORK_INBOX_* environment around a test."""

    def __init__(self) -> None:
        self.saved = {key: os.environ.get(key) for key in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        self.tmp = tempfile.TemporaryDirectory(prefix="bork-inbox-test-")
        os.environ["BORK_INBOX_DATA_DIR"] = self.tmp.name
        self.alice = secrets.token_urlsafe(32).encode()
        self.bob = secrets.token_urlsafe(32).encode()
        os.environ["BORK_INBOX_TOKEN_ALICE_BOT"] = self.alice.decode()
        os.environ["BORK_INBOX_TOKEN_BOB_BOT"] = self.bob.decode()

    def close(self) -> None:
        self.tmp.cleanup()
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def enter_lifespan(app):
    shutdown = asyncio.Event()
    started = asyncio.Event()
    stopped = asyncio.Event()
    phase = {"n": 0}

    async def receive():
        if phase["n"] == 0:
            phase["n"] = 1
            return {"type": "lifespan.startup"}
        await shutdown.wait()
        return {"type": "lifespan.shutdown"}

    async def send(message):
        if message["type"].startswith("lifespan.startup"):
            started.set()
        elif message["type"].startswith("lifespan.shutdown"):
            stopped.set()

    task = asyncio.create_task(app({"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, receive, send))
    await asyncio.wait_for(started.wait(), timeout=10)
    return task, shutdown, stopped


async def exit_lifespan(handle) -> None:
    task, shutdown, stopped = handle
    shutdown.set()
    await asyncio.wait_for(stopped.wait(), timeout=10)
    await asyncio.wait_for(task, timeout=10)
