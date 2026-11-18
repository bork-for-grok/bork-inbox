from __future__ import annotations

import json
import os
import unittest

import httpx2

from bork_inbox import server, wake_webhook
from tests.helpers import EnvSandbox, enter_lifespan, exit_lifespan


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.env = EnvSandbox()
        self.app = server.build_app()
        self.lifespan = await enter_lifespan(self.app)
        transport = httpx2.ASGITransport(app=self.app)
        self.client = httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8800")
        await self.client.__aenter__()

    async def asyncTearDown(self) -> None:
        wake_webhook.wait_pending()
        await self.client.__aexit__(None, None, None)
        await exit_lifespan(self.lifespan)
        self.env.close()

    def _no_token(self, text: str) -> None:
        for token in (self.env.alice, self.env.bob):
            self.assertNotIn(token.decode(), text)

    async def _rpc(self, token: bytes | None, method: str, params: dict, headers: dict | None = None):
        hdrs = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if token is not None:
            hdrs["Authorization"] = "Bearer " + token.decode()
        hdrs.update(headers or {})
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        resp = await self.client.post("/mcp", headers=hdrs, content=json.dumps(payload).encode())
        self._no_token(resp.text)
        return resp

    async def _tool(self, token: bytes, name: str, arguments: dict):
        resp = await self._rpc(token, "tools/call", {"name": name, "arguments": arguments})
        self.assertEqual(resp.status_code, 200, resp.text)
        result = resp.json().get("result") or {}
        is_error = bool(result.get("isError", result.get("is_error", False)))
        text = "".join(b.get("text") or "" for b in result.get("content") or [] if b.get("type") == "text")
        parsed = None
        if text and not is_error:
            parsed = json.loads(text)
        return is_error, text, parsed

    async def test_missing_or_wrong_token_is_401(self) -> None:
        resp = await self._rpc(None, "tools/list", {})
        self.assertEqual(resp.status_code, 401)
        resp = await self._rpc(b"x" * 40, "tools/list", {})
        self.assertEqual(resp.status_code, 401)

    async def test_tools_list(self) -> None:
        resp = await self._rpc(self.env.alice, "tools/list", {})
        self.assertEqual(resp.status_code, 200)
        names = sorted(t["name"] for t in resp.json()["result"]["tools"])
        self.assertEqual(names, ["check_inbox", "check_replies", "send_task", "whoami"])

    async def test_whoami(self) -> None:
        err, _text, parsed = await self._tool(self.env.bob, "whoami", {})
        self.assertFalse(err)
        self.assertEqual(parsed, {"party": "bob-bot", "can_send_to": ["alice-bot"]})

    async def test_send_and_check_over_http(self) -> None:
        err, _t, sent = await self._tool(
            self.env.alice, "send_task", {"to": "bob-bot", "subject": "TEST: ping", "body": "ask: reply pong"}
        )
        self.assertFalse(err)
        self.assertEqual(sent["to"], "bob-bot")
        # Alice cannot read Bob's inbox: she sees only her own (empty) inbox.
        err, _t, mine = await self._tool(self.env.alice, "check_inbox", {})
        self.assertFalse(err)
        self.assertEqual(mine["messages"], [])
        err, _t, got = await self._tool(self.env.bob, "check_replies", {"limit": 5})
        self.assertFalse(err)
        self.assertEqual(len(got["messages"]), 1)
        self.assertEqual(got["messages"][0]["from"], "alice-bot")
        err, _t, sent2 = await self._tool(
            self.env.bob,
            "send_task",
            {"to": "alice-bot", "subject": "REPLY: ping", "body": "pong", "in_reply_to": sent["id"]},
        )
        self.assertFalse(err)
        err, _t, back = await self._tool(self.env.alice, "check_replies", {})
        self.assertEqual(back["messages"][0]["in_reply_to"], sent["id"])

    async def test_sender_is_the_token_not_an_argument(self) -> None:
        err, text, _p = await self._tool(
            self.env.alice, "send_task", {"to": "alice-bot", "subject": "x", "body": "y"}
        )
        self.assertTrue(err)
        self.assertIn("cannot send", text)

    async def test_token_in_body_is_refused(self) -> None:
        err, text, _p = await self._tool(
            self.env.alice,
            "send_task",
            {"to": "bob-bot", "subject": "x", "body": "oops " + self.env.bob.decode() + " here"},
        )
        self.assertTrue(err)
        self.assertIn("bearer token", text)

    async def test_foreign_host_header_rejected(self) -> None:
        resp = await self._rpc(self.env.alice, "tools/list", {}, headers={"Host": "attacker.example"})
        self.assertNotEqual(resp.status_code, 200)

    async def test_public_host_allowlist(self) -> None:
        os.environ["BORK_INBOX_PUBLIC_HOSTS"] = "inbox.example.internal"
        app = server.build_app()
        handle = await enter_lifespan(app)
        try:
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="https://inbox.example.internal"
            ) as client:
                resp = await client.post(
                    "/mcp",
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                        "Authorization": "Bearer " + self.env.alice.decode(),
                    },
                    content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode(),
                )
            self.assertEqual(resp.status_code, 200, resp.text)
        finally:
            await exit_lifespan(handle)


class StartupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = EnvSandbox()

    def tearDown(self) -> None:
        self.env.close()

    def test_require_loopback(self) -> None:
        self.assertEqual(server.require_loopback("127.0.0.1"), "127.0.0.1")
        with self.assertRaises(SystemExit):
            server.require_loopback("0.0.0.0")

    def test_check_tokens(self) -> None:
        server.check_tokens()
        os.environ["BORK_INBOX_TOKEN_BOB_BOT"] = "short"
        with self.assertRaises(SystemExit):
            server.check_tokens()
        os.environ["BORK_INBOX_TOKEN_BOB_BOT"] = self.env.alice.decode()
        with self.assertRaises(SystemExit):
            server.check_tokens()

    def test_duplicate_token_matches_no_role(self) -> None:
        os.environ["BORK_INBOX_TOKEN_BOB_BOT"] = self.env.alice.decode()
        self.assertIsNone(server.match_role(self.env.alice))

    def test_redact_filter(self) -> None:
        import logging

        record = logging.LogRecord("x", logging.INFO, "f", 1, "Authorization: Bearer abc", (), None)
        server._RedactFilter().filter(record)
        self.assertNotIn("abc", record.getMessage())


if __name__ == "__main__":
    unittest.main()
