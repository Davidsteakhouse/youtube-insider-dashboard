from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Any

from common import request_json, request_text, utcnow_iso


NOTION_LOAD_URL = "https://www.notion.so/api/v3/loadCachedPageChunk"
NOTION_QUERY_URL = "https://www.notion.so/api/v3/queryCollection"
NOTION_SYNC_URL = "https://www.notion.so/api/v3/syncRecordValues"
YOUTUBE_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?youtube\.com/(?:@[\w.%+-]+(?:/videos)?|channel/[A-Za-z0-9_-]+|c/[\w.%+-]+(?:/videos)?|user/[\w.%+-]+(?:/videos)?)",
    re.IGNORECASE
)
CHANNEL_ID_PATTERN = re.compile(r"UC[A-Za-z0-9_-]{20,}")


def parse_page_id(source: str) -> str:
    match = re.search(r"([0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", source)
    if not match:
        raise ValueError(f"Notion page id를 찾을 수 없습니다: {source}")
    page_id = match.group(1).replace("-", "")
    return f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:32]}"


def notion_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    token_v2 = os.getenv("NOTION_TOKEN_V2")
    if token_v2:
        headers["Cookie"] = f"token_v2={token_v2}"
    return headers


def fetch_page_record_map(page_id: str) -> dict[str, Any]:
    return request_json(
        NOTION_LOAD_URL,
        method="POST",
        headers=notion_headers(),
        payload={
            "pageId": page_id,
            "limit": 500,
            "cursor": {"stack": []},
            "chunkNumber": 0,
            "verticalColumns": False
        }
    )


def collection_name(value: dict[str, Any]) -> str:
    raw_name = value.get("name", [])
    if not raw_name:
        return ""
    return "".join(segment[0] for segment in raw_name if segment)


def schema_lookup(collection_value: dict[str, Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for prop_id, spec in collection_value.get("schema", {}).items():
        prop_name = (spec.get("name") or "").strip()
        if prop_name:
            lookup[prop_name] = prop_id
    return lookup


def find_watchlist_collection(record_map: dict[str, Any]) -> tuple[str, str, dict[str, str]]:
    collections = record_map.get("collection", {})
    collection_views = record_map.get("collection_view", {})

    best_collection_id = ""
    best_view_id = ""
    best_schema: dict[str, str] = {}

    for collection_id, entry in collections.items():
        value = entry.get("value", {})
        name = collection_name(value)
        schema = schema_lookup(value)
        if {"채널명", "채널 URL", "채널 ID"}.issubset(schema.keys()):
            best_collection_id = collection_id
            best_schema = schema
            if "모니터링 유튜브 채널" in name:
                break

    if not best_collection_id:
        raise RuntimeError("Notion 페이지에서 채널 collection을 찾지 못했습니다.")

    for view_id, entry in collection_views.items():
        value = entry.get("value", {})
        pointer = value.get("format", {}).get("collection_pointer", {})
        if pointer.get("id") == best_collection_id and value.get("type") == "table":
            best_view_id = view_id
            break

    if not best_view_id:
        raise RuntimeError("채널 collection의 table view를 찾지 못했습니다.")

    return best_collection_id, best_view_id, best_schema


def fetch_view_page_sort(record_map: dict[str, Any], view_id: str) -> list[str]:
    view_entry = record_map.get("collection_view", {}).get(view_id, {})
    return view_entry.get("value", {}).get("page_sort", [])


def extract_text_property(raw: Any) -> str:
    if not raw:
        return ""
    chunks: list[str] = []
    for row in raw:
        if isinstance(row, list):
            if row and isinstance(row[0], str):
                chunks.append(row[0])
                continue
            for item in row:
                if isinstance(item, list) and item and isinstance(item[0], str):
                    chunks.append(item[0])
                    break
                if isinstance(item, str):
                    chunks.append(item)
                    break
    return "".join(chunks).strip()


def sanitize_channel_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    matched = CHANNEL_ID_PATTERN.search(raw)
    if matched:
        return matched.group(0)
    return raw.strip("\"'[] ")


def sanitize_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    decoded = (
        raw.replace("\\u002F", "/")
        .replace("\\/", "/")
        .replace("&amp;", "&")
    )
    matched = YOUTUBE_URL_PATTERN.search(decoded)
    if matched:
        return matched.group(0).rstrip("/")
    return decoded.strip("\"'[] ")


def sanitize_name(value: Any) -> str:
    return str(value or "").replace("\\u0027", "'").strip().strip("\"'") or "이름 없는 채널"


def fetch_rows_via_sync(row_ids: list[str]) -> dict[str, Any]:
    if not row_ids:
        return {}
    return request_json(
        NOTION_SYNC_URL,
        method="POST",
        headers=notion_headers(),
        payload={
            "requests": [{"table": "block", "id": row_id, "version": -1} for row_id in row_ids]
        }
    )


def fetch_public_collection_size_hint(collection_id: str, view_id: str) -> int | None:
    try:
        payload = request_json(
            NOTION_QUERY_URL,
            method="POST",
            headers=notion_headers(),
            payload={
                "collection": {"id": collection_id},
                "collectionView": {"id": view_id},
                "loader": {
                    "type": "table",
                    "limit": 100,
                    "searchQuery": "",
                    "userTimeZone": "Asia/Seoul"
                },
                "query": {
                    "filter": {"operator": "and", "filters": []},
                    "sort": [],
                    "aggregate": []
                }
            }
        )
    except Exception:
        return None
    return payload.get("result", {}).get("sizeHint")


def parse_rows(sync_payload: dict[str, Any], schema: dict[str, str]) -> list[dict[str, Any]]:
    row_blocks = sync_payload.get("recordMap", {}).get("block", {})
    channels: list[dict[str, Any]] = []
    for row_id, entry in row_blocks.items():
        value = entry.get("value", {})
        props = value.get("properties", {})
        if not props:
            continue
        channels.append(
            {
                "youtube_channel_id": extract_text_property(props.get(schema.get("채널 ID", ""))),
                "name": extract_text_property(props.get(schema.get("채널명", ""))),
                "url": extract_text_property(props.get(schema.get("채널 URL", ""))),
                "category": extract_text_property(props.get(schema.get("카테고리", ""))) or "미분류",
                "language": "미지정",
                "is_active": extract_text_property(props.get(schema.get("활성화 상태", ""))).lower() in {"yes", "true", "1", "v"},
                "source": "notion",
                "last_synced_at": utcnow_iso(),
                "notes": "",
                "needs_review": False,
                "notion_row_id": row_id
            }
        )
    return channels


def extract_youtube_links_from_html(url: str) -> list[dict[str, Any]]:
    html = request_text(url, headers=notion_headers())
    normalized_html = html.replace("\\u002F", "/").replace("\\/", "/")
    patterns = [
        r"https?://(?:www\.)?youtube\.com/@[A-Za-z0-9._%+-]+(?:/videos)?",
        r"https?://(?:www\.)?youtube\.com/channel/[A-Za-z0-9_-]+",
        r"https?://(?:www\.)?youtube\.com/c/[A-Za-z0-9._%+-]+(?:/videos)?",
        r"https?://(?:www\.)?youtube\.com/user/[A-Za-z0-9._%+-]+(?:/videos)?"
    ]
    urls: list[str] = []
    for pattern in patterns:
        urls.extend(re.findall(pattern, normalized_html))
    deduped = sorted(set(urls))
    channels: list[dict[str, Any]] = []
    for url_value in deduped:
        name = url_value.rstrip("/").split("/")[-1].replace("@", "")
        channels.append(
            {
                "youtube_channel_id": "",
                "name": name,
                "url": url_value,
                "category": "미분류",
                "language": "미지정",
                "is_active": True,
                "source": "notion_public_html",
                "last_synced_at": utcnow_iso(),
                "notes": "",
                "needs_review": True
            }
        )
    return channels


def load_manual_watchlist(import_file: str) -> list[dict[str, Any]]:
    path = Path(import_file)
    if not path.exists():
        raise FileNotFoundError(f"watchlist import 파일이 없습니다: {import_file}")

    if path.suffix.lower() == ".json":
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
        channels = payload.get("channels", payload) if isinstance(payload, dict) else payload
        if not isinstance(channels, list):
            raise RuntimeError("JSON import 파일은 list 또는 {\"channels\": [...]} 형태여야 합니다.")
        return [normalize_channel(channel, source="manual_file") for channel in channels]

    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            return [normalize_channel(row, source="manual_file") for row in reader]

    raise RuntimeError("watchlist import 파일은 .json 또는 .csv 형식만 지원합니다.")


def normalize_channel(channel: dict[str, Any], *, source: str) -> dict[str, Any]:
    is_active_value = channel.get("is_active", channel.get("활성화 상태", True))
    if isinstance(is_active_value, str):
        is_active = is_active_value.strip().lower() in {"1", "true", "yes", "y", "v", "checked"}
    else:
        is_active = bool(is_active_value)

    return {
        "youtube_channel_id": sanitize_channel_id(channel.get("youtube_channel_id", channel.get("채널 ID", ""))),
        "name": sanitize_name(channel.get("name", channel.get("채널명", ""))),
        "url": sanitize_url(channel.get("url", channel.get("채널 URL", ""))),
        "category": str(channel.get("category", channel.get("카테고리", "미분류"))).strip() or "미분류",
        "language": str(channel.get("language", "미지정")).strip() or "미지정",
        "is_active": is_active,
        "source": channel.get("source", source),
        "last_synced_at": channel.get("last_synced_at", utcnow_iso()),
        "subscriber_count": int(channel.get("subscriber_count", 0) or 0),
        "uploads_per_week": int(channel.get("uploads_per_week", 0) or 0),
        "notes": str(channel.get("notes", "")).strip(),
        "needs_review": bool(channel.get("needs_review", False))
    }


def dedupe_channels(channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for channel in channels:
        normalized = normalize_channel(channel, source=str(channel.get("source", "manual")))
        key = normalized["youtube_channel_id"] or normalized["url"] or normalized["name"].lower()
        if not key:
            continue
        deduped[key] = normalized
    return list(deduped.values())


def import_watchlist(notion_url: str | None = None, import_file: str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    imported: list[dict[str, Any]] = []

    if import_file:
        imported.extend(load_manual_watchlist(import_file))

    notion_source = notion_url or os.getenv("NOTION_SOURCE_URL")
    if notion_source:
        collection_debug: tuple[str, str, int | None] | None = None
        try:
            page_id = parse_page_id(notion_source)
            record_payload = fetch_page_record_map(page_id)
            record_map = record_payload.get("recordMap", {})
            collection_id, view_id, schema = find_watchlist_collection(record_map)
            row_ids = fetch_view_page_sort(record_map, view_id)
            collection_debug = (collection_id, view_id, fetch_public_collection_size_hint(collection_id, view_id))
            if row_ids:
                sync_payload = fetch_rows_via_sync(row_ids)
                notion_rows = parse_rows(sync_payload, schema)
                if notion_rows:
                    imported.extend(notion_rows)
                else:
                    warnings.append("공개 Notion DB의 row 속성 값을 직접 읽지 못해 공개 HTML 링크 추출로 전환합니다.")
        except Exception as error:
            warnings.append(f"공개 Notion collection 해석에 실패했습니다: {error}")

        if not imported:
            html_rows = extract_youtube_links_from_html(notion_source)
            if html_rows:
                warnings.append("공개 HTML에서 YouTube 링크만 가져왔습니다. 채널 ID와 카테고리는 검토가 필요합니다.")
                imported.extend(html_rows)
            elif collection_debug:
                collection_id, view_id, size_hint = collection_debug
                warnings.append(
                    "공개 Notion DB는 collection/view까지는 읽었지만 row 속성 값이 비어 있어 자동 동기화를 완료하지 못했습니다. "
                    f"(collection={collection_id}, view={view_id}, visible_rows={size_hint or 'unknown'})"
                )

    deduped = dedupe_channels(imported)
    if not deduped:
        raise RuntimeError("watchlist를 생성할 수 없습니다. 공개 Notion row 값이 비어 있거나, import 파일이 필요합니다.")
    return deduped, warnings
