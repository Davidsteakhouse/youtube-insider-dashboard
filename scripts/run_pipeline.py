from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from analyzer import enrich_videos_with_analysis
from build_static_bundle import write_bundle
from common import DATA_DIR, load_env_file, read_json
from digest_builder import build_digest
from notion_importer import import_watchlist, normalize_channel
from storage import (
    export_snapshot_files,
    init_db,
    latest_digest,
    load_channels,
    load_videos,
    upsert_channels,
    upsert_digest,
    upsert_videos,
)
from telegram_notify import send_digest_message
from transcript_fetcher import enrich_videos_with_transcripts
from youtube_fetcher import merge_video_payload, refresh_watchlist_metadata


WATCHLIST_PATH = DATA_DIR / "watchlist.json"
VIDEOS_PATH = DATA_DIR / "videos.json"
DIGEST_PATH = DATA_DIR / "digest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YouTube Insider v2 데이터 파이프라인을 실행합니다.")
    parser.add_argument("--sync-watchlist", action="store_true", help="즉시 Notion/수동 파일에서 워치리스트를 동기화합니다.")
    parser.add_argument("--no-sync-watchlist", action="store_true", help="기본 Notion 자동 동기화를 건너뜁니다.")
    parser.add_argument("--notion-url", help="공개 Notion 페이지 URL")
    parser.add_argument("--import-file", help="수동 watchlist import 파일 경로(.json 또는 .csv)")
    parser.add_argument("--notify-telegram", action="store_true", help="생성된 digest를 Telegram으로 전송합니다.")
    parser.add_argument("--skip-transcripts", action="store_true", help="자막 수집 단계를 건너뜁니다.")
    parser.add_argument("--skip-analysis", action="store_true", help="LLM/휴리스틱 분석 단계를 건너뜁니다.")
    parser.add_argument("--max-results-per-channel", default=8, type=int, help="채널별로 조회할 최신 업로드 개수")
    return parser.parse_args()


def read_watchlist_snapshot() -> list[dict[str, Any]]:
    payload = read_json(WATCHLIST_PATH, {"channels": []})
    channels = payload if isinstance(payload, list) else payload.get("channels", [])
    return [normalize_channel(channel, source=str(channel.get("source", "watchlist_snapshot"))) for channel in channels]


def read_videos_snapshot() -> list[dict[str, Any]]:
    payload = read_json(VIDEOS_PATH, {"videos": []})
    if isinstance(payload, list):
        return payload
    return payload.get("videos", [])


def seed_database_from_exports_if_needed() -> None:
    if load_channels():
        return

    watchlist_snapshot = read_watchlist_snapshot()
    if watchlist_snapshot:
        upsert_channels(watchlist_snapshot)

    video_snapshot = read_videos_snapshot()
    if video_snapshot:
        upsert_videos(video_snapshot)

    digest_snapshot = read_json(DIGEST_PATH, {})
    if isinstance(digest_snapshot, dict) and digest_snapshot.get("generated_at"):
        upsert_digest(digest_snapshot)

    if watchlist_snapshot or video_snapshot or digest_snapshot:
        export_snapshot_files()
        write_bundle()


def refresh_static_bundle() -> None:
    export_snapshot_files()
    write_bundle()
    print("정적 export 및 data_bundle.js 갱신 완료")


def sync_watchlist(args: argparse.Namespace) -> list[dict[str, Any]]:
    notion_url = args.notion_url or os.getenv("NOTION_SOURCE_URL")
    import_file = args.import_file or os.getenv("WATCHLIST_IMPORT_FILE")
    channels, warnings = import_watchlist(notion_url=notion_url, import_file=import_file)
    persisted_channels = upsert_channels(channels)
    refresh_static_bundle()
    print(f"워치리스트 동기화 완료: {len(persisted_channels)}개 채널")
    for warning in warnings:
        print(f"경고: {warning}")
    return persisted_channels


def ensure_watchlist(args: argparse.Namespace) -> list[dict[str, Any]]:
    auto_sync_enabled = not args.no_sync_watchlist and (bool(os.getenv("NOTION_SOURCE_URL")) or bool(os.getenv("WATCHLIST_IMPORT_FILE")))
    if args.sync_watchlist or auto_sync_enabled:
        try:
            return sync_watchlist(args)
        except Exception as error:
            existing = load_channels()
            if existing:
                print(f"워치리스트 자동 동기화 실패, 기존 DB 워치리스트를 사용합니다: {error}")
                return existing
            raise

    existing = load_channels()
    if existing:
        return existing

    snapshot_channels = read_watchlist_snapshot()
    if snapshot_channels:
        return upsert_channels(snapshot_channels)

    raise RuntimeError("사용 가능한 워치리스트가 없습니다. Notion source 또는 import 파일이 필요합니다.")


def build_video_pipeline(args: argparse.Namespace, watchlist: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    existing_videos = load_videos()
    youtube_key = os.getenv("YOUTUBE_API_KEY")

    refreshed_watchlist = watchlist
    recent_videos: list[dict[str, Any]] = []

    if youtube_key:
        refreshed_watchlist = upsert_channels(refresh_watchlist_metadata(watchlist))
        recent_videos = merge_video_payload(
            refreshed_watchlist,
            existing_videos,
            max_results_per_channel=args.max_results_per_channel,
        )
        print(f"YouTube 수집 완료: 최근 24시간 영상 {len(recent_videos)}개")
    elif existing_videos:
        print("YOUTUBE_API_KEY가 없어 DB에 저장된 기존 영상으로 digest를 재계산합니다.")
        recent_videos = [video for video in existing_videos if video.get("is_recent") is not False]
    else:
        raise RuntimeError("YOUTUBE_API_KEY가 없고 기존 저장 영상도 없어 파이프라인을 진행할 수 없습니다.")

    if not args.skip_transcripts:
        recent_videos = enrich_videos_with_transcripts(recent_videos)
        print("자막 수집 단계 완료")

    if not args.skip_analysis:
        recent_videos = enrich_videos_with_analysis(recent_videos)
        print("분석 단계 완료")

    upsert_channels(refreshed_watchlist)
    upsert_videos(recent_videos)

    all_videos = load_videos()
    digest = build_digest(all_videos, refreshed_watchlist)
    upsert_digest(digest)
    refresh_static_bundle()
    print("digest 생성 및 export 반영 완료")
    return refreshed_watchlist, recent_videos, digest


def maybe_notify_telegram(args: argparse.Namespace, digest: dict[str, Any] | None = None) -> None:
    if not args.notify_telegram:
        return
    active_digest = digest or latest_digest()
    preview = active_digest.get("telegram_preview")
    if not preview:
        raise RuntimeError("전송할 digest 데이터가 없습니다.")
    send_digest_message(preview)
    print("Telegram 전송 완료")


def main() -> int:
    load_env_file()
    init_db()
    seed_database_from_exports_if_needed()
    args = parse_args()

    only_notify = args.notify_telegram and len(sys.argv) == 2
    only_sync = args.sync_watchlist and len(sys.argv) == 2 and not only_notify

    digest: dict[str, Any] | None = None
    if args.sync_watchlist:
        sync_watchlist(args)
        if only_sync:
            return 0

    if not only_notify:
        watchlist = ensure_watchlist(args)
        _watchlist, _recent_videos, digest = build_video_pipeline(args, watchlist)

    maybe_notify_telegram(args, digest=digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
