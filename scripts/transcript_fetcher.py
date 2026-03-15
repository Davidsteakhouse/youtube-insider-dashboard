from __future__ import annotations

import ast
import importlib
import json
import os
import subprocess
import sys
import tempfile
from socket import timeout as SocketTimeout
from typing import Any
from urllib.error import URLError

from common import request_json


APIFY_BASE = "https://api.apify.com/v2"
DEFAULT_ACTOR_ID = "futurizerush~youtube-transcript-scraper"
LEGACY_ACTOR_IDS = {"h7sDV53CddomktSi5"}
PREFERRED_LANGUAGES = ["ko", "ko-KR", "en", "en-US"]


def normalize_language(value: Any) -> str:
    return str(value or "").strip()


def flatten_text(value: Any) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            for parser in (json.loads, ast.literal_eval):
                try:
                    parsed = parser(stripped)
                except Exception:
                    continue
                nested_text = flatten_text(parsed)
                if nested_text:
                    return nested_text
        return stripped
    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            text = flatten_text(item)
            if text:
                lines.append(text)
        return "\n".join(lines).strip()
    if isinstance(value, dict):
        for key in ("plaintext", "text", "transcriptText", "transcript", "plainText", "content"):
            if key not in value:
                continue
            direct = flatten_text(value.get(key))
            if direct:
                return direct
        lines: list[str] = []
        for key in ("subtitles", "chunks", "segments", "entries", "lines", "items"):
            nested = value.get(key)
            if isinstance(nested, list):
                for item in nested:
                    text = flatten_text(item)
                    if text:
                        lines.append(text)
        return "\n".join(lines).strip()
    return ""


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


def actor_id_candidates() -> list[str]:
    configured = normalize_language(os.getenv("APIFY_YOUTUBE_TRANSCRIPT_ACTOR_ID"))
    candidates: list[str] = []
    if configured and configured not in LEGACY_ACTOR_IDS:
        candidates.append(configured)
    if DEFAULT_ACTOR_ID not in candidates:
        candidates.append(DEFAULT_ACTOR_ID)
    return candidates


def transcript_language_label(display_language: str, source_language: str | None = None) -> str:
    display = normalize_language(display_language)
    source = normalize_language(source_language)
    if display and source and display != source:
        return f"{display} ← {source}"
    return display or source


def is_korean(language: str) -> bool:
    lowered = normalize_language(language).lower()
    return lowered.startswith("ko")


def is_english(language: str) -> bool:
    lowered = normalize_language(language).lower()
    return lowered.startswith("en")


def candidate_priority(candidate: dict[str, Any]) -> tuple[int, int]:
    language = normalize_language(candidate.get("language"))
    status = normalize_language(candidate.get("status"))
    if is_korean(language) and status == "available":
        return (0, 0)
    if is_korean(language) and status == "available_auto":
        return (1, 0)
    if is_korean(language) and status == "translated":
        return (2, 0)
    if is_english(language) and status == "available":
        return (3, 0)
    if is_english(language) and status == "available_auto":
        return (4, 0)
    return (5, 0)


def build_candidate(
    text: str,
    *,
    language: str,
    source: str,
    status: str,
) -> dict[str, Any]:
    return {
        "text": text,
        "language": language,
        "source": source,
        "status": status,
    }


def subtitle_candidates_from_list(subtitles: Any) -> list[dict[str, Any]]:
    if isinstance(subtitles, dict):
        subtitles = [subtitles]
    if not isinstance(subtitles, list):
        return []

    candidates: list[dict[str, Any]] = []
    for subtitle in subtitles:
        if not isinstance(subtitle, dict):
            continue
        text = flatten_text(subtitle)
        if not text:
            continue
        language = transcript_language_label(
            subtitle.get("language") or subtitle.get("languageCode"),
            subtitle.get("sourceLanguage") or subtitle.get("translatedFrom"),
        )
        subtitle_type = normalize_language(subtitle.get("type")).lower()
        translated = bool(subtitle.get("isTranslated")) or bool(subtitle.get("translatedFrom")) or bool(subtitle.get("sourceLanguage"))
        status = "translated" if translated else ("available_auto" if "auto" in subtitle_type else "available")
        candidates.append(build_candidate(text, language=language, source="apify", status=status))
    return candidates


def subtitle_candidates_from_transcript_map(transcripts: Any) -> list[dict[str, Any]]:
    if not isinstance(transcripts, dict):
        return []

    candidates: list[dict[str, Any]] = []
    for language_key, payload in transcripts.items():
        language = normalize_language(language_key)

        if isinstance(payload, dict):
            text = flatten_text(payload)
            translated_from = payload.get("translatedFrom") or payload.get("sourceLanguage")
            status = "translated" if translated_from or payload.get("isTranslated") else (
                "available_auto" if payload.get("isGenerated") or payload.get("autoGenerated") else "available"
            )
            candidate_language = transcript_language_label(language, translated_from)
            if text:
                candidates.append(build_candidate(text, language=candidate_language, source="apify", status=status))
            continue

        text = flatten_text(payload)
        if text:
            candidates.append(build_candidate(text, language=language, source="apify", status="available"))
    return candidates


def transcript_candidates_from_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for candidate in subtitle_candidates_from_list(item.get("subtitles")):
        key = (candidate["text"], candidate["language"], candidate["status"])
        if key not in seen:
            seen.add(key)
            candidates.append(candidate)

    for candidate in subtitle_candidates_from_transcript_map(item.get("transcripts")):
        key = (candidate["text"], candidate["language"], candidate["status"])
        if key not in seen:
            seen.add(key)
            candidates.append(candidate)

    direct_variants = [
        (
            flatten_text(item.get("transcriptText") or item.get("transcript") or item.get("text")),
            transcript_language_label(
                item.get("language") or item.get("languageCode") or item.get("requestedLanguage"),
                item.get("sourceLanguage") or item.get("translatedFrom"),
            ),
            "translated" if item.get("isTranslated") or item.get("translatedFrom") else (
                "available_auto" if item.get("isGenerated") or item.get("autoGenerated") else "available"
            ),
        ),
        (
            flatten_text(item.get("translation") or item.get("translatedText")),
            transcript_language_label(item.get("displayLanguage") or "ko", item.get("language") or item.get("sourceLanguage")),
            "translated",
        ),
    ]

    for text, language, status in direct_variants:
        if text:
            key = (text, language, status)
            if key not in seen:
                seen.add(key)
                candidates.append(build_candidate(text, language=language, source="apify", status=status))

    for collection_key in ("translations", "translatedTranscripts", "localizedTranscripts", "results", "items"):
        collection = item.get(collection_key)
        if isinstance(collection, list):
            for nested in collection:
                if not isinstance(nested, dict):
                    continue
                text = flatten_text(nested)
                if not text:
                    continue
                language = transcript_language_label(
                    nested.get("displayLanguage") or nested.get("language") or nested.get("languageCode"),
                    nested.get("sourceLanguage") or nested.get("translatedFrom") or item.get("language"),
                )
                status = "translated" if nested.get("isTranslated") or nested.get("translatedFrom") or nested.get("sourceLanguage") else (
                    "available_auto" if nested.get("isGenerated") or nested.get("autoGenerated") else "available"
                )
                key = (text, language, status)
                if key not in seen:
                    seen.add(key)
                    candidates.append(build_candidate(text, language=language, source="apify", status=status))

    return candidates


def extract_apify_transcript(items: Any) -> dict[str, Any]:
    if not isinstance(items, list) or not items:
        return {
            "transcript_status": "unavailable",
            "transcript_source": "none",
            "transcript_language": "",
            "transcript_text": "",
            "transcript_highlights": [],
        }

    candidates: list[dict[str, Any]] = []
    description_only = ""
    for item in items:
        if not isinstance(item, dict):
            continue
        candidates.extend(transcript_candidates_from_item(item))
        if not description_only:
            description_only = flatten_text(item.get("description") or item.get("textDescription") or "")

    if candidates:
        best = sorted(candidates, key=candidate_priority)[0]
        return transcript_payload(
            status=best["status"],
            source=best["source"],
            language=best["language"],
            text=best["text"],
        )

    if description_only:
        return {
            "transcript_status": "description_only",
            "transcript_source": "apify",
            "transcript_language": "",
            "transcript_text": "",
            "transcript_highlights": [],
        }

    return {
        "transcript_status": "unavailable",
        "transcript_source": "none",
        "transcript_language": "",
        "transcript_text": "",
        "transcript_highlights": [],
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


def fetch_items_from_transcript_obj(transcript_obj: Any) -> list[dict[str, Any]] | None:
    try:
        items = transcript_obj.fetch()
    except Exception:
        return None
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
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
            result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
            if result.returncode != 0:
                return None

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
                for raw_line in handle:
                    stripped = raw_line.strip()
                    if not stripped or stripped.startswith("WEBVTT") or "-->" in stripped or stripped.isdigit():
                        continue
                    lines.append(stripped)
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
    token = os.getenv("APIFY_TOKEN")

    if token:
        payload = {
            "video_ids": [video_id],
            "languages": PREFERRED_LANGUAGES,
            "text_only": True,
            "include_generated": True,
            "include_translation": True,
        }
        for actor_id in actor_id_candidates():
            try:
                items = request_json(
                    f"{APIFY_BASE}/acts/{actor_id}/run-sync-get-dataset-items",
                    method="POST",
                    params={"token": token},
                    payload=payload,
                    timeout=120,
                )
                transcript = extract_apify_transcript(items)
                if transcript.get("transcript_status") in {"available", "available_auto", "translated"}:
                    return transcript
                fallback = fetch_via_youtube_transcript_api(video_id) or fetch_via_ytdlp(video_id)
                return fallback or transcript
            except (RuntimeError, TimeoutError, SocketTimeout, URLError, OSError):
                continue

    fallback = fetch_via_youtube_transcript_api(video_id) or fetch_via_ytdlp(video_id)
    if fallback:
        return fallback

    if token:
        return {
            "transcript_status": "failed",
            "transcript_source": "none",
            "transcript_language": "",
            "transcript_text": "",
            "transcript_highlights": [],
        }

    return {
        "transcript_status": "not_configured",
        "transcript_source": "none",
        "transcript_language": "",
        "transcript_text": "",
        "transcript_highlights": [],
    }


def enrich_videos_with_transcripts(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    token = os.getenv("APIFY_TOKEN")
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

        if not token:
            transcript = fetch_transcript(video.get("video_id", "")) if (not has_existing_transcript) else None
            enriched.append({**video, **transcript} if transcript else video)
            continue

        if video.get("video_id") not in prioritized_ids:
            enriched.append({**video, "transcript_status": video.get("transcript_status") or "skipped"})
            continue

        transcript = fetch_transcript(video.get("video_id", ""))
        enriched.append({**video, **transcript})
    return enriched
