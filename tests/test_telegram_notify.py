from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import telegram_notify  # noqa: E402


class TelegramNotifyTests(unittest.TestCase):
    def test_blocks_messages_over_telegram_limit_before_network(self) -> None:
        with patch.dict(
            telegram_notify.os.environ,
            {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "chat"},
            clear=False,
        ), patch.object(telegram_notify, "request_json") as request_mock:
            with self.assertRaises(ValueError):
                telegram_notify.send_digest_message("x" * (telegram_notify.TELEGRAM_MESSAGE_LIMIT + 1))

        request_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
