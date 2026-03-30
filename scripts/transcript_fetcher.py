from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


PREFERRED_LANGUAGES = ["ko", "ko-KR", "en", "en-US"]
APIFY_BASE = "https://api.apify.com/v2"


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
            result: list[dict[str, Any]] = []
            for item in items:
                if isinstance(item, dict):
                    # 0.6.x: 이미 dict {"text": ..., "start": ..., "duration": ...}
                    result.append(item)
                elif hasattr(item, "text"):
                    # 1.x: FetchedTranscriptSnippet 객체 → dict으로 변환
                    result.append({"text": str(item.text), "start": getattr(item, "start", 0), "duration": getattr(item, "duration", 0)})
            return result if result else None
        except Exception as exc:
            error_str = str(exc)
            is_rate_limit = "429" in error_str or "Too Many Requests" in error_str
            is_empty_xml = "no element found" in error_str
            if (is_rate_limit or is_empty_xml) and attempt < max_retries:
                time.sleep(3 * (attempt + 1))
                continue
            print(f"[transcript] transcript_obj.fetch() 실패 (시도 {attempt+1}): {exc}")
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
        parts: list[str] = []
        for item in transcript_items:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
            elif hasattr(item, "text"):
                text = str(item.text).strip()
            else:
                continue
            if text:
                parts.append(text)
        transcript_text = "\n".join(parts).strip()
        if transcript_text:
            return transcript_payload(
                status="available_auto",
                source="transcript_api",
                language="ko_or_en",
                text=transcript_text,
            )
    except Exception as exc:
        print(f"[transcript] get_transcript() 실패 ({video_id}): {exc}")
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
    except Exception as exc:
        print(f"[transcript] yt-dlp 실패 ({video_id}): {exc}")
        return None


def _apify_extract_transcript_text(item: dict[str, Any]) -> tuple[str, str] | None:
    """Apify 결과 item에서 (text, language) 추출. 언어 우선순위: ko > en."""
    transcripts = item.get("transcripts") or {}
    for lang in PREFERRED_LANGUAGES:
        lang_data = transcripts.get(lang) or {}
        raw = lang_data.get("transcript") or []
        if not raw:
            continue
        if isinstance(raw, list):
            parts = [str(s).strip() for s in raw if str(s).strip()]
        else:
            parts = [str(raw).strip()]
        text = "\n".join(parts).strip()
        if text:
            return text, lang
    return None


def batch_fetch_via_apify(video_ids: list[str]) -> dict[str, dict[str, Any]]:
    """여러 video_id를 한 번의 Apify 실행으로 수집. {video_id: transcript_payload} 반환."""
    token = os.getenv("APIFY_TOKEN", "").strip()
    actor_id = os.getenv("APIFY_YOUTUBE_TRANSCRIPT_ACTOR_ID", "futurizerush~youtube-transcript-scraper").strip()
    if not token or not video_ids:
        return {}

    # 1) 액터 실행 시작
    run_url = f"{APIFY_BASE}/acts/{urllib.parse.quote(actor_id, safe='~')}/runs?token={token}"
    payload = json.dumps({
        "video_ids": video_ids,
        "languages": PREFERRED_LANGUAGES,
        "text_only": True,
        "include_generated": True,
        "include_translation": True,
        "fetch_all": False,
    }).encode()
    req = urllib.request.Request(run_url, data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            run_data = json.loads(resp.read())
    except Exception as exc:
        print(f"[transcript] Apify 배치 실행 시작 실패: {exc}")
        return {}

    run_id = (run_data.get("data") or {}).get("id")
    if not run_id:
        print("[transcript] Apify run_id 없음")
        return {}

    # 2) 완료 대기 (최대 5분, 10초 간격)
    status_url = f"{APIFY_BASE}/actor-runs/{run_id}?token={token}"
    status = ""
    status_data: dict[str, Any] = {}
    for _ in range(30):
        time.sleep(10)
        try:
            with urllib.request.urlopen(status_url, timeout=15) as resp:
                status_data = json.loads(resp.read())
            status = (status_data.get("data") or {}).get("status", "")
            if status in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
                break
        except Exception:
            pass

    if status != "SUCCEEDED":
        print(f"[transcript] Apify 배치 완료 안됨: {status}")
        return {}

    dataset_id = (status_data.get("data") or {}).get("defaultDatasetId", "")
    if not dataset_id:
        print("[transcript] Apify dataset_id 없음")
        return {}

    # 3) 결과 조회
    items_url = f"{APIFY_BASE}/datasets/{dataset_id}/items?token={token}"
    try:
        with urllib.request.urlopen(items_url, timeout=30) as resp:
            items = json.loads(resp.read())
    except Exception as exc:
        print(f"[transcript] Apify 결과 조회 실패: {exc}")
        return {}

    # 4) video_id → payload 매핑
    results: dict[str, dict[str, Any]] = {}
    for item in (items or []):
        vid = item.get("video_id") or ""
        if not vid:
            continue
        extracted = _apify_extract_transcript_text(item)
        if extracted:
            text, lang = extracted
            results[vid] = transcript_payload(
                status="available", source="apify", language=lang, text=text
            )
            print(f"[transcript] Apify 성공 ({vid}): {len(text)}자")
        else:
            print(f"[transcript] Apify 자막 없음 ({vid})")

    print(f"[transcript] Apify 배치 완료: {len(results)}/{len(video_ids)}개 성공")
    return results


def fetch_transcript(video_id: str) -> dict[str, Any]:
    result = fetch_via_youtube_transcript_api(video_id) or fetch_via_ytdlp(video_id)
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
    prioritized_ids = [
        video.get("video_id")
        for video in sorted(
            videos,
            key=lambda item: (
                0 if item.get("is_recent") else 1,
                -float(item.get("view_count", 0) or 0),
                -float(item.get("engagement_rate", 0) or 0),
            ),
        )[:max_fetch]
        if video.get("video_id")
    ]
    prioritized_set = set(prioritized_ids)

    # 1단계: youtube-transcript-api / yt-dlp로 개별 시도
    individual_results: dict[str, dict[str, Any]] = {}
    failed_ids: list[str] = []
    for video in videos:
        vid = video.get("video_id", "")
        has_existing = bool(video.get("transcript_text")) or bool(video.get("transcript_highlights"))
        if video.get("transcript_status") in {"available", "available_auto", "translated"} and has_existing:
            continue  # 이미 수집됨
        if vid not in prioritized_set:
            continue
        result = fetch_transcript(vid)
        if result.get("transcript_status") == "failed":
            failed_ids.append(vid)
        else:
            individual_results[vid] = result
        time.sleep(3)

    # 2단계: 실패한 영상만 Apify 배치로 재시도
    apify_results: dict[str, dict[str, Any]] = {}
    if failed_ids and os.getenv("APIFY_TOKEN", "").strip():
        print(f"[transcript] Apify 배치 시작: {len(failed_ids)}개 실패 영상")
        apify_results = batch_fetch_via_apify(failed_ids)

    # 3단계: 결과 병합
    enriched: list[dict[str, Any]] = []
    for video in videos:
        vid = video.get("video_id", "")
        has_existing = bool(video.get("transcript_text")) or bool(video.get("transcript_highlights"))
        if video.get("transcript_status") in {"available", "available_auto", "translated"} and has_existing:
            enriched.append(video)
        elif vid in individual_results:
            enriched.append({**video, **individual_results[vid]})
        elif vid in apify_results:
            enriched.append({**video, **apify_results[vid]})
        elif vid in prioritized_set:
            enriched.append({**video, "transcript_status": "failed", "transcript_source": "none",
                              "transcript_language": "", "transcript_text": "", "transcript_highlights": []})
        else:
            enriched.append({**video, "transcript_status": video.get("transcript_status") or "skipped"})

    return enriched
