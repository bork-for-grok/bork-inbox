"""Minimal command-line client for bork-inbox (standard library only).

Reads the endpoint from BORK_INBOX_URL (default http://127.0.0.1:8800/mcp)
and the caller's token from BORK_INBOX_CLIENT_TOKEN. Never prints the token.

    python3 examples/client.py whoami
    python3 examples/client.py send bob-bot "TEST: ping" "ask: reply pong"
    python3 examples/client.py check
    python3 examples/client.py reply alice-bot <message-id> "REPLY: ping" "pong"
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import urllib.error
import urllib.request

URL = os.environ.get("BORK_INBOX_URL", "http://127.0.0.1:8800/mcp")


def call(name: str, arguments: dict) -> object:
    token = os.environ.get("BORK_INBOX_CLIENT_TOKEN", "")
    if not token:
        sys.exit("set BORK_INBOX_CLIENT_TOKEN")
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"HTTP {exc.code}")
    result = data.get("result") or {}
    text = "".join(b.get("text") or "" for b in result.get("content") or [] if b.get("type") == "text")
    if result.get("isError"):
        sys.exit("tool error: " + text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def main(argv: list[str]) -> None:
    if not argv:
        sys.exit(__doc__)
    cmd, rest = argv[0], argv[1:]
    if cmd == "whoami":
        out = call("whoami", {})
    elif cmd == "send" and len(rest) == 3:
        out = call("send_task", {"to": rest[0], "subject": rest[1], "body": rest[2],
                                 "client_id": "cli-" + secrets.token_hex(6)})
    elif cmd == "reply" and len(rest) == 4:
        out = call("send_task", {"to": rest[0], "in_reply_to": rest[1], "subject": rest[2], "body": rest[3],
                                 "client_id": "cli-" + secrets.token_hex(6)})
    elif cmd == "check":
        out = call("check_replies", {"limit": 20, "mark_read": True})
    else:
        sys.exit(__doc__)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
