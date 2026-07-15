from __future__ import annotations

import sys
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import common  # noqa: E402


class CommonSecurityTests(unittest.TestCase):
    def test_redacts_query_keys_and_telegram_bot_path(self) -> None:
        safe = common.redact_sensitive_url(
            "https://api.telegram.org/botBOT_SECRET/sendMessage?key=API_SECRET&other=ok"
        )

        self.assertNotIn("BOT_SECRET", safe)
        self.assertNotIn("API_SECRET", safe)
        self.assertIn("other=ok", safe)

    def test_http_error_does_not_expose_url_or_body_secrets(self) -> None:
        secret = "VERY_SECRET_VALUE"
        error = urllib.error.HTTPError(
            "https://example.test",
            503,
            "Unavailable",
            hdrs=None,
            fp=BytesIO(f"temporary failure for {secret}".encode("utf-8")),
        )

        with patch.dict(common.os.environ, {"GEMINI_API_KEY": secret}, clear=False), patch.object(
            common.urllib.request,
            "urlopen",
            side_effect=error,
        ):
            with self.assertRaises(RuntimeError) as raised:
                common.request_json(
                    "https://example.test/generate",
                    method="POST",
                    params={"key": secret},
                    payload={"hello": "world"},
                )

        message = str(raised.exception)
        self.assertNotIn(secret, message)
        self.assertIn("key=%2A%2A%2A", message)


if __name__ == "__main__":
    unittest.main()
