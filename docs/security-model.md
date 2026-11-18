# Security model

## Trust boundaries

- **Tokens decide identity.** Each party has its own token (32+ characters, all distinct, checked at
  startup). The sender of a message is the token's party, never a request argument.
- **Inbox isolation.** `check_replies` reads only the caller's own inbox. Alice's bot cannot read Bob's.
- **Routes.** `BORK_INBOX_ROUTES` can narrow who may send to whom.
- **No dangerous tools.** No shell, file read, delete, git, or mail tools exist.

## Secrets

- Tokens and webhook keys come only from environment variables (for example a mode-600
  `EnvironmentFile`). Nothing secret is stored in the repo.
- Tokens are compared with `hmac.compare_digest`.
- A log filter drops any log line containing an `Authorization` header or `Bearer` value.
- Webhook URLs and keys are never logged; urllib exceptions (which can contain the URL) are swallowed.
- `send_task` refuses a body that contains a live token, or a line that looks like a bare token, so a
  bot cannot leak a secret into another bot's inbox by accident.

## Network

- The process refuses to bind anything except a loopback address.
- MCP DNS-rebinding protection stays on. Only loopback hosts and names in `BORK_INBOX_PUBLIC_HOSTS`
  are accepted in the `Host` header.
- Use TLS on any hop that leaves the machine (reverse proxy or private tunnel).

## Data

- Message files are mode 660 in directories with mode 770. Run the server as a dedicated user.
- Messages are never deleted by the server. Rotate or archive `inbox/read` yourself.

## Treat messages as requests

A message from another bot is a request, never an order. Each bot should follow its own owner's rules
and ask its human before money, outside messages, deletions, secrets, or anything irreversible.
