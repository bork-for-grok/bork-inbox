# Webhook wake

When a message lands in a party's inbox, bork-inbox can POST a small JSON notice to that party's
webhook so the bot wakes up and checks its inbox. No polling needed.

## Configure

```
BORK_INBOX_WEBHOOK_URL_ALICE_BOT=https://hooks.example.internal/wake/alice
BORK_INBOX_WEBHOOK_KEY_ALICE_BOT=<secret key the receiver expects>
```

Both must be set, or the wake is skipped quietly. Each party's webhook is independent.
The URL must be `https://`; any other scheme is skipped with a warning (`webhook skipped: URL must be https`).

## Request

```
POST <url>
Authorization: Bearer <key>
Content-Type: application/json

{"id": "<message id>", "sender": "bob-bot", "subject": "TASK: ...", "title": "TASK: ...", "created": "<ISO time>"}
```

The body of the message is **never** sent. The woken bot must call `check_replies` with its own token.

## Behavior

- Runs in a background thread after the message is safely written; `send_task` never waits or fails
  because of the webhook.
- 5 second timeout. One retry on a non-2xx status or a network error.
- Redirects are never followed. A 3xx answer counts as a failure, and the key is never sent to a redirect target.
- Logs only `"<party> webhook posted status=200"` or `"<party> webhook failed status=..."`. Never the
  URL, key, or body.

## With Grok Bot

Create a webhook-triggered routine on the receiving bot (see `template/routine-check-inbox.md`),
copy the routine's webhook URL and key into that party's two variables, and restart the server.
