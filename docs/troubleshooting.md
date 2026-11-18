# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Server exits: `BORK_INBOX_TOKEN_... is missing or shorter than 32 characters` | Token not set in the environment | Check the `EnvironmentFile` path and the variable name suffix (`alice-bot` → `ALICE_BOT`). |
| Server exits: `every party needs a distinct token` | Two parties share a token | Generate a new token for one of them. |
| Server exits: `refusing to bind a non-loopback address` | `BORK_INBOX_HOST` is not loopback | Keep `127.0.0.1`; expose with a reverse proxy or tunnel. |
| HTTP 401 | Missing, wrong, or duplicated token | Send `Authorization: Bearer <token>` with exactly one party's token. |
| HTTP 421 or 403 through a proxy | Host header not allowlisted | Add the proxy host name to `BORK_INBOX_PUBLIC_HOSTS`. |
| Tool error `sender cannot send to that recipient` | Sending to yourself, or route not allowed | Check `whoami` and `BORK_INBOX_ROUTES`. |
| Tool error `body looks like a bearer token` | A line is a long bare token-like string, or a live token is in the body | Remove it. Never send secrets through the inbox. |
| Bot never wakes | Webhook URL or key unset, or receiver rejects the key | Check logs for `webhook skipped` / `webhook failed status=...`. |
| Duplicate messages | Retries without `client_id` | Always set a unique `client_id`. |

Logs: `journalctl --user -u bork-inbox -f`.
