# Task layer

## Message file

Every message is `<id>.md`, where the id is a UTC stamp plus 6 hex characters
(for example `20990101T120000Z-a1b2c3`):

```markdown
---
id: "20990101T120000Z-a1b2c3"
timestamp: "2099-01-01T12:00:00+00:00"
from: "alice-bot"
to: "bob-bot"
subject: "TASK: summarize the weekly notes"
in_reply_to: null
client_id: "alice-0001"
---

ask: summarize the weekly notes in five bullets
in_reply_to: none
deadline: none
owner_decision_needed: no
```

## Guarantees

- **Atomic delivery.** Written to `tmp/`, then renamed into `inbox/unread/`.
- **Idempotent retries.** A repeated `client_id` from the same sender returns the original message,
  including one stuck in `tmp/` after a crash (it is promoted).
- **Serialized writers.** A process lock plus a `flock` on `.lock`.
- **No deletion.** Reading moves the file to `inbox/read/`. Symlinks and files outside the inbox
  directory are ignored.

## Limits

| Field | Limit |
|---|---|
| subject | 1–200 characters, one line; refused if it looks like a token (same check as the body) |
| body | 64 KiB UTF-8, no NUL bytes, no token-like lines |
| client_id | 1–200 of `A-Z a-z 0-9 . _ : -`, starts with a letter or digit; refused if it looks like a token (32+ letters, digits, `-` or `_` only) |
| check limit | 1–50 |
