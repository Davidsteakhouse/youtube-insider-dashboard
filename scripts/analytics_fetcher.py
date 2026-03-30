from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any

from common import DATA_DIR, KST, read_json, write_json


TOKEN_URL = "https://oauth2.googleapis.com/token"
ANALYTICS_BASE = "https://youtubeanalytics.googleapis.com/v2"
MY_CHANNEL_PATH = DATA_DIR / "my_channel.json"


def _exchange_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["access_token"]


def _analytics_get(params: dict[str, Any], access_token: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{ANALYTICS_BASE}/reports?{query}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"YouTube Analytics API 실패: HTTP {exc.code} {detail[:300]}") from exc


def _parse_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    col_headers = [h["name"] for h in (response.get("columnHeaders") or [])]
    return [dict(zip(col_headers, row)) for row in (response.get("rows") or [])]


def fetch_channel_daily(access_token: str, days: int = 7) -> list[dict[str, Any]]:
    """채널 전체 일별 지표 (최근 N일)."""
    end = datetime.now(KST).date()
    start = end - timedelta(days=days - 1)
    response = _analytics_get({
        "ids": "channel==MINE",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "metrics": (
            "views,likes,comments,"
            "subscribersGained,subscribersLost,"
            "estimatedMinutesWatched,averageViewDuration,averageViewPercentage"
        ),
        "dimensions": "day",
        "sort": "day",
    }, access_token)
    result = []
    for row in _parse_rows(response):
        result.append({
            "date": row.get("day"),
            "views": int(row.get("views") or 0),
            "likes": int(row.get("likes") or 0),
            "comments": int(row.get("comments") or 0),
            "subscribers_net": int(row.get("subscribersGained") or 0) - int(row.get("subscribersLost") or 0),
            "watch_minutes": int(row.get("estimatedMinutesWatched") or 0),
            "avg_view_duration_sec": float(row.get("averageViewDuration") or 0),
            "avg_view_percentage": float(row.get("averageViewPercentage") or 0),
        })
    return result


def fetch_video_stats(access_token: str, days: int = 28) -> list[dict[str, Any]]:
    """최근 N일 내 영상별 지표 (조회수 TOP 10)."""
    end = datetime.now(KST).date()
    start = end - timedelta(days=days - 1)
    response = _analytics_get({
        "ids": "channel==MINE",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "metrics": (
            "views,impressions,impressionClickThroughRate,"
            "averageViewPercentage,averageViewDuration,likes,comments"
        ),
        "dimensions": "video",
        "sort": "-views",
        "maxResults": 10,
    }, access_token)
    result = []
    for row in _parse_rows(response):
        result.append({
            "video_id": row.get("video"),
            "views": int(row.get("views") or 0),
            "impressions": int(row.get("impressions") or 0),
            # API가 퍼센트로 반환 (예: 4.2 = 4.2%)
            "ctr_pct": float(row.get("impressionClickThroughRate") or 0),
            "avg_view_percentage": float(row.get("averageViewPercentage") or 0),
            "avg_view_duration_sec": float(row.get("averageViewDuration") or 0),
            "likes": int(row.get("likes") or 0),
            "comments": int(row.get("comments") or 0),
        })
    return result


def yesterday_summary(daily: list[dict[str, Any]]) -> dict[str, Any] | None:
    """daily 리스트에서 어제(KST) 데이터만 추출."""
    yesterday = (datetime.now(KST).date() - timedelta(days=1)).isoformat()
    for row in daily:
        if row.get("date") == yesterday:
            engagement_rate = (
                (row["likes"] + row["comments"]) / max(row["views"], 1)
                if row.get("views")
                else 0.0
            )
            return {**row, "engagement_rate": round(engagement_rate, 4)}
    return None


def seven_day_avg(daily: list[dict[str, Any]]) -> dict[str, float]:
    """최근 7일 평균 (어제 포함)."""
    if not daily:
        return {}
    keys = ["views", "likes", "comments", "subscribers_net", "avg_view_percentage"]
    totals: dict[str, float] = {k: 0.0 for k in keys}
    count = 0
    for row in daily[-7:]:
        for k in keys:
            totals[k] += float(row.get(k) or 0)
        count += 1
    if count == 0:
        return {}
    return {k: round(v / count, 2) for k, v in totals.items()}


def fetch_my_channel_analytics(days: int = 7) -> dict[str, Any] | None:
    """환경변수에서 인증 정보를 읽어 채널 analytics 수집. 인증 정보 없으면 None 반환."""
    client_id = os.getenv("YT_CLIENT_ID")
    client_secret = os.getenv("YT_CLIENT_SECRET")
    refresh_token = os.getenv("YT_REFRESH_TOKEN")
    channel_name = os.getenv("YT_CHANNEL_NAME", "스마트대디")

    if not all([client_id, client_secret, refresh_token]):
        return None

    try:
        access_token = _exchange_token(client_id, client_secret, refresh_token)
    except Exception as exc:
        print(f"YouTube Analytics 인증 실패: {exc}")
        return None

    daily: list[dict[str, Any]] = []
    try:
        daily = fetch_channel_daily(access_token, days=days)
        print(f"채널 일별 지표 수집 완료: {len(daily)}일치")
    except Exception as exc:
        print(f"채널 일별 지표 수집 실패: {exc}")

    video_stats: list[dict[str, Any]] = []
    try:
        video_stats = fetch_video_stats(access_token, days=28)
        print(f"영상별 지표 수집 완료: {len(video_stats)}개")
    except Exception as exc:
        print(f"영상별 지표 수집 실패: {exc}")

    return {
        "generated_at": datetime.now(KST).isoformat(),
        "channel_name": channel_name,
        "period_days": days,
        "daily": daily,
        "video_stats": video_stats,
        "yesterday": yesterday_summary(daily),
        "avg_7d": seven_day_avg(daily),
    }


def save_my_channel(data: dict[str, Any]) -> None:
    write_json(MY_CHANNEL_PATH, data)


def load_my_channel() -> dict[str, Any] | None:
    data = read_json(MY_CHANNEL_PATH, {})
    return data if data else None
