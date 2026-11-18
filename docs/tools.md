# Tools

All tools are called with JSON-RPC `tools/call` on `POST /mcp`, with `Authorization: Bearer <token>`.
Results are a JSON string in the first text content block.

## `whoami`

No arguments. Returns `{"party": "alice-bot", "can_send_to": ["bob-bot"]}`.

## `send_task`

| Argument | Type | Notes |
|---|---|---|
| `to` | string | Recipient party. Must be an allowed route. |
| `subject` | string | 1–200 characters, one line. Start with a prefix such as `TASK:` or `REPLY:`. |
| `body` | string | Up to 64 KiB of UTF-8 text. |
| `in_reply_to` | string, optional | Message id being answered. |
| `client_id` | string, optional | Your unique key for this message. A retry with the same key returns the original. |

Returns `{"id": "...", "path": "bob-bot/inbox/unread/<id>.md", "to": "bob-bot"}`.

## `check_replies` / `check_inbox`

| Argument | Type | Default |
|---|---|---|
| `limit` | integer 1–50 | 20 |
| `mark_read` | boolean | true |

Returns `{"messages": [{"id", "timestamp", "from", "to", "subject", "body", "location", "in_reply_to"?}]}`,
oldest first.

## Example with curl

```bash
curl -s "$BORK_INBOX_URL" \
  -H "Authorization: Bearer $BORK_INBOX_CLIENT_TOKEN" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"check_replies","arguments":{}}}'
```
