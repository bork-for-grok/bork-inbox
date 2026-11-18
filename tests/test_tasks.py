from __future__ import annotations

import os
import unittest
from pathlib import Path

from bork_inbox import config, tasks, wake_webhook
from tests.helpers import EnvSandbox


class TaskLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = EnvSandbox()
        self.root = Path(self.env.tmp.name)

    def tearDown(self) -> None:
        wake_webhook.wait_pending()
        self.env.close()

    def test_layout_created_for_each_party(self) -> None:
        tasks.ensure_layout()
        for party in ("alice-bot", "bob-bot"):
            for sub in ("inbox/unread", "inbox/read", "tmp"):
                self.assertTrue((self.root / party / sub).is_dir())

    def test_send_and_check_round_trip(self) -> None:
        sent = tasks.send_task(role="alice-bot", to="bob-bot", subject="TASK: hello", body="ask: say hi")
        self.assertEqual(sent["to"], "bob-bot")
        self.assertTrue(sent["path"].startswith("bob-bot/inbox/unread/"))
        got = tasks.check_replies(role="bob-bot")
        self.assertEqual(len(got["messages"]), 1)
        msg = got["messages"][0]
        self.assertEqual(msg["from"], "alice-bot")
        self.assertEqual(msg["subject"], "TASK: hello")
        self.assertEqual(msg["body"], "ask: say hi")
        self.assertEqual(msg["location"], "read")
        self.assertEqual(tasks.check_replies(role="bob-bot")["messages"], [])
        self.assertTrue((self.root / "bob-bot" / "inbox" / "read" / f"{sent['id']}.md").is_file())

    def test_mark_read_false_keeps_unread(self) -> None:
        tasks.send_task(role="alice-bot", to="bob-bot", subject="FYI: x", body="note")
        first = tasks.check_replies(role="bob-bot", mark_read=False)
        self.assertEqual(first["messages"][0]["location"], "unread")
        self.assertEqual(len(tasks.check_replies(role="bob-bot")["messages"]), 1)

    def test_reply_threading(self) -> None:
        sent = tasks.send_task(role="alice-bot", to="bob-bot", subject="TASK: a", body="ask: a")
        tasks.send_task(role="bob-bot", to="alice-bot", subject="REPLY: a", body="done", in_reply_to=sent["id"])
        msg = tasks.check_replies(role="alice-bot")["messages"][0]
        self.assertEqual(msg["in_reply_to"], sent["id"])

    def test_client_id_is_idempotent(self) -> None:
        a = tasks.send_task(role="alice-bot", to="bob-bot", subject="TASK: a", body="b", client_id="alice-0001")
        b = tasks.send_task(role="alice-bot", to="bob-bot", subject="TASK: a", body="b", client_id="alice-0001")
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(tasks.check_replies(role="bob-bot")["messages"]), 1)

    def test_cannot_send_to_self_or_unknown(self) -> None:
        with self.assertRaises(tasks.TaskError):
            tasks.send_task(role="alice-bot", to="alice-bot", subject="x", body="y")
        with self.assertRaises(tasks.TaskError):
            tasks.send_task(role="alice-bot", to="mallory-bot", subject="x", body="y")
        with self.assertRaises(tasks.TaskError):
            tasks.send_task(role="mallory-bot", to="bob-bot", subject="x", body="y")

    def test_routes_restrict_directions(self) -> None:
        os.environ["BORK_INBOX_ROUTES"] = "alice-bot>bob-bot"
        tasks.send_task(role="alice-bot", to="bob-bot", subject="x", body="y")
        with self.assertRaises(tasks.TaskError):
            tasks.send_task(role="bob-bot", to="alice-bot", subject="x", body="y")

    def test_three_parties(self) -> None:
        os.environ["BORK_INBOX_PARTIES"] = "alice-bot,bob-bot,carol-bot"
        tasks.send_task(role="carol-bot", to="alice-bot", subject="x", body="y")
        self.assertEqual(tasks.check_replies(role="alice-bot")["messages"][0]["from"], "carol-bot")

    def test_validation(self) -> None:
        bad = [
            dict(subject="", body="y"),
            dict(subject="a\nb", body="y"),
            dict(subject="x" * 201, body="y"),
            dict(subject="x", body=""),
            dict(subject="x", body="a\x00b"),
            dict(subject="x", body="y" * (64 * 1024 + 1)),
            dict(subject="x", body="y", in_reply_to="not-an-id"),
            dict(subject="x", body="y", client_id="bad id with spaces"),
        ]
        for kwargs in bad:
            with self.subTest(kwargs=list(kwargs)):
                with self.assertRaises(tasks.TaskError):
                    tasks.send_task(role="alice-bot", to="bob-bot", **kwargs)
        for limit in (0, 51, True, "5"):
            with self.assertRaises(tasks.TaskError):
                tasks.check_replies(role="bob-bot", limit=limit)

    def test_token_like_body_refused(self) -> None:
        with self.assertRaises(tasks.TaskError):
            tasks.send_task(role="alice-bot", to="bob-bot", subject="x", body="A" * 40)
        with self.assertRaises(tasks.TaskError):
            tasks.send_task(role="alice-bot", to="bob-bot", subject="x", body="Bearer " + "b" * 40)
        live = self.env.bob
        with self.assertRaises(tasks.TaskError):
            tasks.send_task(
                role="alice-bot", to="bob-bot", subject="x", body=f"key is {live.decode()} ok", live_tokens=[live]
            )

    def test_token_like_subject_refused(self) -> None:
        with self.assertRaises(tasks.TaskError):
            tasks.send_task(role="alice-bot", to="bob-bot", subject="A" * 40, body="y")
        with self.assertRaises(tasks.TaskError):
            tasks.send_task(role="alice-bot", to="bob-bot", subject="Bearer " + "b" * 40, body="y")
        live = self.env.bob
        with self.assertRaises(tasks.TaskError):
            tasks.send_task(
                role="alice-bot", to="bob-bot", subject=f"TASK: {live.decode()}", body="y", live_tokens=[live]
            )
        self.assertEqual(tasks.check_replies(role="bob-bot")["messages"], [])
        ok = tasks.send_task(role="alice-bot", to="bob-bot", subject="TASK: a normal subject", body="y")
        self.assertIn("id", ok)

    def test_token_like_client_id_refused(self) -> None:
        with self.assertRaises(tasks.TaskError):
            tasks.send_task(role="alice-bot", to="bob-bot", subject="x", body="y", client_id="a" * 40)
        live = self.env.bob
        with self.assertRaises(tasks.TaskError):
            tasks.send_task(
                role="alice-bot", to="bob-bot", subject="x", body="y", client_id=live.decode(), live_tokens=[live]
            )
        self.assertEqual(tasks.check_replies(role="bob-bot")["messages"], [])
        ok = tasks.send_task(role="alice-bot", to="bob-bot", subject="x", body="y", client_id="alice-0002")
        self.assertIn("id", ok)

    def test_wake_payload_never_carries_unchecked_subject(self) -> None:
        os.environ["BORK_INBOX_WEBHOOK_URL_BOB_BOT"] = "https://hooks.example.internal/wake/bob"
        os.environ["BORK_INBOX_WEBHOOK_KEY_BOB_BOT"] = "placeholder-webhook-key"
        from unittest.mock import patch

        with patch("bork_inbox.wake_webhook.schedule_wake") as wake:
            with self.assertRaises(tasks.TaskError):
                tasks.send_task(role="alice-bot", to="bob-bot", subject="A" * 40, body="y")
            wake.assert_not_called()

    def test_symlinked_message_is_ignored(self) -> None:
        tasks.ensure_layout()
        outside = self.root / "outside.md"
        outside.write_text("---\nid: x\n---\n")
        (self.root / "bob-bot" / "inbox" / "unread" / "20990101T000000Z-abcdef.md").symlink_to(outside)
        self.assertEqual(tasks.check_replies(role="bob-bot")["messages"], [])

    def test_config_rejects_bad_party_names(self) -> None:
        os.environ["BORK_INBOX_PARTIES"] = "Alice Bot,bob-bot"
        with self.assertRaises(config.ConfigError):
            config.parties()
        os.environ["BORK_INBOX_PARTIES"] = "solo-bot"
        with self.assertRaises(config.ConfigError):
            config.parties()


if __name__ == "__main__":
    unittest.main()
