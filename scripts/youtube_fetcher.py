from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

from common import chunks, parse_datetime, request_json, utcnow_iso


YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?youtube\.com/(?:@[\w.%+-]+(?:/videos)?|channel/[A-Za-z0-9_-]+|c/[\w.%+-]+(?:/videos)?|user/[\w.%+-]+(?:/videos)?)",
    re.IGNORECASE
)
CHANNEL_ID_PATTERN = re.compile(r"UC[A-Za-z0-9_-]{20,}")
DEFAULT_LOOKBACK_HOURS = 24


def youtube_get(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY가 설정되지 않았습니다.")
    merged = {"key": api_key, **params}
    return request_json(f"{YOUTUBE_API_BASE}/{endpoint}", params=merged)


def extract_channel_reference(url: str) -> tuple[str | None, str | None]:
    if not url:
        return None, None
    matched_url = YOUTUBE_URL_PATTERN.search(url)
    normalized_url = matched_url.group(0) if matched_url else url
    channel_match = re.search(r"/channel/([A-Za-z0-9_-]+)", normalized_url)
    if channel_match:
        return channel_match.group(1), None
    handle_match = re.search(r"/@([A-Za-z0-9._%-]+)", normalized_url)
    if handle_match:
        return None, handle_match.group(1)
    return None, None


def resolve_channel_ids(watchlist: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for channel in watchlist:
        raw_channel_id = channel.get("youtube_channel_id") or ""
        channel_id_match = CHANNEL_ID_PATTERN.search(str(raw_channel_id))
        channel_id = channel_id_match.group(0) if channel_id_match else ""
        if channel_id:
            channel["youtube_channel_id"] = channel_id
            resolved.append(channel)
            continue

        from_url, handle = extract_channel_reference(channel.get("url", ""))
        if from_url:
            channel["youtube_channel_id"] = from_url
            resolved.append(channel)
            continue

        if handle:
            search_payload = youtube_get(
                "search",
                {
                    "part": "snippet",
                    "type": "channel",
                    "q": f"@{handle}",
                    "maxResults": 1
                }
            )
            items = search_payload.get("items", [])
            if items:
                channel["youtube_channel_id"] = items[0].get("snippet", {}).get("channelId", "")
        resolved.append(channel)
    return resolved


def fetch_channel_metadata(channel_ids: list[str]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    if not channel_ids:
        return metadata
    for batch in chunks(channel_ids, 50):
        payload = youtube_get(
            "channels",
            {
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(batch),
                "maxResults": 50
            }
        )
        for item in payload.get("items", []):
            metadata[item["id"]] = item
    return metadata


def fetch_recent_playlist_video_ids(uploads_playlist_id: str, max_results: int) -> list[str]:
    video_ids: list[str] = []
    next_page_token = None
    while len(video_ids) < max_results:
        payload = youtube_get(
            "playlistItems",
            {
                "part": "snippet,contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": min(50, max_results - len(video_ids)),
                "pageToken": next_page_token
            }
        )
        items = payload.get("items", [])
        for item in items:
            video_id = item.get("contentDetails", {}).get("videoId")
            if video_id:
                video_ids.append(video_id)
        next_page_token = payload.get("nextPageToken")
        if not next_page_token or not items:
            break
    return video_ids


def fetch_video_details(video_ids: list[str]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for batch in chunks(video_ids, 50):
        payload = youtube_get(
            "videos",
            {
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(batch),
                "maxResults": 50
            }
        )
        details.extend(payload.get("items", []))
    return details


def fetch_top_comments(video_id: str, limit: int = 5) -> list[dict[str, Any]]:
    try:
        payload = youtube_get(
            "commentThreads",
            {
                "part": "snippet,replies",
                "videoId": video_id,
                "maxResults": min(max(limit, 1), 100),
                "order": "relevance",
                "textFormat": "plainText"
            }
        )
    except RuntimeError:
        return []

    comments: list[dict[str, Any]] = []
    for item in payload.get("items", []):
        comment = item.get("snippet", {}).get("topLevelComment", {})
        snippet = comment.get("snippet", {})
        text = str(snippet.get("textDisplay") or "").strip()
        if not text:
            continue
        comments.append(
            {
                "comment_id": comment.get("id") or f"{video_id}-{len(comments) + 1}",
                "author": snippet.get("authorDisplayName", ""),
                "text": text,
                "like_count": int(snippet.get("likeCount", 0) or 0),
                "reply_count": int(item.get("snippet", {}).get("totalReplyCount", 0) or 0),
                "published_at": snippet.get("publishedAt"),
            }
        )
    comments.sort(
        key=lambda item: (
            int(item.get("like_count", 0) or 0),
            int(item.get("reply_count", 0) or 0),
            item.get("published_at") or "",
        ),
        reverse=True,
    )
    return comments[:limit]


def parse_duration_seconds(value: str | None) -> int:
    if not value:
        return 0
    hours = minutes = seconds = 0
    hour_match = re.search(r"(\d+)H", value)
    minute_match = re.search(r"(\d+)M", value)
    second_match = re.search(r"(\d+)S", value)
    if hour_match:
        hours = int(hour_match.group(1))
    if minute_match:
        minutes = int(minute_match.group(1))
    if second_match:
        seconds = int(second_match.group(1))
    return hours * 3600 + minutes * 60 + seconds


def is_within_lookback(published_at: str | None, *, lookback_hours: int) -> bool:
    published = parse_datetime(published_at)
    if not published:
        return False
    hours = max((datetime.now(timezone.utc) - published.astimezone(timezone.utc)).total_seconds() / 3600, 0)
    return hours <= lookback_hours


def refresh_watchlist_metadata(watchlist: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resolved_watchlist = resolve_channel_ids([dict(channel) for channel in watchlist])
    channel_ids = [channel.get("youtube_channel_id") for channel in resolved_watchlist if channel.get("youtube_channel_id")]
    metadata = fetch_channel_metadata(channel_ids)
    refreshed: list[dict[str, Any]] = []

    for channel in resolved_watchlist:
        channel_id = channel.get("youtube_channel_id")
        item = metadata.get(channel_id, {})
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})

        refreshed.append(
            {
                **channel,
                "youtube_channel_id": channel_id or channel.get("youtube_channel_id", ""),
                "name": channel.get("name") or snippet.get("title") or "이름 없는 채널",
                "url": channel.get("url") or (f"https://www.youtube.com/channel/{channel_id}" if channel_id else ""),
                "subscriber_count": int(statistics.get("subscriberCount", channel.get("subscriber_count", 0)) or 0),
                "channel_view_count": int(statistics.get("viewCount", channel.get("channel_view_count", 0)) or 0),
                "video_count": int(statistics.get("videoCount", channel.get("video_count", 0)) or 0),
                "description": snippet.get("description", channel.get("description", "")),
                "country": snippet.get("country", channel.get("country", "")),
                "published_at": snippet.get("publishedAt", channel.get("published_at")),
                "thumbnail_url": (
                    snippet.get("thumbnails", {}).get("high", {}).get("url")
                    or snippet.get("thumbnails", {}).get("medium", {}).get("url")
                    or snippet.get("thumbnails", {}).get("default", {}).get("url")
                    or channel.get("thumbnail_url", "")
                ),
                "last_synced_at": utcnow_iso()
            }
        )

    return refreshed


def merge_video_payload(
    watchlist: list[dict[str, Any]],
    existing_videos: list[dict[str, Any]],
    *,
    max_results_per_channel: int = 8
) -> list[dict[str, Any]]:
    lookback_hours = int(os.getenv("VIDEO_LOOKBACK_HOURS", str(DEFAULT_LOOKBACK_HOURS)) or DEFAULT_LOOKBACK_HOURS)
    resolved_watchlist = resolve_channel_ids(watchlist)
    active_channels = [channel for channel in resolved_watchlist if channel.get("is_active")]
    allowed_channel_ids = {
        channel.get("youtube_channel_id")
        for channel in resolved_watchlist
        if channel.get("youtube_channel_id")
    }
    channel_ids = [channel["youtube_channel_id"] for channel in active_channels if channel.get("youtube_channel_id")]
    channel_metadata = fetch_channel_metadata(channel_ids)

    previous_by_id = {
        video.get("video_id"): video
        for video in existing_videos
        if video.get("video_id") and video.get("channel_id") in allowed_channel_ids
    }
    merged: dict[str, dict[str, Any]] = previous_by_id.copy()

    for channel in active_channels:
        channel_id = channel.get("youtube_channel_id")
        metadata = channel_metadata.get(channel_id)
        if not metadata:
            continue
        uploads_playlist_id = metadata.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        if not uploads_playlist_id:
            continue

        recent_video_ids = fetch_recent_playlist_video_ids(uploads_playlist_id, max_results=max_results_per_channel)
        for video_item in fetch_video_details(recent_video_ids):
            video_id = video_item.get("id")
            snippet = video_item.get("snippet", {})
            statistics = video_item.get("statistics", {})
            detail = video_item.get("contentDetails", {})
            published_at = snippet.get("publishedAt")
            if not is_within_lookback(published_at, lookback_hours=lookback_hours):
                continue
            channel_subscriber_count = int(metadata.get("statistics", {}).get("subscriberCount", 0) or 0)
            thumbnails = snippet.get("thumbnails", {})
            thumbnail_url = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url")
                or ""
            )

            merged_video = {
                **previous_by_id.get(video_id, {}),
                "video_id": video_id,
                "channel_id": channel_id,
                "channel_name": snippet.get("channelTitle", "") or metadata.get("snippet", {}).get("title", ""),
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": published_at,
                "analysis_date": utcnow_iso(),
                "duration_seconds": parse_duration_seconds(detail.get("duration")),
                "view_count": int(statistics.get("viewCount", 0) or 0),
                "like_count": int(statistics.get("likeCount", 0) or 0),
                "comment_count": int(statistics.get("commentCount", 0) or 0),
                "channel_subscriber_count": channel_subscriber_count,
                "thumbnail_url": thumbnail_url,
                "video_url": f"https://www.youtube.com/watch?v={video_id}",
                "engagement_rate": (
                    (int(statistics.get("likeCount", 0) or 0) + int(statistics.get("commentCount", 0) or 0))
                    / max(int(statistics.get("viewCount", 0) or 0), 1)
                ),
                "format": previous_by_id.get(video_id, {}).get("format", "미분류"),
                "hook_type": previous_by_id.get(video_id, {}).get("hook_type", "미분류"),
                "title_pattern": previous_by_id.get(video_id, {}).get("title_pattern", "패턴 미분류"),
                "topic_tags": previous_by_id.get(video_id, {}).get("topic_tags", []),
                "keywords": previous_by_id.get(video_id, {}).get("keywords", []),
                "tools": previous_by_id.get(video_id, {}).get("tools", []),
                "one_line_summary": previous_by_id.get(video_id, {}).get("one_line_summary", ""),
                "why_it_works": previous_by_id.get(video_id, {}).get("why_it_works", ""),
                "recommendation": previous_by_id.get(video_id, {}).get("recommendation", ""),
                "flow": previous_by_id.get(video_id, {}).get("flow", []),
                "claims": previous_by_id.get(video_id, {}).get("claims", []),
                "transcript_highlights": previous_by_id.get(video_id, {}).get("transcript_highlights", []),
                "transcript_status": previous_by_id.get(video_id, {}).get("transcript_status", "pending"),
                "transcript_source": previous_by_id.get(video_id, {}).get("transcript_source", "none"),
                "transcript_language": previous_by_id.get(video_id, {}).get("transcript_language", ""),
                "transcript_text": previous_by_id.get(video_id, {}).get("transcript_text", ""),
                "top_comments": previous_by_id.get(video_id, {}).get("top_comments", fetch_top_comments(video_id)),
                "is_recent": True
            }
            merged[video_id] = merged_video

    merged_list = [
        video
        for video in merged.values()
        if is_within_lookback(video.get("published_at"), lookback_hours=lookback_hours)
    ]
    merged_list.sort(key=lambda item: item.get("published_at") or "", reverse=True)
    return merged_list
