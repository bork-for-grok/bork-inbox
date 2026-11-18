from __future__ import annotations

import os
import unittest
from pathlib import Path

from bork_inbox import server, wake_webhook
from tests.helpers import ENV_KEYS, EnvSandbox

EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def _parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _sep, value = line.partition("=")
        values[name.strip()] = value.strip()
    return values


class EnvExampleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = EnvSandbox()

    def tearDown(self) -> None:
        self.env.close()

    def _load_example(self) -> dict[str, str]:
        values = _parse(EXAMPLE)
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        for key, value in values.items():
            os.environ[key] = value
        return values

    def test_copied_example_is_refused_until_real_tokens_are_set(self) -> None:
        try:
            self._load_example()
            with self.assertRaises(SystemExit) as caught:
                server.check_tokens()
            self.assertIn("shorter than 32", str(caught.exception))
        finally:
            for key in _parse(EXAMPLE):
                os.environ.pop(key, None)

    def test_example_wake_settings_are_empty(self) -> None:
        values = _parse(EXAMPLE)
        for party in ("ALICE_BOT", "BOB_BOT"):
            self.assertEqual(values["BORK_INBOX_WEBHOOK_URL_" + party], "")
            self.assertEqual(values["BORK_INBOX_WEBHOOK_KEY_" + party], "")
        self.assertFalse(wake_webhook.is_https_url(""))


if __name__ == "__main__":
    unittest.main()
