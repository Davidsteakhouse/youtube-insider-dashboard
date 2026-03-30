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


def _resolve_channel_ids(access_token: str) -> str:
    """OAuth 토큰이 가리키는 채널 ID 목록을 진단용으로 출력하고, ids 파라미터 값을 반환."""
    channel_id = os.getenv("YT_CHANNEL_ID", "").strip()
    if channel_id:
        print(f"[Analytics] 명시된 채널 ID 사용: {channel_id}")
        return f"channel=={channel_id}"

    # 연결된 채널 확인 (YouTube Data API v3)
    try:
        url = "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        items = data.get("items", [])
        if items:
            found_id = items[0]["id"]
            found_name = items[0]["snippet"]["title"]
            print(f"[Analytics] channel==MINE 해석 결과: {found_name} ({found_id})")
            if len(items) > 1:
                for it in items[1:]:
                    print(f"[Analytics]   추가 채널: {it['snippet']['title']} ({it['id']})")
        else:
            print("[Analytics] channel==MINE 해석 결과: 채널 없음")
    except Exception as exc:
        print(f"[Analytics] 채널 ID 확인 실패 (무시): {exc}")

    return "channel==MINE"


def fetch_channel_daily(access_token: str, days: int = 7, channel_ids: str = "channel==MINE") -> list[dict[str, Any]]:
    """채널 전체 일별 지표 (최근 N일)."""
    end = datetime.now(KST).date()
    start = end - timedelta(days=days - 1)
    response = _analytics_get({
        "ids": channel_ids,
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


def fetch_video_stats(access_token: str, days: int = 28, channel_ids: str = "channel==MINE") -> list[dict[str, Any]]:
    """최근 N일 내 영상별 지표 (조회수 TOP 10)."""
    end = datetime.now(KST).date()
    start = end - timedelta(days=days - 1)
    response = _analytics_get({
        "ids": channel_ids,
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
    """daily 리스트에서 가장 최근 가용일 데이터 반환 (YouTube Analytics는 2~3일 지연).
    어제 날짜가 없으면 가장 최근 날짜로 fallback."""
    if not daily:
        return None
    yesterday = (datetime.now(KST).date() - timedelta(days=1)).isoformat()
    # 어제 데이터 우선, 없으면 최신 가용일
    candidates = sorted(daily, key=lambda r: r.get("date", ""), reverse=True)
    target = None
    for row in candidates:
        if row.get("date") == yesterday:
            target = row
            break
    if target is None:
        target = candidates[0]
    engagement_rate = (
        (target["likes"] + target["comments"]) / max(target["views"], 1)
        if target.get("views")
        else 0.0
    )
    return {**target, "engagement_rate": round(engagement_rate, 4)}


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

    channel_ids = _resolve_channel_ids(access_token)

    daily: list[dict[str, Any]] = []
    try:
        daily = fetch_channel_daily(access_token, days=days, channel_ids=channel_ids)
        print(f"채널 일별 지표 수집 완료: {len(daily)}일치")
        if daily:
            sample = daily[-1]
            print(f"[Analytics] 최근 데이터 샘플 ({sample['date']}): 조회수={sample['views']}, 구독증감={sample['subscribers_net']}")
    except Exception as exc:
        print(f"채널 일별 지표 수집 실패: {exc}")

    video_stats: list[dict[str, Any]] = []
    try:
        video_stats = fetch_video_stats(access_token, days=28, channel_ids=channel_ids)
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
