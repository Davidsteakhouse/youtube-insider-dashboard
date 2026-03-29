from __future__ import annotations

import importlib
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import time
from typing import Any


PREFERRED_LANGUAGES = ["ko", "ko-KR", "en", "en-US"]


def transcript_payload(
    *,
    status: str,
    source: str,
    language: str,
    text: str,
) -> dict[str, Any]:
    highlights = [line.strip() for line in text.splitlines() if line.strip()][:3]
    return {
        "transcript_status": status,
        "transcript_source": source,
        "transcript_language": language,
        "transcript_text": text,
        "transcript_highlights": highlights,
    }


def transcript_list_instance(video_id: str) -> Any:
    module = importlib.util.find_spec("youtube_transcript_api")
    if not module:
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    except Exception:
        return None

    try:
        if hasattr(YouTubeTranscriptApi, "list_transcripts"):
            return YouTubeTranscriptApi.list_transcripts(video_id)
        api = YouTubeTranscriptApi()
        if hasattr(api, "list"):
            return api.list(video_id)
    except Exception:
        return None
    return None


def fetch_items_from_transcript_obj(transcript_obj: Any, max_retries: int = 2) -> list[dict[str, Any]] | None:
    for attempt in range(max_retries + 1):
        try:
            items = transcript_obj.fetch()
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
            return None
        except Exception as exc:
            error_str = str(exc)
            is_rate_limit = "429" in error_str or "Too Many Requests" in error_str
            is_empty_xml = "no element found" in error_str
            if (is_rate_limit or is_empty_xml) and attempt < max_retries:
                time.sleep(3 * (attempt + 1))
                continue
            return None
    return None


def build_transcript_api_payload(transcript_obj: Any, *, source_status: str, source_language: str) -> dict[str, Any] | None:
    items = fetch_items_from_transcript_obj(transcript_obj)
    if not items:
        return None
    transcript_text = "\n".join(
        str(item.get("text") or "").strip()
        for item in items
        if str(item.get("text") or "").strip()
    ).strip()
    if not transcript_text:
        return None
    return transcript_payload(
        status=source_status,
        source="transcript_api",
        language=source_language,
        text=transcript_text,
    )


def fetch_via_youtube_transcript_api(video_id: str) -> dict[str, Any] | None:
    transcript_list = transcript_list_instance(video_id)
    if transcript_list is None:
        return None

    try:
        if hasattr(transcript_list, "find_manually_created_transcript"):
            ko_manual = transcript_list.find_manually_created_transcript(["ko", "ko-KR"])
            payload = build_transcript_api_payload(ko_manual, source_status="available", source_language="ko")
            if payload:
                return payload
    except Exception:
        pass

    try:
        if hasattr(transcript_list, "find_generated_transcript"):
            ko_generated = transcript_list.find_generated_transcript(["ko", "ko-KR"])
            payload = build_transcript_api_payload(ko_generated, source_status="available_auto", source_language="ko")
            if payload:
                return payload
    except Exception:
        pass

    try:
        if hasattr(transcript_list, "find_transcript"):
            english = transcript_list.find_transcript(["en", "en-US"])
            if hasattr(english, "translate"):
                translated = english.translate("ko")
                payload = build_transcript_api_payload(translated, source_status="translated", source_language="ko ← en")
                if payload:
                    return payload
            payload = build_transcript_api_payload(
                english,
                source_status="available_auto" if getattr(english, "is_generated", False) else "available",
                source_language="en",
            )
            if payload:
                return payload
    except Exception:
        pass

    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore

        transcript_items = YouTubeTranscriptApi.get_transcript(video_id, languages=PREFERRED_LANGUAGES)
        transcript_text = "\n".join(
            str(item.get("text") or "").strip()
            for item in transcript_items
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ).strip()
        if transcript_text:
            return transcript_payload(
                status="available_auto",
                source="transcript_api",
                language="ko_or_en",
                text=transcript_text,
            )
    except Exception:
        return None
    return None


def fetch_via_ytdlp(video_id: str) -> dict[str, Any] | None:
    if not importlib.util.find_spec("yt_dlp"):
        return None

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            command = [
                sys.executable,
                "-m",
                "yt_dlp",
                "--skip-download",
                "--write-auto-subs",
                "--write-subs",
                "--sub-langs",
                "ko.*,ko,en.*,en",
                "--sub-format",
                "vtt",
                "-o",
                f"{tmp_dir}/%(id)s.%(ext)s",
                f"https://www.youtube.com/watch?v={video_id}",
            ]
            subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)

            subtitle_files = sorted(
                path for path in os.listdir(tmp_dir)
                if path.endswith(".vtt") and video_id in path
            )
            if not subtitle_files:
                return None

            preferred_files = sorted(
                subtitle_files,
                key=lambda item: (
                    0 if ".ko" in item.lower() else 1,
                    0 if ".en" in item.lower() else 1,
                    0 if ".orig" in item.lower() else 1,
                    1 if ".vtt" in item.lower() else 0,
                    item,
                ),
            )
            subtitle_path = os.path.join(tmp_dir, preferred_files[0])
            with open(subtitle_path, "r", encoding="utf-8", errors="ignore") as handle:
                lines: list[str] = []
                seen: set[str] = set()
                for raw_line in handle:
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    if stripped.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE", "REGION")):
                        continue
                    if "-->" in stripped or stripped.isdigit():
                        continue
                    cleaned = re.sub(r"<[^>]+>", "", stripped).strip()
                    if cleaned and cleaned not in seen:
                        seen.add(cleaned)
                        lines.append(cleaned)
            transcript_text = "\n".join(lines).strip()
            if not transcript_text:
                return None

            lowered = preferred_files[0].lower()
            language = "ko" if ".ko" in lowered else ("en" if ".en" in lowered else "ko_or_en")
            status = "available_auto" if ".live_chat" not in lowered else "available"
            return transcript_payload(status=status, source="ytdlp", language=language, text=transcript_text)
    except Exception:
        return None


def fetch_transcript(video_id: str) -> dict[str, Any]:
    result = fetch_via_ytdlp(video_id) or fetch_via_youtube_transcript_api(video_id)
    if result:
        return result
    return {
        "transcript_status": "failed",
        "transcript_source": "none",
        "transcript_language": "",
        "transcript_text": "",
        "transcript_highlights": [],
    }


def enrich_videos_with_transcripts(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    max_fetch = int(os.getenv("TRANSCRIPT_FETCH_LIMIT", "24") or 24)
    prioritized_ids = {
        video.get("video_id")
        for video in sorted(
            videos,
            key=lambda item: (
                0 if item.get("is_recent") else 1,
                -float(item.get("view_count", 0) or 0),
                -float(item.get("engagement_rate", 0) or 0),
            ),
        )[:max_fetch]
    }

    enriched: list[dict[str, Any]] = []
    for video in videos:
        has_existing_transcript = bool(video.get("transcript_text")) or bool(video.get("transcript_highlights"))
        if video.get("transcript_status") in {"available", "available_auto", "translated"} and has_existing_transcript:
            enriched.append(video)
            continue

        if video.get("video_id") not in prioritized_ids:
            enriched.append({**video, "transcript_status": video.get("transcript_status") or "skipped"})
            continue

        transcript = fetch_transcript(video.get("video_id", ""))
        enriched.append({**video, **transcript})
        time.sleep(5)
    return enriched
