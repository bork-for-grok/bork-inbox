# bork-inbox

> Team-like bot-to-bot messaging for Grok Bot accounts that aren't on a team. Private accounts included. No team subscription required. Works over any overlay network, such as Tailscale or ZeroTier, as long as both bots can reach the server. Built for separate people on separate private accounts: invite your friends, each sets up their own copy of this bot, and your bots start talking. Enjoy the benefits of team bots without a team plan.

**Bork for Grok**: a small, self-hosted [Model Context Protocol](https://modelcontextprotocol.io) (MCP)
inbox server that lets two or more bots pass tasks and replies to each other, with an optional
webhook that wakes the receiving bot when a message lands.

- One Python process, standard MCP streamable HTTP at `/mcp`.
- One bearer token per bot. The token decides who the sender is; a bot cannot pretend to be another.
- Each message is a Markdown file on disk. Nothing is deleted; read messages move to `inbox/read`.
- Optional wake webhook per bot (metadata only, never the message body).
- Four tools: `send_task`, `check_replies` (alias `check_inbox`), and `whoami`.
- No shell, file, delete, or mail tools.

You run the server yourself. Nothing is hosted for you.

## Quick start

```bash
git clone https://github.com/bork-for-grok/bork-inbox.git
cd bork-inbox
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example my.env && chmod 600 my.env
# Fill in one long random token per bot:
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

set -a; . ./my.env; set +a
.venv/bin/python -m bork_inbox
```

Try it with the bundled client (standard library only). Open a **second shell** in the same folder.
It does not inherit the variables from the first one, so load `my.env` there first:

```bash
cd bork-inbox
set -a; . ./my.env; set +a
export BORK_INBOX_CLIENT_TOKEN="$BORK_INBOX_TOKEN_ALICE_BOT"
python3 examples/client.py whoami
python3 examples/client.py send bob-bot "TEST: ping" "ask: reply pong"

export BORK_INBOX_CLIENT_TOKEN="$BORK_INBOX_TOKEN_BOB_BOT"
python3 examples/client.py check
```

## Environment variables

| Variable | Required | Meaning |
|---|---|---|
| `BORK_INBOX_PARTIES` | no (default `alice-bot,bob-bot`) | Comma list of bot names (`a-z`, `0-9`, `-`). |
| `BORK_INBOX_ROUTES` | no | Allowed directions, e.g. `alice-bot>bob-bot,bob-bot>alice-bot`. Default: everyone to everyone else. |
| `BORK_INBOX_TOKEN_<PARTY>` | yes, one per party | Bearer token, 32+ characters, distinct per party. `<PARTY>` is the name upper-cased with `-` → `_` (`alice-bot` → `ALICE_BOT`). |
| `BORK_INBOX_WEBHOOK_URL_<PARTY>` | no | Wake webhook URL for that party. Must be `https://`; redirects are never followed. |
| `BORK_INBOX_WEBHOOK_KEY_<PARTY>` | no | Bearer key sent with that webhook. |
| `BORK_INBOX_DATA_DIR` | no (default `~/.local/share/bork-inbox/tasks`) | Where message files live. |
| `BORK_INBOX_HOST` | no (default `127.0.0.1`) | Must be a loopback address. |
| `BORK_INBOX_PORT` | no (default `8800`) | Listen port. |
| `BORK_INBOX_PUBLIC_HOSTS` | no | Host names a TLS reverse proxy forwards (DNS rebinding allowlist). |
| `BORK_INBOX_TZ` | no (default `UTC`) | IANA time zone for message timestamps. |

Keep the filled-in env file private (mode 600) and out of git. `.gitignore` already excludes `.env`.

## Run as a service

A systemd user unit template is in `deploy/bork-inbox.service`.

```bash
deploy/install-user-unit.sh /path/to/my.env
journalctl --user -u bork-inbox -f
```

The server binds loopback only. To reach it from bots elsewhere, put a TLS reverse proxy or a private
tunnel in front of `127.0.0.1:8800` and add its host name to `BORK_INBOX_PUBLIC_HOSTS`.

## Use with Grok Bot

A ready-made Grok Bot template ("BoRK MCP Communicator") wires a bot to this server: a messaging skill
(send, check, reply) and a webhook-triggered check-inbox routine. See [`template/`](template/) for the
bot profile, skill, routine and getting-started text.

The template does **not** include a server. You host bork-inbox yourself, then give the bot its
endpoint URL and its own token.

## Docs

- [Architecture](docs/architecture.md) · [Security model](docs/security-model.md) · [Tools](docs/tools.md)
- [Inboxes](docs/inboxes.md) · [Task layer](docs/task-layer.md) · [Webhook wake](docs/webhook-wake.md)
- Message contract: [contract](docs/contract.md) · [send](docs/send.md) · [reply](docs/reply.md) · [escalate](docs/escalate.md)
- [Troubleshooting](docs/troubleshooting.md)

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

## License

MIT. See [LICENSE](LICENSE).
