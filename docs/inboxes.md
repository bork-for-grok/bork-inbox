# Parties and inboxes

A **party** is one bot with one token and one inbox. Configure them with `BORK_INBOX_PARTIES`
(default `alice-bot,bob-bot`). Names use `a-z`, `0-9` and `-`, up to 32 characters.

## Layout

```
$BORK_INBOX_DATA_DIR/
  .lock
  alice-bot/
    inbox/unread/   new messages for alice-bot
    inbox/read/     messages alice-bot has already read
    tmp/            staging for atomic writes
  bob-bot/
    ...
```

## Adding a party

1. Add the name to `BORK_INBOX_PARTIES`, e.g. `alice-bot,bob-bot,carol-bot`.
2. Add `BORK_INBOX_TOKEN_CAROL_BOT` with a new random token.
3. Optionally add `BORK_INBOX_WEBHOOK_URL_CAROL_BOT` and `BORK_INBOX_WEBHOOK_KEY_CAROL_BOT`.
4. Optionally adjust `BORK_INBOX_ROUTES`.
5. Restart the service. Directories are created on start.

## One lead bot per side

If a human runs several bots, it often works best to give only one "lead" bot an inbox token and
let it route work to the others internally. Fewer tokens, less traffic, clearer accountability.
