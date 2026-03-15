from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common import DATA_DIR, parse_datetime, slugify, utcnow_iso, write_json


DB_PATH = DATA_DIR / "youtube_insider.db"


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS channels (
                channel_key TEXT PRIMARY KEY,
                youtube_channel_id TEXT,
                name TEXT NOT NULL,
                url TEXT,
                category TEXT,
                language TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                subscriber_count INTEGER NOT NULL DEFAULT 0,
                channel_view_count INTEGER NOT NULL DEFAULT 0,
                video_count INTEGER NOT NULL DEFAULT 0,
                description TEXT,
                country TEXT,
                published_at TEXT,
                thumbnail_url TEXT,
                last_synced_at TEXT,
                source TEXT,
                notes TEXT DEFAULT ''
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_channels_youtube_id
                ON channels(youtube_channel_id) WHERE youtube_channel_id IS NOT NULL AND youtube_channel_id != '';

            CREATE INDEX IF NOT EXISTS idx_channels_name ON channels(name);
            CREATE INDEX IF NOT EXISTS idx_channels_category ON channels(category);
            CREATE INDEX IF NOT EXISTS idx_channels_active ON channels(is_active);

            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                channel_key TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                published_at TEXT,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                view_count INTEGER NOT NULL DEFAULT 0,
                like_count INTEGER NOT NULL DEFAULT 0,
                comment_count INTEGER NOT NULL DEFAULT 0,
                engagement_rate REAL NOT NULL DEFAULT 0,
                thumbnail_url TEXT,
                video_url TEXT,
                format TEXT,
                hook_type TEXT,
                title_pattern TEXT,
                topic_tags_json TEXT,
                keywords_json TEXT,
                tools_json TEXT,
                one_line_summary TEXT,
                why_it_works TEXT,
                recommendation TEXT,
                flow_json TEXT,
                claims_json TEXT,
                transcript_status TEXT,
                transcript_source TEXT,
                transcript_language TEXT,
                transcript_text TEXT,
                transcript_highlights_json TEXT,
                analysis_date TEXT,
                channel_name TEXT,
                FOREIGN KEY(channel_key) REFERENCES channels(channel_key) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_videos_published_at ON videos(published_at);
            CREATE INDEX IF NOT EXISTS idx_videos_channel_key ON videos(channel_key);
            CREATE INDEX IF NOT EXISTS idx_videos_title ON videos(title);

            CREATE TABLE IF NOT EXISTS video_comments (
                video_id TEXT NOT NULL,
                comment_id TEXT NOT NULL,
                author TEXT,
                text TEXT,
                like_count INTEGER NOT NULL DEFAULT 0,
                reply_count INTEGER NOT NULL DEFAULT 0,
                published_at TEXT,
                PRIMARY KEY(video_id, comment_id),
                FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_video_comments_video_id ON video_comments(video_id);
            CREATE INDEX IF NOT EXISTS idx_video_comments_like_count ON video_comments(like_count DESC);

            CREATE TABLE IF NOT EXISTS daily_digests (
                digest_date TEXT PRIMARY KEY,
                generated_at TEXT NOT NULL,
                summary TEXT,
                summary_points_json TEXT,
                action_chips_json TEXT,
                creator_takeaway TEXT,
                title_suggestions_json TEXT,
                recommendations_json TEXT,
                topic_clusters_json TEXT,
                video_highlights_json TEXT,
                telegram_preview TEXT,
                video_count INTEGER NOT NULL DEFAULT 0,
                total_recent_video_count INTEGER NOT NULL DEFAULT 0,
                focus_scope TEXT,
                average_view_count REAL DEFAULT 0,
                average_engagement_rate REAL DEFAULT 0,
                average_like_count REAL DEFAULT 0,
                average_comment_count REAL DEFAULT 0,
                best_video_id TEXT,
                best_topic TEXT
            );
            """
        )
        ensure_column(connection, "daily_digests", "summary_points_json", "TEXT")
        ensure_column(connection, "daily_digests", "action_chips_json", "TEXT")
        connection.commit()


def ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column in existing:
        return
    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def dumps_json(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def loads_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def normalize_channel_key(channel: dict[str, Any], existing_keys: set[str]) -> str:
    base_key = (
        str(channel.get("channel_key") or "").strip()
        or str(channel.get("youtube_channel_id") or "").strip()
        or str(channel.get("url") or "").strip()
        or str(channel.get("name") or "").strip()
    )
    normalized = slugify(base_key)
    candidate = normalized
    suffix = 2
    while candidate in existing_keys:
        candidate = f"{normalized}-{suffix}"
        suffix += 1
    existing_keys.add(candidate)
    return candidate


def assign_channel_keys(channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT channel_key, youtube_channel_id, url, name FROM channels"
        ).fetchall()

    by_youtube_id = {
        str(row["youtube_channel_id"] or "").strip(): row["channel_key"]
        for row in rows
        if str(row["youtube_channel_id"] or "").strip()
    }
    by_url = {
        str(row["url"] or "").rstrip("/"): row["channel_key"]
        for row in rows
        if str(row["url"] or "").strip()
    }
    existing_keys = {row["channel_key"] for row in rows}
    assigned: list[dict[str, Any]] = []

    for raw_channel in channels:
        channel = dict(raw_channel)
        youtube_channel_id = str(channel.get("youtube_channel_id") or "").strip()
        url = str(channel.get("url") or "").strip().rstrip("/")
        existing_key = (
            str(channel.get("channel_key") or "").strip()
            or by_youtube_id.get(youtube_channel_id)
            or by_url.get(url)
        )
        if existing_key:
            channel["channel_key"] = existing_key
            existing_keys.add(existing_key)
        else:
            channel["channel_key"] = normalize_channel_key(channel, existing_keys)
        assigned.append(channel)
    return assigned


def upsert_channels(channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared_channels = assign_channel_keys(channels)
    with get_connection() as connection:
        for channel in prepared_channels:
            connection.execute(
                """
                INSERT INTO channels (
                    channel_key, youtube_channel_id, name, url, category, language, is_active,
                    subscriber_count, channel_view_count, video_count, description, country,
                    published_at, thumbnail_url, last_synced_at, source, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel_key) DO UPDATE SET
                    youtube_channel_id = excluded.youtube_channel_id,
                    name = excluded.name,
                    url = excluded.url,
                    category = excluded.category,
                    language = excluded.language,
                    is_active = excluded.is_active,
                    subscriber_count = excluded.subscriber_count,
                    channel_view_count = excluded.channel_view_count,
                    video_count = excluded.video_count,
                    description = excluded.description,
                    country = excluded.country,
                    published_at = excluded.published_at,
                    thumbnail_url = excluded.thumbnail_url,
                    last_synced_at = excluded.last_synced_at,
                    source = excluded.source,
                    notes = COALESCE(NULLIF(excluded.notes, ''), channels.notes)
                """,
                (
                    channel.get("channel_key"),
                    channel.get("youtube_channel_id"),
                    channel.get("name"),
                    channel.get("url"),
                    channel.get("category", "미분류"),
                    channel.get("language", "미지정"),
                    1 if channel.get("is_active", True) else 0,
                    int(channel.get("subscriber_count", 0) or 0),
                    int(channel.get("channel_view_count", 0) or 0),
                    int(channel.get("video_count", 0) or 0),
                    channel.get("description", ""),
                    channel.get("country", ""),
                    channel.get("published_at"),
                    channel.get("thumbnail_url", ""),
                    channel.get("last_synced_at", utcnow_iso()),
                    channel.get("source", "manual"),
                    channel.get("notes", ""),
                ),
            )
        connection.commit()
    return prepared_channels


def load_channels(*, active_only: bool = False) -> list[dict[str, Any]]:
    query = "SELECT * FROM channels"
    params: tuple[Any, ...] = ()
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY is_active DESC, subscriber_count DESC, name COLLATE NOCASE"
    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict_from_channel_row(row) for row in rows]


def channel_key_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for channel in load_channels():
        channel_key = channel.get("channel_key")
        if not channel_key:
            continue
        youtube_channel_id = str(channel.get("youtube_channel_id") or "").strip()
        url = str(channel.get("url") or "").strip().rstrip("/")
        name = str(channel.get("name") or "").strip().lower()
        if youtube_channel_id:
            lookup[youtube_channel_id] = channel_key
        if url:
            lookup[url] = channel_key
        if name:
            lookup[name] = channel_key
    return lookup


def dict_from_channel_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["is_active"] = bool(item.get("is_active", 0))
    return item


def upsert_videos(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lookup = channel_key_lookup()
    persisted: list[dict[str, Any]] = []
    with get_connection() as connection:
        for raw_video in videos:
            video = dict(raw_video)
            channel_key = (
                video.get("channel_key")
                or lookup.get(str(video.get("channel_id") or "").strip())
                or lookup.get(str(video.get("channel_url") or "").strip().rstrip("/"))
                or lookup.get(str(video.get("channel_name") or "").strip().lower())
            )
            if not channel_key:
                continue
            video["channel_key"] = channel_key
            connection.execute(
                """
                INSERT INTO videos (
                    video_id, channel_key, title, description, published_at, duration_seconds,
                    view_count, like_count, comment_count, engagement_rate, thumbnail_url, video_url,
                    format, hook_type, title_pattern, topic_tags_json, keywords_json, tools_json,
                    one_line_summary, why_it_works, recommendation, flow_json, claims_json,
                    transcript_status, transcript_source, transcript_language, transcript_text,
                    transcript_highlights_json, analysis_date, channel_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    channel_key = excluded.channel_key,
                    title = excluded.title,
                    description = excluded.description,
                    published_at = excluded.published_at,
                    duration_seconds = excluded.duration_seconds,
                    view_count = excluded.view_count,
                    like_count = excluded.like_count,
                    comment_count = excluded.comment_count,
                    engagement_rate = excluded.engagement_rate,
                    thumbnail_url = excluded.thumbnail_url,
                    video_url = excluded.video_url,
                    format = excluded.format,
                    hook_type = excluded.hook_type,
                    title_pattern = excluded.title_pattern,
                    topic_tags_json = excluded.topic_tags_json,
                    keywords_json = excluded.keywords_json,
                    tools_json = excluded.tools_json,
                    one_line_summary = excluded.one_line_summary,
                    why_it_works = excluded.why_it_works,
                    recommendation = excluded.recommendation,
                    flow_json = excluded.flow_json,
                    claims_json = excluded.claims_json,
                    transcript_status = excluded.transcript_status,
                    transcript_source = excluded.transcript_source,
                    transcript_language = excluded.transcript_language,
                    transcript_text = excluded.transcript_text,
                    transcript_highlights_json = excluded.transcript_highlights_json,
                    analysis_date = excluded.analysis_date,
                    channel_name = excluded.channel_name
                """,
                (
                    video.get("video_id"),
                    channel_key,
                    video.get("title", "제목 없음"),
                    video.get("description", ""),
                    video.get("published_at"),
                    int(video.get("duration_seconds", 0) or 0),
                    int(video.get("view_count", 0) or 0),
                    int(video.get("like_count", 0) or 0),
                    int(video.get("comment_count", 0) or 0),
                    float(video.get("engagement_rate", 0) or 0),
                    video.get("thumbnail_url", ""),
                    video.get("video_url", ""),
                    video.get("format", "미분류"),
                    video.get("hook_type", "미분류"),
                    video.get("title_pattern", "패턴 미분류"),
                    dumps_json(video.get("topic_tags", [])),
                    dumps_json(video.get("keywords", [])),
                    dumps_json(video.get("tools", [])),
                    video.get("one_line_summary", ""),
                    video.get("why_it_works", ""),
                    video.get("recommendation", ""),
                    dumps_json(video.get("flow", [])),
                    dumps_json(video.get("claims", [])),
                    video.get("transcript_status", "unknown"),
                    video.get("transcript_source", "none"),
                    video.get("transcript_language", ""),
                    video.get("transcript_text", ""),
                    dumps_json(video.get("transcript_highlights", [])),
                    video.get("analysis_date", utcnow_iso()),
                    video.get("channel_name", ""),
                ),
            )
            replace_video_comments(connection, video.get("video_id", ""), video.get("top_comments", []))
            persisted.append(video)
        connection.commit()
    return persisted


def replace_video_comments(connection: sqlite3.Connection, video_id: str, comments: list[Any]) -> None:
    if not video_id:
        return
    connection.execute("DELETE FROM video_comments WHERE video_id = ?", (video_id,))
    for index, raw_comment in enumerate(comments or []):
        if isinstance(raw_comment, dict):
            comment = raw_comment
        else:
            comment = {"text": str(raw_comment or "").strip()}
        text = str(comment.get("text") or "").strip()
        if not text:
            continue
        comment_id = str(comment.get("comment_id") or f"{video_id}-{index + 1}")
        connection.execute(
            """
            INSERT OR REPLACE INTO video_comments (
                video_id, comment_id, author, text, like_count, reply_count, published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                comment_id,
                str(comment.get("author") or ""),
                text,
                int(comment.get("like_count", 0) or 0),
                int(comment.get("reply_count", 0) or 0),
                comment.get("published_at"),
            ),
        )


def upsert_digest(digest: dict[str, Any]) -> None:
    generated_at = digest.get("generated_at", utcnow_iso())
    digest_date = generated_at[:10]
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO daily_digests (
                digest_date, generated_at, summary, summary_points_json, action_chips_json, creator_takeaway, title_suggestions_json,
                recommendations_json, topic_clusters_json, video_highlights_json, telegram_preview,
                video_count, total_recent_video_count, focus_scope, average_view_count,
                average_engagement_rate, average_like_count, average_comment_count, best_video_id, best_topic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(digest_date) DO UPDATE SET
                generated_at = excluded.generated_at,
                summary = excluded.summary,
                summary_points_json = excluded.summary_points_json,
                action_chips_json = excluded.action_chips_json,
                creator_takeaway = excluded.creator_takeaway,
                title_suggestions_json = excluded.title_suggestions_json,
                recommendations_json = excluded.recommendations_json,
                topic_clusters_json = excluded.topic_clusters_json,
                video_highlights_json = excluded.video_highlights_json,
                telegram_preview = excluded.telegram_preview,
                video_count = excluded.video_count,
                total_recent_video_count = excluded.total_recent_video_count,
                focus_scope = excluded.focus_scope,
                average_view_count = excluded.average_view_count,
                average_engagement_rate = excluded.average_engagement_rate,
                average_like_count = excluded.average_like_count,
                average_comment_count = excluded.average_comment_count,
                best_video_id = excluded.best_video_id,
                best_topic = excluded.best_topic
            """,
            (
                digest_date,
                generated_at,
                digest.get("summary", ""),
                dumps_json(digest.get("summary_points", [])),
                dumps_json(digest.get("action_chips", [])),
                digest.get("creator_takeaway", ""),
                dumps_json(digest.get("title_suggestions", [])),
                dumps_json(digest.get("recommendations", [])),
                dumps_json(digest.get("topic_clusters", [])),
                dumps_json(digest.get("video_highlights", [])),
                digest.get("telegram_preview", ""),
                int(digest.get("video_count", 0) or 0),
                int(digest.get("total_recent_video_count", 0) or 0),
                digest.get("focus_scope", "unknown"),
                float(digest.get("average_view_count", 0) or 0),
                float(digest.get("average_engagement_rate", 0) or 0),
                float(digest.get("average_like_count", 0) or 0),
                float(digest.get("average_comment_count", 0) or 0),
                digest.get("best_video_id", ""),
                digest.get("best_topic", ""),
            ),
        )
        connection.commit()


def latest_digest() -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM daily_digests ORDER BY digest_date DESC LIMIT 1"
        ).fetchone()
    if not row:
        return {}
    return dict_from_digest_row(row)


def dict_from_digest_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["summary_points"] = loads_json(item.pop("summary_points_json", None), [])
    item["action_chips"] = loads_json(item.pop("action_chips_json", None), [])
    item["title_suggestions"] = loads_json(item.pop("title_suggestions_json", None), [])
    item["recommendations"] = loads_json(item.pop("recommendations_json", None), [])
    item["topic_clusters"] = loads_json(item.pop("topic_clusters_json", None), [])
    item["video_highlights"] = loads_json(item.pop("video_highlights_json", None), [])
    return item


def dict_from_video_row(row: sqlite3.Row | dict[str, Any], comments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    item = dict(row)
    item["topic_tags"] = loads_json(item.pop("topic_tags_json", None), [])
    item["keywords"] = loads_json(item.pop("keywords_json", None), [])
    item["tools"] = loads_json(item.pop("tools_json", None), [])
    item["flow"] = loads_json(item.pop("flow_json", None), [])
    item["claims"] = loads_json(item.pop("claims_json", None), [])
    item["transcript_highlights"] = loads_json(item.pop("transcript_highlights_json", None), [])
    if comments is not None:
        item["top_comments"] = comments
    return item


def load_comments_for_video_ids(video_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not video_ids:
        return {}
    placeholders = ",".join("?" for _ in video_ids)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM video_comments
            WHERE video_id IN ({placeholders})
            ORDER BY like_count DESC, reply_count DESC, published_at DESC
            """,
            tuple(video_ids),
        ).fetchall()

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["video_id"]].append(dict(row))
    return grouped


def load_videos(*, since_hours: int | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM videos"
    params: list[Any] = []
    if since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        query += " WHERE published_at >= ?"
        params.append(cutoff.replace(microsecond=0).isoformat())
    query += " ORDER BY published_at DESC"

    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
    video_ids = [row["video_id"] for row in rows]
    comments_by_video_id = load_comments_for_video_ids(video_ids)
    return [
        dict_from_video_row(row, comments=comments_by_video_id.get(row["video_id"], [])[:5])
        for row in rows
    ]


def group_videos_by_date(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for video in videos:
        published_at = parse_datetime(video.get("published_at"))
        date_key = published_at.astimezone(timezone.utc).date().isoformat() if published_at else "날짜 없음"
        grouped[date_key].append(video)
    results: list[dict[str, Any]] = []
    today = datetime.now(timezone.utc).date().isoformat()
    for date_key in sorted(grouped.keys(), reverse=True):
        results.append(
            {
                "date": date_key,
                "label": date_key,
                "is_today": date_key == today,
                "video_count": len(grouped[date_key]),
                "videos": grouped[date_key],
            }
        )
    return results


def build_channel_detail(channel_key: str) -> dict[str, Any]:
    with get_connection() as connection:
        channel_row = connection.execute(
            "SELECT * FROM channels WHERE channel_key = ?",
            (channel_key,),
        ).fetchone()
        if not channel_row:
            return {}

        recent_video_rows = connection.execute(
            """
            SELECT *
            FROM videos
            WHERE channel_key = ?
            ORDER BY published_at DESC
            LIMIT 3
            """,
            (channel_key,),
        ).fetchall()

        topic_rows = connection.execute(
            """
            SELECT topic_tags_json, COUNT(*) AS video_count
            FROM videos
            WHERE channel_key = ?
            GROUP BY topic_tags_json
            ORDER BY video_count DESC
            LIMIT 5
            """,
            (channel_key,),
        ).fetchall()

        comment_rows = connection.execute(
            """
            SELECT vc.*
            FROM video_comments vc
            JOIN videos v ON v.video_id = vc.video_id
            WHERE v.channel_key = ?
            ORDER BY vc.like_count DESC, vc.reply_count DESC, vc.published_at DESC
            LIMIT 5
            """,
            (channel_key,),
        ).fetchall()

    channel = dict_from_channel_row(channel_row)
    recent_videos = [dict_from_video_row(row, comments=[]) for row in recent_video_rows]
    top_topics: list[dict[str, Any]] = []
    for row in topic_rows:
        tags = loads_json(row["topic_tags_json"], [])
        for tag in tags[:3]:
            top_topics.append({"label": tag, "video_count": row["video_count"]})
    deduped_topics: dict[str, dict[str, Any]] = {}
    for topic in top_topics:
        existing = deduped_topics.get(topic["label"])
        if not existing or topic["video_count"] > existing["video_count"]:
            deduped_topics[topic["label"]] = topic

    return {
        "channel": channel,
        "recent_videos": recent_videos,
        "top_topics": list(deduped_topics.values())[:5],
        "recent_comments": [dict(row) for row in comment_rows],
    }


def search_dashboard(query: str) -> dict[str, Any]:
    normalized = f"%{query.strip().lower()}%"
    with get_connection() as connection:
        channel_rows = connection.execute(
            """
            SELECT *
            FROM channels
            WHERE lower(name) LIKE ? OR lower(url) LIKE ? OR lower(category) LIKE ?
            ORDER BY is_active DESC, subscriber_count DESC, name COLLATE NOCASE
            LIMIT 50
            """,
            (normalized, normalized, normalized),
        ).fetchall()
        video_rows = connection.execute(
            """
            SELECT *
            FROM videos
            WHERE lower(title) LIKE ?
               OR lower(description) LIKE ?
               OR lower(one_line_summary) LIKE ?
               OR lower(COALESCE(topic_tags_json, '')) LIKE ?
               OR lower(COALESCE(tools_json, '')) LIKE ?
               OR lower(COALESCE(transcript_text, '')) LIKE ?
            ORDER BY published_at DESC
            LIMIT 200
            """,
            (normalized, normalized, normalized, normalized, normalized, normalized),
        ).fetchall()

    video_ids = [row["video_id"] for row in video_rows]
    comments_by_video_id = load_comments_for_video_ids(video_ids)
    videos = [
        dict_from_video_row(row, comments=comments_by_video_id.get(row["video_id"], [])[:5])
        for row in video_rows
    ]
    return {
        "channels": [dict_from_channel_row(row) for row in channel_rows],
        "videos": videos,
        "grouped_by_date": group_videos_by_date(videos),
    }


def export_snapshot_files() -> dict[str, Any]:
    channels = load_channels()
    videos = load_videos()
    digest = latest_digest()

    watchlist_payload = {
        "generated_at": utcnow_iso(),
        "source": "sqlite_export",
        "channels": channels,
    }
    videos_payload = {
        "generated_at": utcnow_iso(),
        "source": "sqlite_export",
        "video_count": len(videos),
        "videos": videos,
    }
    digest_payload = digest

    write_json(DATA_DIR / "watchlist.json", watchlist_payload)
    write_json(DATA_DIR / "videos.json", videos_payload)
    write_json(DATA_DIR / "digest.json", digest_payload)

    return {
        "watchlist": watchlist_payload,
        "videos": videos_payload,
        "digest": digest_payload,
    }


def build_bootstrap_payload() -> dict[str, Any]:
    channels = load_channels()
    all_videos = load_videos()
    today_videos = load_videos(since_hours=24)
    digest = latest_digest()
    return {
        "meta": {
            "generated_at": utcnow_iso(),
            "database_path": str(Path(DB_PATH).name),
            "channel_count": len(channels),
            "today_video_count": len(today_videos),
            "notion_source_url": os.getenv("NOTION_SOURCE_URL", ""),
        },
        "channels": channels,
        "videos": all_videos,
        "todayVideos": today_videos,
        "groupedHistory": group_videos_by_date(all_videos),
        "digest": digest,
    }
