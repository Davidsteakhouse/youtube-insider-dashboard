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
from pathlib import Path
from typing import Any


PREFERRED_LANGUAGES = ["ko", "ko-KR", "en", "en-US"]
APIFY_BASE = "https://api.apify.com/v2"
TMP_DIR = Path(__file__).resolve().parent.parent / ".tmp_transcripts"


def extract_video_id_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return ""

    hostname = (parsed.netloc or "").lower()
    path = parsed.path or ""
    if "youtu.be" in hostname:
        candidate = path.strip("/").split("/", 1)[0]
        return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or "") else ""

    if "youtube.com" in hostname or "m.youtube.com" in hostname:
        query_video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", query_video_id or ""):
            return query_video_id
        for prefix in ("/shorts/", "/embed/", "/live/"):
            if path.startswith(prefix):
                candidate = path[len(prefix):].split("/", 1)[0]
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or ""):
                    return candidate
    return ""


def normalize_error_code(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (value or "").upper()).strip("_")


def apify_actor_family(actor_id: str) -> str:
    actor = (actor_id or "").strip().lower()
    if "johnvc" in actor and "youtubetranscripts" in actor:
        return "johnvc_youtubetranscripts"
    if "supreme_coder" in actor and "youtube-transcript-scraper" in actor:
        return "supreme_coder_youtube_transcript_scraper"
    return "default"


def apify_actor_payload(actor_id: str, video_ids: list[str]) -> dict[str, Any]:
    actor_family = apify_actor_family(actor_id)
    if actor_family == "johnvc_youtubetranscripts":
        return {
            "youtube_url": [f"https://www.youtube.com/watch?v={video_id}" for video_id in video_ids],
        }
    if actor_family == "supreme_coder_youtube_transcript_scraper":
        return {
            "urls": [{"url": f"https://www.youtube.com/watch?v={video_id}"} for video_id in video_ids],
            "languages": PREFERRED_LANGUAGES,
            "outputFormat": "text",
        }
    return {
        "video_ids": video_ids,
        "languages": PREFERRED_LANGUAGES,
        "text_only": True,
        "include_generated": True,
        "include_translation": True,
        "fetch_all": False,
    }


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


def unavailable_transcript_payload(*, source: str) -> dict[str, Any]:
    return transcript_payload(status="unavailable", source=source, language="", text="")


def blocked_transcript_payload(*, source: str) -> dict[str, Any]:
    return transcript_payload(status="blocked", source=source, language="", text="")


def is_permanently_unavailable_error(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        token in lowered
        for token in [
            "subtitles are disabled",
            "transcripts are disabled",
            "video is unavailable",
            "private video",
            "age restricted",
            "age-restricted",
        ]
    )


def is_request_blocked_error(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        token in lowered
        for token in [
            "youtube is blocking requests from your ip",
            "requestblocked",
            "ipblocked",
            "too many requests",
            "http error 429",
        ]
    )


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
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore

        api = YouTubeTranscriptApi()
        transcript_items = api.fetch(video_id, languages=PREFERRED_LANGUAGES)
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
        error_message = str(exc)
        if is_permanently_unavailable_error(error_message):
            return unavailable_transcript_payload(source="transcript_api")
        if is_request_blocked_error(error_message):
            print(f"[transcript] transcript_api 차단 ({video_id}): {exc}")
            return blocked_transcript_payload(source="transcript_api")
        print(f"[transcript] transcript_api.fetch() 실패 ({video_id}): {exc}")
        return None
    return None


def fetch_via_ytdlp(video_id: str) -> dict[str, Any] | None:
    if not importlib.util.find_spec("yt_dlp"):
        return None

    try:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TMP_DIR) as tmp_dir:
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
    raw_transcript = item.get("transcript")
    if isinstance(raw_transcript, str) and raw_transcript.strip():
        language_code = str(item.get("languageCode") or item.get("language_code") or item.get("language") or "").strip()
        return raw_transcript.strip(), language_code
    if isinstance(raw_transcript, list):
        parts: list[str] = []
        for snippet in raw_transcript:
            if isinstance(snippet, dict):
                text = str(snippet.get("text") or "").strip()
            else:
                text = str(snippet or "").strip()
            if text:
                parts.append(text)
        if parts:
            language_code = str(item.get("languageCode") or item.get("language_code") or item.get("language") or "").strip()
            return "\n".join(parts).strip(), language_code

    raw_non_timestamped = str(item.get("non_timestamped") or "").strip()
    if raw_non_timestamped and item.get("success", True) is not False:
        language_code = str(item.get("language_code") or item.get("language") or "").strip()
        return raw_non_timestamped, language_code

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


def _batch_fetch_via_apify_actor(video_ids: list[str], actor_id: str, token: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """단일 Apify actor를 실행해 결과와 미해결 video_id 목록을 반환."""
    if not token or not video_ids:
        return {}, []

    # 1) 액터 실행 시작
    memory_mb = int(os.getenv("APIFY_MEMORY_MB", "1024") or 1024)
    run_url = f"{APIFY_BASE}/acts/{urllib.parse.quote(actor_id, safe='~')}/runs?token={token}&memory={memory_mb}"
    payload = json.dumps(apify_actor_payload(actor_id, video_ids)).encode()
    req = urllib.request.Request(run_url, data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            run_data = json.loads(resp.read())
    except Exception as exc:
        print(f"[transcript] Apify 배치 실행 시작 실패 ({actor_id}): {exc}")
        return {}, list(video_ids)

    run_id = (run_data.get("data") or {}).get("id")
    if not run_id:
        print(f"[transcript] Apify run_id 없음 ({actor_id})")
        return {}, list(video_ids)

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
        print(f"[transcript] Apify 배치 완료 안됨 ({actor_id}): {status}")
        return {}, list(video_ids)

    dataset_id = (status_data.get("data") or {}).get("defaultDatasetId", "")
    if not dataset_id:
        print(f"[transcript] Apify dataset_id 없음 ({actor_id})")
        return {}, list(video_ids)

    # 3) 결과 조회
    items_url = f"{APIFY_BASE}/datasets/{dataset_id}/items?token={token}"
    try:
        with urllib.request.urlopen(items_url, timeout=30) as resp:
            items = json.loads(resp.read())
    except Exception as exc:
        print(f"[transcript] Apify 결과 조회 실패 ({actor_id}): {exc}")
        return {}, list(video_ids)

    # 4) video_id → payload 매핑
    # "unavailable" = Apify가 영구적으로 자막 없음을 확인 → 재시도 안 함
    PERMANENT_ERROR_CODES = {
        "TRANSCRIPTS_DISABLED",
        "VIDEO_UNAVAILABLE",
        "PRIVATE_VIDEO",
        "AGE_RESTRICTED",
        "TRANSCRIPT_NOT_FOUND",
    }
    results: dict[str, dict[str, Any]] = {}
    unresolved_ids: set[str] = set()
    for item in (items or []):
        vid = (
            str(item.get("video_id") or "").strip()
            or str(item.get("videoId") or "").strip()
            or str(((item.get("videoDetails") or {}) if isinstance(item.get("videoDetails"), dict) else {}).get("videoId") or "").strip()
            or extract_video_id_from_url(str(item.get("url") or "").strip())
            or extract_video_id_from_url(str(item.get("inputUrl") or "").strip())
        )
        if not vid:
            continue
        raw_error_code = str(item.get("code") or item.get("error_type") or item.get("errorCode") or "").strip()
        error_code = normalize_error_code(raw_error_code)
        if error_code in PERMANENT_ERROR_CODES:
            results[vid] = transcript_payload(status="unavailable", source="apify", language="", text="")
            print(f"[transcript] Apify 영구 불가 ({vid}, {actor_id}): {raw_error_code or error_code}")
            continue
        error_message = str(item.get("error") or item.get("error_message") or "").strip()
        lowered_error = error_message.lower()
        if any(token in lowered_error for token in ["disabled", "private", "age-restricted", "unavailable"]):
            results[vid] = transcript_payload(status="unavailable", source="apify", language="", text="")
            print(f"[transcript] Apify 영구 불가 ({vid}, {actor_id}): {error_message}")
            continue
        extracted = _apify_extract_transcript_text(item)
        if extracted:
            text, lang = extracted
            results[vid] = transcript_payload(
                status="available", source="apify", language=lang, text=text
            )
            print(f"[transcript] Apify 성공 ({vid}, {actor_id}): {len(text)}자")
        else:
            unresolved_ids.add(vid)
            reason = raw_error_code or error_message or "empty_result"
            print(f"[transcript] Apify 미해결 ({vid}, {actor_id}): {reason}")

    unresolved_ids.update(vid for vid in video_ids if vid not in results and vid not in unresolved_ids)
    print(f"[transcript] Apify 배치 완료 ({actor_id}): {len(results)}/{len(video_ids)}개 처리")
    return results, sorted(unresolved_ids)


def batch_fetch_via_apify(video_ids: list[str]) -> dict[str, dict[str, Any]]:
    """여러 video_id를 Apify actor 체인으로 수집. {video_id: transcript_payload} 반환."""
    token = os.getenv("APIFY_TOKEN", "").strip()
    actor_id = os.getenv("APIFY_YOUTUBE_TRANSCRIPT_ACTOR_ID", "supreme_coder~youtube-transcript-scraper").strip()
    fallback_actor_id = os.getenv("APIFY_YOUTUBE_TRANSCRIPT_FALLBACK_ACTOR_ID", "").strip()
    if not token or not video_ids:
        return {}

    results, unresolved_ids = _batch_fetch_via_apify_actor(video_ids, actor_id, token)

    if fallback_actor_id and fallback_actor_id != actor_id and unresolved_ids:
        print(f"[transcript] Apify fallback 시작: {len(unresolved_ids)}개 → {fallback_actor_id}")
        fallback_results, fallback_unresolved_ids = _batch_fetch_via_apify_actor(unresolved_ids, fallback_actor_id, token)
        results.update(fallback_results)
        unresolved_ids = fallback_unresolved_ids

    if unresolved_ids:
        print(f"[transcript] Apify 최종 미해결: {len(unresolved_ids)}개")
    return results


def fetch_transcript(video_id: str) -> dict[str, Any]:
    transcript_api_result = fetch_via_youtube_transcript_api(video_id)
    if transcript_api_result and transcript_api_result.get("transcript_status") == "blocked":
        return transcript_api_result
    result = transcript_api_result or fetch_via_ytdlp(video_id)
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
    fetch_delay_sec = float(os.getenv("TRANSCRIPT_FETCH_DELAY_SEC", "8") or 8)
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
        if video.get("transcript_status") == "unavailable":
            continue  # Apify가 영구 불가 확인 → 재시도 안 함
        if vid not in prioritized_set:
            continue
        result = fetch_transcript(vid)
        if result.get("transcript_status") == "blocked":
            blocked_ids = [candidate for candidate in prioritized_ids if candidate not in individual_results and candidate not in failed_ids]
            failed_ids.extend(blocked_ids)
            print(f"[transcript] 현재 IP 차단 감지. 남은 {len(blocked_ids)}개를 Apify 배치로 전환합니다.")
            break
        if result.get("transcript_status") == "failed":
            failed_ids.append(vid)
        else:
            individual_results[vid] = result
        time.sleep(fetch_delay_sec)

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
        elif video.get("transcript_status") == "unavailable":
            enriched.append(video)  # 영구 불가 → 그대로 유지
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
