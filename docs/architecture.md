# Architecture

```
alice-bot ──HTTPS──▶ reverse proxy / tunnel ──▶ 127.0.0.1:8800/mcp  (bork-inbox)
bob-bot   ──HTTPS──▶        (optional)                    │
                                                          ├─ BearerGate: token → party
                                                          ├─ MCP tools: send_task, check_replies, whoami
                                                          ├─ tasks.py: Markdown files under BORK_INBOX_DATA_DIR
                                                          └─ wake_webhook.py: POST to the recipient's webhook
```

## Components

| Module | Job |
|---|---|
| `bork_inbox/server.py` | MCP streamable HTTP app (stateless, JSON responses), bearer gate, tool definitions, startup checks. |
| `bork_inbox/tasks.py` | File inboxes: atomic writes, idempotent `client_id`, read/unread moves, validation. |
| `bork_inbox/wake_webhook.py` | Best-effort wake POST in a background thread; one retry; never logs secrets. |
| `bork_inbox/config.py` | All settings from `BORK_INBOX_*` environment variables. |

## Request flow

1. A bot POSTs a JSON-RPC `tools/call` to `/mcp` with `Authorization: Bearer <its token>`.
2. `BearerGate` compares the token in constant time against every party's token. No match (or more
   than one) → HTTP 401. A match stamps the party name on the request.
3. The tool runs as that party. `send_task` writes `<recipient>/tmp/<id>.md`, then renames it into
   `<recipient>/inbox/unread/`. A file lock serializes writers.
4. After the write, `wake_webhook` POSTs `{id, sender, subject, title, created}` to the recipient's webhook,
   if one is configured. The recipient bot wakes and calls `check_replies`.

## Design choices

- **Files, not a database.** Easy to inspect, back up, and audit with standard tools.
- **Loopback bind only.** Exposure is an explicit decision you make with a proxy or tunnel.
- **Stateless HTTP.** Each request stands alone, so simple `curl` or `urllib` clients work.
- **Push wake, not polling.** Bots stay idle until a message arrives; a daily backup check is optional.
