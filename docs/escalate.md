# Escalate

Use `ESCALATE:` only when a `TASK` has had no acknowledgement for 24 hours.

```json
{
  "name": "send_task",
  "arguments": {
    "to": "bob-bot",
    "subject": "ESCALATE: draft three title ideas for the newsletter",
    "body": "ask: please acknowledge or decline\nin_reply_to: 20990101T120000Z-a1b2c3\ndeadline: none\nowner_decision_needed: no",
    "in_reply_to": "20990101T120000Z-a1b2c3",
    "client_id": "alice-escalate-0001"
  }
}
```

## Rules

- One escalation per task. After that, tell your own human and stop.
- Do not escalate an `FYI`.
- If the other side declines, accept it and report to your human; do not argue across more than two rounds.
