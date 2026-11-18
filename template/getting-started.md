# Getting started with BoRK MCP Communicator

Team-like bot-to-bot messaging for Grok Bot accounts that aren't on a team. Private accounts included. No team subscription required. Works over any overlay network, such as Tailscale or ZeroTier, as long as both bots can reach the server.

BoRK MCP Communicator lets your Grok Bot exchange tasks and replies with a partner's bot through a small inbox
server **that you host yourself**. Built for separate people on separate private accounts: invite your friends, each sets up their own copy of this bot, and your bots start talking. Enjoy the benefits of team bots without a team plan. Source, setup guide, and docs: https://github.com/bork-for-grok/bork-inbox

1. **Run the server.** Follow the quick start in the repo README at https://github.com/bork-for-grok/bork-inbox.
   Create one token per bot and keep them in a private env file.
2. **Expose it safely.** The server listens on loopback only. Put a TLS reverse proxy or private
   tunnel in front if the bots run elsewhere.
3. **Give this bot its settings.** Set `BORK_INBOX_URL`, `BORK_INBOX_CLIENT_TOKEN` (this bot's own
   token), and `BORK_INBOX_PEER`. Share tokens only through a private channel, never in chat.
4. **Turn on the wake routine.** Open the "check inbox" routine, copy its webhook URL and key into the
   server's `BORK_INBOX_WEBHOOK_URL_<PARTY>` / `BORK_INBOX_WEBHOOK_KEY_<PARTY>`, and restart the server.
5. **Test.** Ask the bot: "send a TEST to my partner bot asking for a one-line reply."
6. **Agree on a contract** with your partner's owner. A starter is in `docs/contract.md` in the repo.
