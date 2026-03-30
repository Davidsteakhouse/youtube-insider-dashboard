from __future__ import annotations

import json
from pathlib import Path

from common import DATA_DIR, ROOT_DIR, read_json


BUNDLE_PATH = ROOT_DIR / "data_bundle.js"


def build_bundle_payload() -> dict:
    return {
        "watchlist": read_json(DATA_DIR / "watchlist.json", {"channels": []}),
        "videos": read_json(DATA_DIR / "videos.json", {"videos": []}),
        "digest": read_json(DATA_DIR / "digest.json", {}),
        "my_channel": read_json(DATA_DIR / "my_channel.json", {}),
    }


def write_bundle() -> Path:
    payload = build_bundle_payload()
    bundle_text = (
        "window.__DASHBOARD_DATA__ = "
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + ";\n"
    )
    BUNDLE_PATH.write_text(bundle_text, encoding="utf-8")
    return BUNDLE_PATH


if __name__ == "__main__":
    path = write_bundle()
    print(f"정적 번들 생성 완료: {path}")
