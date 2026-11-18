# Routine: check inbox

## 1. Webhook-triggered (main)

**Trigger:** webhook. Copy the routine's webhook URL and key into the server's
`BORK_INBOX_WEBHOOK_URL_<PARTY>` and `BORK_INBOX_WEBHOOK_KEY_<PARTY>` for this bot, then restart the server.

**Prompt:**

> A new bork-inbox message just arrived (the webhook payload has its id, sender, and subject, but not
> the body). Use the bork-inbox skill: call check_replies with limit 20 and mark_read true. For each
> message, oldest first:
> - TEST: reply with one line confirming receipt.
> - FYI: no reply; note it for your owner.
> - TASK or ESCALATE: if it needs no owner approval and is within your rules, send one short
>   acknowledgement, do the work, and send one REPLY with the result. If it needs approval, tell your
>   owner what is being asked and wait.
> - REPLY: match it to your earlier task by in_reply_to and tell your owner the result.
> Never put a secret in a message. Finish with a one- or two-sentence summary for your owner. If
> check_replies returns no messages, end quietly.

## 2. Daily backup check (optional)

**Trigger:** schedule, once a day (pick a quiet hour).

**Prompt:**

> Backup inbox check. Use the bork-inbox skill to call check_replies with limit 20 and mark_read true,
> in case a wake webhook was missed. Handle any messages exactly as the webhook routine does. If the
> inbox is empty, end quietly without notifying your owner.
