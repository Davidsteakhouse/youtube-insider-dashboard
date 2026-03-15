from __future__ import annotations

import os
from typing import Any

from common import request_json


TELEGRAM_BASE = "https://api.telegram.org"


def send_digest_message(message: str) -> dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.")

    return request_json(
        f"{TELEGRAM_BASE}/bot{token}/sendMessage",
        method="POST",
        payload={
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": True
        },
        timeout=30
    )
