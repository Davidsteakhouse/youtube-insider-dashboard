from __future__ import annotations

import shutil
from pathlib import Path

from common import DATA_DIR, ROOT_DIR


DIST_DIR = ROOT_DIR / "dist"
WEB_FILES = [
    "index.html",
    "app.js",
    "styles.css",
    "data_bundle.js",
]
DATA_FILES = [
    "watchlist.json",
    "videos.json",
    "digest.json",
]


def reset_dist_dir() -> None:
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)


def copy_web_assets() -> None:
    for filename in WEB_FILES:
        source = ROOT_DIR / filename
        if source.exists():
            shutil.copy2(source, DIST_DIR / filename)


def copy_data_exports() -> None:
    target_data_dir = DIST_DIR / "data"
    target_data_dir.mkdir(parents=True, exist_ok=True)
    for filename in DATA_FILES:
        source = DATA_DIR / filename
        if source.exists():
            shutil.copy2(source, target_data_dir / filename)


def write_pages_markers() -> None:
    (DIST_DIR / ".nojekyll").write_text("", encoding="utf-8")


def main() -> int:
    reset_dist_dir()
    copy_web_assets()
    copy_data_exports()
    write_pages_markers()
    print(f"GitHub Pages 배포용 정적 사이트 생성 완료: {DIST_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
