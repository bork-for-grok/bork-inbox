from __future__ import annotations

import json
import logging
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from bork_inbox import tasks, wake_webhook
from tests.helpers import EnvSandbox

FAKE_URL = "https://hooks.example.internal/wake/alice"
FAKE_KEY = "placeholder-webhook-key"


class _Resp:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class WakeWebhookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = EnvSandbox()

    def tearDown(self) -> None:
        wake_webhook.wait_pending()
        self.env.close()

    def _configure(self) -> None:
        os.environ["BORK_INBOX_WEBHOOK_URL_ALICE_BOT"] = FAKE_URL
        os.environ["BORK_INBOX_WEBHOOK_KEY_ALICE_BOT"] = FAKE_KEY

    def test_posts_metadata_only(self) -> None:
        self._configure()
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            return _Resp(200)

        with patch("bork_inbox.wake_webhook._open", fake_urlopen), self.assertLogs("bork_inbox", logging.INFO) as logs:
            sent = tasks.send_task(role="bob-bot", to="alice-bot", subject="TASK: wake", body="secret body text")
            wake_webhook.wait_pending()
        self.assertEqual(len(calls), 1)
        req = calls[0]
        self.assertEqual(req.full_url, FAKE_URL)
        self.assertEqual(req.get_header("Authorization"), "Bearer " + FAKE_KEY)
        payload = json.loads(req.data)
        self.assertEqual(payload["id"], sent["id"])
        self.assertEqual(payload["sender"], "bob-bot")
        self.assertEqual(payload["subject"], "TASK: wake")
        self.assertNotIn("body", payload)
        joined = "\n".join(logs.output)
        self.assertIn("alice-bot webhook posted status=200", joined)
        self.assertNotIn(FAKE_URL, joined)
        self.assertNotIn(FAKE_KEY, joined)
        self.assertNotIn("secret body text", joined)

    def test_retries_once_then_logs_failure(self) -> None:
        self._configure()
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request)
            raise urllib.error.HTTPError(FAKE_URL, 500, "boom", {}, None)

        with patch("bork_inbox.wake_webhook._open", fake_urlopen), self.assertLogs("bork_inbox", logging.WARNING) as logs:
            tasks.send_task(role="bob-bot", to="alice-bot", subject="x", body="y")
            wake_webhook.wait_pending()
        self.assertEqual(len(calls), 2)
        joined = "\n".join(logs.output)
        self.assertIn("alice-bot webhook failed status=500", joined)
        self.assertNotIn(FAKE_URL, joined)

    def test_network_error_never_raises_into_send(self) -> None:
        self._configure()

        def fake_urlopen(request, timeout):
            raise OSError("network down " + FAKE_URL)

        with patch("bork_inbox.wake_webhook._open", fake_urlopen), self.assertLogs("bork_inbox", logging.WARNING) as logs:
            sent = tasks.send_task(role="bob-bot", to="alice-bot", subject="x", body="y")
            wake_webhook.wait_pending()
        self.assertIn("id", sent)
        self.assertNotIn(FAKE_URL, "\n".join(logs.output))

    def test_unconfigured_recipient_is_quiet_skip(self) -> None:
        with patch("bork_inbox.wake_webhook._open") as mocked:
            tasks.send_task(role="alice-bot", to="bob-bot", subject="x", body="y")
            wake_webhook.wait_pending()
        mocked.assert_not_called()

    def test_half_configured_is_skip(self) -> None:
        os.environ["BORK_INBOX_WEBHOOK_URL_ALICE_BOT"] = FAKE_URL
        with patch("bork_inbox.wake_webhook._open") as mocked:
            tasks.send_task(role="bob-bot", to="alice-bot", subject="x", body="y")
            wake_webhook.wait_pending()
        mocked.assert_not_called()

    def test_http_url_is_rejected(self) -> None:
        os.environ["BORK_INBOX_WEBHOOK_URL_ALICE_BOT"] = "http://hooks.example.internal/wake/alice"
        os.environ["BORK_INBOX_WEBHOOK_KEY_ALICE_BOT"] = FAKE_KEY
        with patch("bork_inbox.wake_webhook._open") as mocked, self.assertLogs("bork_inbox", logging.WARNING) as logs:
            sent = tasks.send_task(role="bob-bot", to="alice-bot", subject="x", body="y")
            wake_webhook.wait_pending()
        mocked.assert_not_called()
        self.assertIn("id", sent)
        joined = "\n".join(logs.output)
        self.assertIn("alice-bot webhook skipped: URL must be https", joined)
        self.assertNotIn("hooks.example.internal", joined)
        self.assertNotIn(FAKE_KEY, joined)

    def test_non_http_schemes_are_rejected(self) -> None:
        for url in ("ftp://h.example/x", "file:///etc/passwd", "//h.example/x", "h.example/x", "https:///x", ""):
            with self.subTest(url=url):
                self.assertFalse(wake_webhook.is_https_url(url))
                self.assertIsNone(wake_webhook._post_once(url, FAKE_KEY, b"{}"))
        self.assertTrue(wake_webhook.is_https_url(FAKE_URL))

    def test_redirect_status_is_a_failure_and_not_followed(self) -> None:
        self._configure()
        calls = []

        def fake_open(request, timeout):
            calls.append(request)
            raise urllib.error.HTTPError(FAKE_URL, 302, "Found", {"Location": "https://other.example/x"}, None)

        with patch("bork_inbox.wake_webhook._open", fake_open), self.assertLogs("bork_inbox", logging.WARNING) as logs:
            tasks.send_task(role="bob-bot", to="alice-bot", subject="x", body="y")
            wake_webhook.wait_pending()
        self.assertTrue(all(c.full_url == FAKE_URL for c in calls))
        joined = "\n".join(logs.output)
        self.assertIn("alice-bot webhook failed status=302", joined)
        self.assertNotIn("posted", joined)
        self.assertNotIn(FAKE_KEY, joined)

    def test_redirect_handler_refuses_every_redirect(self) -> None:
        handler = wake_webhook._NoRedirect()
        req = urllib.request.Request(FAKE_URL, data=b"{}", method="POST", headers={"Authorization": "Bearer k"})
        for code in (301, 302, 303, 307, 308):
            self.assertIsNone(handler.redirect_request(req, None, code, "x", {}, "https://other.example/x"))

    def test_real_opener_does_not_follow_redirect_or_resend_key(self) -> None:
        seen: list[tuple[str, str | None]] = []
        target = HTTPServer(("127.0.0.1", 0), _recorder(seen, None))
        target_url = f"http://127.0.0.1:{target.server_address[1]}/landing"
        origin = HTTPServer(("127.0.0.1", 0), _recorder(seen, target_url))
        threads = [threading.Thread(target=srv.serve_forever, daemon=True) for srv in (origin, target)]
        for thread in threads:
            thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{origin.server_address[1]}/hook",
                data=b"{}",
                method="POST",
                headers={"Authorization": "Bearer " + FAKE_KEY},
            )
            # _open is the module's no-redirect opener. It is called directly here only because the
            # local test servers speak plain http; production URLs go through the https check.
            with self.assertRaises(urllib.error.HTTPError) as caught:
                wake_webhook._open(request, 5.0)
            self.assertEqual(caught.exception.code, 302)
            caught.exception.close()
        finally:
            for srv in (origin, target):
                srv.shutdown()
                srv.server_close()
        self.assertEqual([path for path, _auth in seen], ["/hook"])
        self.assertEqual(seen[0][1], "Bearer " + FAKE_KEY)


def _recorder(seen, redirect_to):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            seen.append((self.path, self.headers.get("Authorization")))
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if redirect_to:
                self.send_response(302)
                self.send_header("Location", redirect_to)
            else:
                self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    return Handler


if __name__ == "__main__":
    unittest.main()
