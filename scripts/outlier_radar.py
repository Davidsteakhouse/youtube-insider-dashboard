#!/usr/bin/env python3
"""vidIQ식 아웃라이어 레이더.

막 터지는 영상을 이렇게 찾는다.
- 주 기준(둘 중 하나): 평소 대비 배수 = 조회수 ÷ 그 채널 최근 롱폼 조회수 중앙값 (7일 안 된 영상은 기준에서 뺌),
  구독자 대비 배수 = 조회수 ÷ 구독자 수 (작은 채널이 포맷의 힘으로 터진 경우)
- 바닥: 최소 조회수. 24시간 기준(영어 3만·한국어 1만)이고 24시간이 안 된 영상은 지난 시간만큼 나눠 적용한다
- 순위 보조: 최근 증가량. 실행 때마다 조회수를 기록해 직전 기록 이후 시간당 몇 회 늘었는지(가속·유지·둔화) 본다

감시 채널(data/watchlist.json) 밖까지 보려고 검색어 순환, 주간 페르소나 검색어,
GitHub·Hacker News 급상승 항목에서 뽑은 검색어를 함께 쓴다.
걸린 영상에는 Gemini로 내 채널 적합도를 매기고, 한국어 검색으로 국내 공백을 판정한다.
조건을 모두 넘은 것만 텔레그램 '선점 기회'로 보내고, 하루 한 번 요약을 보낸다.

GitHub Actions에서 pip 설치 없이 돌도록 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CONFIG_FILE = ROOT_DIR / "radar_config.json"
STATE_FILE = DATA_DIR / "radar_state.json"
LATEST_FILE = DATA_DIR / "radar_latest.json"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"
ENV_FILE = ROOT_DIR / ".env"

KST = timezone(timedelta(hours=9))
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
GEMINI_ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"
TELEGRAM_LIMIT = 4000
SHORTS_MAX_SECONDS = 180  # 기존 파이프라인(analytics_fetcher)과 같은 쇼츠 기준
SEARCH_COST = 100
HANGUL_RE = re.compile(r"[가-힣]")
AI_HINT_RE = re.compile(
    r"\b(ai|llm|gpt|claude|gemini|openai|anthropic|agent|agents|model|vibe|copilot|cursor|codex|diffusion|clone|mcp)\b",
    re.IGNORECASE,
)
GAP_LABELS = {"green": "🟢 공백", "yellow": "🟡 선점 경쟁", "red": "🔴 포화", "unknown": "⚪ 확인 못 함"}
WEEKDAYS_KO = "월화수목금토일"

FIT_PROMPT = """너는 한국 AI 유튜브 채널의 기획 보조다.
채널 설명: {profile}

입력은 지금 평소보다 크게 터지고 있는 유튜브 영상 목록이다.
영상마다 아래 필드를 가진 JSON 객체를 만들고, JSON 배열로만 답하라.
- id: 입력 id 그대로
- cluster: 같은 사건·소재를 다룬 영상끼리 같은 값을 갖는 영어 소문자 슬러그 (예: "claude-tv-adblock")
- topic_ko: 영상 소재를 한국어 15자 이내 이름으로 (예: "AI가 만든 어도비 대체앱")
- ko_query: 한국 유튜브에서 같은 소재를 찾을 검색어. 한국어 2~4단어
- ko_terms: 같은 소재를 다룬 한국 영상 제목에 나올 고유명사. 한글·영문 표기 모두, 최대 4개. 고유명사가 없으면 빈 배열
- fit: 이 채널이 같은 소재로 영상을 만들 때의 적합도. 1~5 정수 (5 = 채널 포맷에 딱 맞고 시청자가 좋아함, 1 = 안 맞음)
- format: "대결", "직접 해보기", "AI 대체 실험", "뉴스 해설", "기타" 중 하나
- series: 같은 뼈대로 이어 갈 다음 편 아이디어 한 줄. 없으면 빈 문자열
- title_ko: 이 채널이 쓸 한국어 제목 1개. 30자 이내, 과장 금지
- why: 적합도 판단 이유 한 줄"""

UPSTREAM_PROMPT = """입력은 GitHub와 Hacker News에서 지금 급상승 중인 항목이다.
항목마다 아래 필드를 가진 JSON 객체를 만들고, JSON 배열로만 답하라.
- id: 입력 id 그대로
- ai_related: AI·LLM·에이전트로 만들었거나 AI 관련 도구·사건이면 true
- yt_query: 이 소재를 다룬 영어 유튜브 영상을 찾을 검색어. 고유명사를 포함한 2~5단어"""

PERSONA_PROMPT = """아래 페르소나가 유튜브에서 찾아볼 만한 'AI × 생활·업무·취미' 주제의 유튜브 검색어 {count}개를 만들어라.
AI 툴 리뷰 채널이 잘 다루지 않는 쪽으로 넓게 뻗어라. 절반은 한국어, 절반은 영어.
검색창에 실제로 칠 법한 2~4단어로만 쓴다. 콜론, 부제, 설명 문장은 쓰지 않는다 (좋은 예: "AI 엑셀 자동화", "AI car repair").
JSON 배열로만 답하라: [{{"q": "검색어", "lang": "ko" 또는 "en"}}]
페르소나: {persona}
채널: {profile}"""


class QuotaExhausted(RuntimeError):
    pass


# ---------------------------------------------------------------- 공통 도구

def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip("\"'")


def redact(text: str) -> str:
    text = re.sub(r"(key=)[^&\s\"']+", r"\1***", text)
    return re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot***", text)


def http_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    payload: Any = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> Any:
    if params:
        query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
        url = f"{url}?{query}"
    request_headers = {"User-Agent": "youtube-insider-radar/1.0"}
    if headers:
        request_headers.update(headers)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="ignore"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:300]
        raise RuntimeError(f"HTTP {exc.code} {redact(url)} {redact(detail)}") from exc


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def chunked(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    bucket: list[Any] = []
    for item in items:
        bucket.append(item)
        if len(bucket) == size:
            yield bucket
            bucket = []
    if bucket:
        yield bucket


def unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def has_hangul(text: str | None) -> bool:
    return bool(HANGUL_RE.search(text or ""))


def parse_duration_seconds(value: str | None) -> int:
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value or "")
    if not match:
        return 0
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def compact_ko(value: float | int | None) -> str:
    if value is None:
        return "비공개"
    number = float(value)
    if number >= 100_000_000:
        text = f"{number / 100_000_000:.1f}억"
    elif number >= 10_000:
        text = f"{number / 10_000:.1f}만"
    else:
        return f"{int(round(number)):,}"
    return text.replace(".0", "")


def format_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}" if value < 10 else f"{value:,.0f}"


def quota_day(now: datetime) -> str:
    """유튜브 API 하루 한도는 미국 태평양 시간 자정에 초기화된다. 서머타임과 관계없이 늦은 쪽(UTC-8)으로 센다."""
    return (now - timedelta(hours=8)).date().isoformat()


def kst_label(value: datetime) -> str:
    local = value.astimezone(KST)
    return f"{local.month}/{local.day}({WEEKDAYS_KO[local.weekday()]})"


def as_list(result: Any) -> list[Any]:
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for value in result.values():
            if isinstance(value, list):
                return value
    return []


# ---------------------------------------------------------------- YouTube

class YouTubeClient:
    def __init__(self, api_key: str, budget: int) -> None:
        self.api_key = api_key
        self.budget = budget
        self.used = 0

    def get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        cost = SEARCH_COST if endpoint == "search" else 1
        if self.used + cost > self.budget:
            raise QuotaExhausted(f"{endpoint}: 이번 실행 쿼터 {self.budget} 소진")
        self.used += cost
        return http_json(f"{YOUTUBE_API_BASE}/{endpoint}", params={**params, "key": self.api_key})

    def can_search(self) -> bool:
        return self.used + SEARCH_COST <= self.budget

    def search(self, query: str, *, published_after: datetime, lang: str, max_results: int) -> list[str]:
        data = self.get(
            "search",
            {
                "part": "snippet",
                "type": "video",
                "q": query,
                "order": "viewCount",
                "publishedAfter": iso(published_after),
                "maxResults": max_results,
                "relevanceLanguage": lang,
                "regionCode": "KR" if lang == "ko" else "US",
            },
        )
        return [item["id"]["videoId"] for item in data.get("items", []) if item.get("id", {}).get("videoId")]

    def videos(self, video_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for batch in chunked(unique(video_ids), 50):
            data = self.get("videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(batch), "maxResults": 50})
            for item in data.get("items", []):
                record = parse_video_item(item)
                records[record["video_id"]] = record
        return records

    def channels(self, channel_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for batch in chunked(unique(channel_ids), 50):
            data = self.get("channels", {"part": "snippet,statistics,contentDetails", "id": ",".join(batch), "maxResults": 50})
            for item in data.get("items", []):
                statistics = item.get("statistics", {})
                hidden = statistics.get("hiddenSubscriberCount")
                records[item["id"]] = {
                    "title": item.get("snippet", {}).get("title", ""),
                    "subs": None if hidden else int(statistics.get("subscriberCount", 0) or 0) or None,
                    "uploads": item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
                }
        return records

    def playlist_video_ids(self, playlist_id: str, max_results: int) -> list[str]:
        data = self.get("playlistItems", {"part": "contentDetails", "playlistId": playlist_id, "maxResults": max_results})
        return [item.get("contentDetails", {}).get("videoId") for item in data.get("items", []) if item.get("contentDetails")]


def parse_video_item(item: dict[str, Any]) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})
    return {
        "video_id": item["id"],
        "title": snippet.get("title", ""),
        "description": (snippet.get("description") or "")[:400],
        "channel_id": snippet.get("channelId"),
        "channel_title": snippet.get("channelTitle", ""),
        "published_at": snippet.get("publishedAt"),
        "views": int(statistics.get("viewCount", 0) or 0),
        "likes": int(statistics.get("likeCount", 0) or 0),
        "comments": int(statistics.get("commentCount", 0) or 0),
        "duration_s": parse_duration_seconds(item.get("contentDetails", {}).get("duration")),
        "live": snippet.get("liveBroadcastContent", "none"),
    }


def is_longform(video: dict[str, Any]) -> bool:
    return video.get("duration_s", 0) > SHORTS_MAX_SECONDS and video.get("live", "none") == "none"


def age_hours(video: dict[str, Any], now: datetime) -> float:
    published = parse_time(video.get("published_at"))
    if not published:
        return 0.0
    return (now - published).total_seconds() / 3600


# ---------------------------------------------------------------- 점수

def compute_baseline(videos: Iterable[dict[str, Any]], now: datetime, *, min_age_days: float, sample_size: int) -> tuple[float | None, int]:
    """채널의 '평소 조회수' = 최근 롱폼 조회수 중앙값. 아직 크는 중인 새 영상은 뺀다."""
    longform = sorted(
        (video for video in videos if is_longform(video)),
        key=lambda video: video.get("published_at") or "",
        reverse=True,
    )
    for min_days in (min_age_days, 2):
        eligible = [video for video in longform if age_hours(video, now) >= min_days * 24][:sample_size]
        if len(eligible) >= 3:
            return float(median(video["views"] for video in eligible)), len(eligible)
    return None, 0


def required_views(hours: float, lang: str, thresholds: dict[str, Any]) -> float:
    """최소 조회수 바닥. 24시간 기준값이고, 24시간이 안 된 영상은 지난 시간만큼만 요구한다 (12시간이면 절반)."""
    return thresholds["views_min"][lang] * min(hours / thresholds["views_min_hours"], 1.0)


def recent_growth(points: list[list[Any]], views: int, now: datetime, min_gap_hours: float) -> dict[str, Any] | None:
    """min_gap_hours 이상 지난 가장 최근 기록과 비교해 그사이 늘어난 조회수를 구한다."""
    for stamp, previous in reversed(points):
        recorded = parse_time(stamp)
        if not recorded:
            continue
        hours = (now - recorded).total_seconds() / 3600
        if hours >= min_gap_hours:
            gained = max(views - int(previous), 0)
            return {"hours": round(hours, 1), "gained": gained, "per_hour": round(gained / hours)}
    return None


def growth_trend(recent_per_hour: float, average_per_hour: float) -> str:
    """보통 영상은 시간이 갈수록 느려진다. 최근 속도가 평균 이상이면 가속, 평균의 40% 미만이면 둔화."""
    if average_per_hour <= 0:
        return "유지"
    ratio = recent_per_hour / average_per_hour
    if ratio >= 1.0:
        return "가속"
    return "유지" if ratio >= 0.4 else "둔화"


def score_video(
    video: dict[str, Any],
    channel: dict[str, Any],
    now: datetime,
    thresholds: dict[str, Any],
    growth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hours = max(age_hours(video, now), 1.0)
    views = video["views"]
    vph = views / hours
    baseline = channel.get("baseline")
    subs = channel.get("subs")
    multiplier = views / baseline if baseline else None
    sub_ratio = views / subs if subs else None
    lang = "ko" if has_hangul(video.get("title")) else "en"
    outlier = (multiplier or 0) >= thresholds["multiplier_min"] or (sub_ratio or 0) >= thresholds["sub_ratio_min"]
    big_enough = views >= required_views(hours, lang, thresholds)
    # 배수는 로그로 눌러 한 지표가 순위를 독차지하지 않게 한다. 속도는 최근 증가량이 있으면 그걸 쓴다.
    speed = growth["per_hour"] if growth else vph
    score = math.log2(max(multiplier or 1.0, 1.0)) + math.log2(1 + (sub_ratio or 0)) + math.log10(1 + speed)
    result = {
        **video,
        "channel_subs": subs,
        "channel_baseline": round(baseline) if baseline else None,
        "age_hours": round(hours, 1),
        "vph": round(vph),
        "multiplier": round(multiplier, 2) if multiplier is not None else None,
        "sub_ratio": round(sub_ratio, 2) if sub_ratio is not None else None,
        "lang": lang,
        "is_outlier": outlier,
        "is_big": big_enough,
        "passes": outlier and big_enough,
        "score": round(score, 2),
    }
    if growth:
        result.update(
            recent_hours=growth["hours"],
            recent_gain=growth["gained"],
            recent_vph=growth["per_hour"],
            trend=growth_trend(growth["per_hour"], vph),
        )
    return result


def growth_text(candidate: dict[str, Any]) -> str:
    if candidate.get("recent_vph") is None:
        return f"시간당 평균 {compact_ko(candidate['vph'])}회 (첫 관측)"
    return (
        f"최근 {candidate['recent_hours']:.0f}시간 +{compact_ko(candidate['recent_gain'])}회 "
        f"(시간당 {compact_ko(candidate['recent_vph'])} · {candidate['trend']})"
    )


def classify_gap(longform_count: int, top_views: int, gap_cfg: dict[str, Any]) -> str:
    if longform_count >= gap_cfg["red_longform_min"] or top_views >= gap_cfg["red_top_views_min"]:
        return "red"
    if longform_count <= gap_cfg["green_longform_max"] and top_views < gap_cfg["green_top_views_max"]:
        return "green"
    return "yellow"


def topic_key(candidate: dict[str, Any]) -> str:
    base = candidate.get("ko_query") or candidate.get("topic_ko") or candidate.get("video_id", "")
    return re.sub(r"\s+", "", str(base)).lower()


def dedupe_keys(candidate: dict[str, Any]) -> list[str]:
    """다음 실행에서 같은 소재를 다시 알리지 않으려고 남기는 열쇠들."""
    keys = [topic_key(candidate)]
    if candidate.get("cluster"):
        keys.append(f"cluster:{candidate['cluster']}")
    for signal in candidate.get("signals", []):
        keys.append(f"signal:{signal.split(' ★')[0].split(' · ')[0].lower()}")
    return unique(keys)


def group_by_cluster(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 소재 영상을 묶어 점수가 가장 높은 영상을 대표로 세운다. 입력은 점수순이어야 한다."""
    leaders: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = candidate.get("cluster") or topic_key(candidate)
        leader = leaders.get(key)
        if leader is None:
            leaders[key] = candidate
            candidate["cluster_items"] = []
            continue
        leader["cluster_items"].append(candidate)
        leader["signals"] = unique([*leader.get("signals", []), *candidate.get("signals", [])])
    return list(leaders.values())


# ---------------------------------------------------------------- Gemini

def gemini_json(system_prompt: str, user_payload: Any) -> Any | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    model = os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(user_payload, ensure_ascii=False)}]}],
    }
    try:
        response = http_json(GEMINI_ENDPOINT_TEMPLATE.format(model=model), params={"key": api_key}, payload=payload, timeout=60)
        text = response["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = re.sub(r"^```(?:json)?|```$", "", text).strip()
        return json.loads(text)
    except Exception as exc:  # 적합도는 보조 정보라 실패해도 레이더는 계속 돈다
        log(f"[gemini] 실패: {redact(str(exc))[:200]}")
        return None


def enrich_fit(candidates: list[dict[str, Any]], profile: str) -> bool:
    if not candidates:
        return True
    rows = [
        {
            "id": candidate["video_id"],
            "title": candidate["title"],
            "channel": candidate["channel_title"],
            "description": candidate.get("description", "")[:300],
            "views": candidate["views"],
            "hours_since_upload": candidate["age_hours"],
            "multiplier_vs_channel": candidate.get("multiplier"),
        }
        for candidate in candidates
    ]
    result = as_list(gemini_json(FIT_PROMPT.format(profile=profile), rows))
    by_id = {row.get("id"): row for row in result if isinstance(row, dict)}
    for candidate in candidates:
        row = by_id.get(candidate["video_id"])
        if not row:
            continue
        try:
            fit = int(row.get("fit"))
        except (TypeError, ValueError):
            fit = None
        candidate.update(
            cluster=str(row.get("cluster") or "").strip().lower(),
            topic_ko=str(row.get("topic_ko") or "").strip(),
            ko_query=str(row.get("ko_query") or "").strip(),
            ko_terms=[str(term).strip() for term in (row.get("ko_terms") or []) if str(term).strip()][:4],
            fit=fit,
            format=str(row.get("format") or "").strip(),
            series=str(row.get("series") or "").strip(),
            title_ko=str(row.get("title_ko") or "").strip(),
            why=str(row.get("why") or "").strip(),
        )
    return bool(by_id)


# ---------------------------------------------------------------- 상류 신호

def github_signals(state: dict[str, Any], now: datetime, upstream_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    since = (now - timedelta(days=upstream_cfg["github_created_within_days"])).date().isoformat()
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = http_json(
        "https://api.github.com/search/repositories",
        params={"q": f"created:>{since} stars:>{upstream_cfg['github_query_min_stars']}", "sort": "stars", "order": "desc", "per_page": 30},
        headers=headers,
    )
    memory = state.setdefault("github", {})
    signals = []
    for repo in data.get("items", []):
        name = repo.get("full_name")
        stars = int(repo.get("stargazers_count") or 0)
        previous = memory.get(name) or {}
        previous_at = parse_time(previous.get("at"))
        if previous_at:
            days = max((now - previous_at).total_seconds() / 86400, 1 / 24)
            per_day = (stars - int(previous.get("stars", 0))) / days
        else:
            created = parse_time(repo.get("created_at")) or now
            per_day = stars / max((now - created).total_seconds() / 86400, 0.5)
        memory[name] = {"stars": stars, "at": iso(now)}
        if stars >= upstream_cfg["github_min_stars"] or per_day >= upstream_cfg["github_min_stars_per_day"]:
            signals.append(
                {
                    "id": f"gh:{name}",
                    "kind": "GitHub",
                    "name": name,
                    "title": repo.get("name", ""),
                    "description": (repo.get("description") or "")[:160],
                    "stars": stars,
                    "per_day": round(per_day),
                    "url": repo.get("html_url"),
                }
            )
    cutoff = now - timedelta(days=30)
    for name in [name for name, value in memory.items() if (parse_time(value.get("at")) or now) < cutoff]:
        memory.pop(name, None)
    signals.sort(key=lambda signal: signal["per_day"], reverse=True)
    return signals[: upstream_cfg["max_signals"]]


def hn_signals(now: datetime, upstream_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    data = http_json("https://hn.algolia.com/api/v1/search", params={"tags": "front_page", "hitsPerPage": 50})
    max_age = timedelta(hours=upstream_cfg["hn_max_age_hours"])
    signals = []
    for hit in data.get("hits", []):
        points = int(hit.get("points") or 0)
        created = datetime.fromtimestamp(int(hit.get("created_at_i") or 0), tz=timezone.utc)
        if points < upstream_cfg["hn_min_points"] or now - created > max_age:
            continue
        item_url = f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        signals.append(
            {
                "id": f"hn:{hit.get('objectID')}",
                "kind": "HN",
                "title": hit.get("title") or "",
                "description": "",
                "points": points,
                "comments": int(hit.get("num_comments") or 0),
                "url": hit.get("url") or item_url,
                "hn_url": item_url,
            }
        )
    signals.sort(key=lambda signal: signal["points"], reverse=True)
    return signals[: upstream_cfg["max_signals"]]


def fallback_query(signal: dict[str, Any]) -> str:
    if signal["kind"] == "GitHub":
        return re.sub(r"[-_.]+", " ", signal.get("title", "")).strip()
    title = re.sub(r"^(show|ask|launch) hn:\s*", "", signal.get("title", ""), flags=re.IGNORECASE)
    return " ".join(title.split()[:6])


def signal_label(signal: dict[str, Any]) -> str:
    if signal["kind"] == "GitHub":
        return f"GitHub {signal['name']} ★{compact_ko(signal['stars'])} (+{compact_ko(signal['per_day'])}/일)"
    return f"HN {signal['points']}점 · {signal['title'][:50]}"


def pick_upstream_queries(signals: list[dict[str, Any]], state: dict[str, Any], now: datetime, upstream_cfg: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    if not signals:
        return []
    rows = [{"id": s["id"], "title": s.get("title"), "name": s.get("name"), "description": s.get("description")} for s in signals]
    by_id = {row.get("id"): row for row in as_list(gemini_json(UPSTREAM_PROMPT, rows)) if isinstance(row, dict)}
    searched = state.setdefault("upstream_searched", {})
    picks: list[tuple[str, dict[str, Any]]] = []
    for signal in signals:
        row = by_id.get(signal["id"], {})
        if "ai_related" in row:
            signal["ai_related"] = bool(row["ai_related"])
        else:
            signal["ai_related"] = bool(AI_HINT_RE.search(f"{signal.get('title', '')} {signal.get('description', '')}"))
        signal["yt_query"] = str(row.get("yt_query") or fallback_query(signal)).strip()
        if not signal["ai_related"] or not signal["yt_query"]:
            continue
        last = parse_time(searched.get(signal["yt_query"].lower()))
        if last and now - last < timedelta(hours=24):
            continue
        picks.append((signal["yt_query"], signal))
        if len(picks) >= upstream_cfg["max_queries_per_run"]:
            break
    return picks


# ---------------------------------------------------------------- 검색어

def refresh_persona_queries(config: dict[str, Any], state: dict[str, Any], now: datetime) -> None:
    persona = state.get("persona") or {}
    last = parse_time(persona.get("at"))
    if last and now - last < timedelta(days=7):
        return
    count = config.get("persona_queries_per_week", 10)
    prompt = PERSONA_PROMPT.format(count=count, persona=config.get("persona", ""), profile=config.get("channel_profile", ""))
    rows = as_list(gemini_json(prompt, {"count": count}))
    queries = [
        {"q": str(row.get("q")).strip(), "lang": "ko" if row.get("lang") == "ko" else "en"}
        for row in rows
        if isinstance(row, dict) and str(row.get("q") or "").strip()
    ][:count]
    if queries:
        state["persona"] = {"at": iso(now), "queries": queries}
        log(f"[persona] 이번 주 검색어 {len(queries)}개: {', '.join(q['q'] for q in queries)}")


def next_queries(config: dict[str, Any], state: dict[str, Any], count: int) -> list[dict[str, str]]:
    pool = list(config.get("queries", [])) + list((state.get("persona") or {}).get("queries", []))
    if not pool or count <= 0:
        return []
    cursor = int(state.get("query_cursor", 0)) % len(pool)
    picked = [pool[(cursor + offset) % len(pool)] for offset in range(min(count, len(pool)))]
    state["query_cursor"] = (cursor + len(picked)) % len(pool)
    return picked


# ---------------------------------------------------------------- 채널 정보

def refresh_channels(yt: YouTubeClient, state: dict[str, Any], channel_ids: list[str], now: datetime, ttl: timedelta) -> dict[str, dict[str, Any]]:
    cache = state.setdefault("channels", {})
    stale = [cid for cid in unique(channel_ids) if cid not in cache or not parse_time(cache[cid].get("meta_at")) or now - parse_time(cache[cid]["meta_at"]) > ttl]
    if stale:
        for cid, meta in yt.channels(stale).items():
            cache[cid] = {**cache.get(cid, {}), **meta, "meta_at": iso(now)}
    return cache


def update_baselines(
    yt: YouTubeClient,
    state: dict[str, Any],
    channel_ids: list[str],
    now: datetime,
    baseline_cfg: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, dict[str, Any]]:
    """채널 최근 업로드를 읽어 평소 조회수를 갱신한다. 읽은 영상도 돌려준다(감시 채널 새 영상 찾기에 씀)."""
    cache = state.setdefault("channels", {})
    ttl = timedelta(hours=baseline_cfg["ttl_hours"])
    targets = []
    for cid in unique(channel_ids):
        entry = cache.get(cid) or {}
        fresh = parse_time(entry.get("baseline_at"))
        if not entry.get("uploads") or (not force and fresh and now - fresh < ttl):
            continue
        targets.append(cid)
    playlist: dict[str, list[str]] = {}
    for cid in targets:
        playlist[cid] = yt.playlist_video_ids(cache[cid]["uploads"], baseline_cfg["recent_uploads"])
    videos = yt.videos(video_id for ids in playlist.values() for video_id in ids)
    by_channel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for video in videos.values():
        by_channel[video["channel_id"]].append(video)
    for cid in targets:
        baseline, sample = compute_baseline(
            by_channel.get(cid, []), now, min_age_days=baseline_cfg["min_age_days"], sample_size=baseline_cfg["sample_size"]
        )
        cache[cid].update(baseline=baseline, baseline_n=sample, baseline_at=iso(now))
    return videos


# ---------------------------------------------------------------- 국내 공백

def korea_gap(yt: YouTubeClient, candidate: dict[str, Any], now: datetime, gap_cfg: dict[str, Any], max_results: int) -> dict[str, Any]:
    query = candidate.get("ko_query") or ""
    ids = yt.search(query, published_after=now - timedelta(days=gap_cfg["lookback_days"]), lang="ko", max_results=max_results)
    videos = [video for video in yt.videos(ids).values() if has_hangul(video["title"])]
    terms = [term.lower() for term in candidate.get("ko_terms") or [] if term]
    if terms:
        videos = [video for video in videos if any(term in f"{video['title']} {video['description']}".lower() for term in terms)]
    longform = [video for video in videos if is_longform(video)]
    top = max(longform, key=lambda video: video["views"], default=None)
    top_views = top["views"] if top else 0
    return {
        "verdict": classify_gap(len(longform), top_views, gap_cfg),
        "query": query,
        "terms": candidate.get("ko_terms") or [],
        "longform": len(longform),
        "shorts": len(videos) - len(longform),
        "top_views": top_views,
        "top_title": top["title"] if top else "",
        "top_channel": top["channel_title"] if top else "",
    }


# ---------------------------------------------------------------- 메시지

def build_alert(candidate: dict[str, Any], gap_cfg: dict[str, Any], deadline_days: int) -> str:
    gap = candidate.get("korea") or {"verdict": "unknown"}
    published = parse_time(candidate.get("published_at")) or datetime.now(timezone.utc)
    deadline = published + timedelta(days=deadline_days)
    lines = [
        f"🚨 선점 기회 | {candidate.get('topic_ko') or candidate['title'][:30]}",
        candidate["title"],
        f"[{candidate['channel_title']}] 구독 {compact_ko(candidate.get('channel_subs'))} · 업로드 {candidate['age_hours']:.0f}시간 · {compact_ko(candidate['views'])}회",
        (f"평소 대비 {format_ratio(candidate['multiplier'])}배" if candidate.get("multiplier") is not None else "평소 기준 없음")
        + f" · 구독자 대비 {format_ratio(candidate.get('sub_ratio'))}배",
        growth_text(candidate),
    ]
    if gap.get("verdict") != "unknown":
        lines.append(
            f"국내: {GAP_LABELS[gap['verdict']]} (최근 {gap_cfg['lookback_days']}일 롱폼 {gap['longform']}개·쇼츠 {gap['shorts']}개, "
            f"최고 {compact_ko(gap['top_views'])}회 · \"{gap['query']}\")"
        )
    else:
        lines.append(f"국내: {GAP_LABELS['unknown']}")
    if candidate.get("fit") is not None:
        lines.append(f"내 포맷: {candidate.get('format') or '-'} · 적합 {candidate['fit']}/5 — {candidate.get('why', '')}".rstrip(" —"))
    others = candidate.get("cluster_items") or []
    if others:
        names = ", ".join(unique(item["channel_title"][:16] for item in others)[:3])
        lines.append(f"같은 소재 아웃라이어 {len(others)}개 더: {names}")
    if candidate.get("series"):
        lines.append(f"다음 편: {candidate['series']}")
    if candidate.get("title_ko"):
        lines.append(f"제목 예: {candidate['title_ko']}")
    lines.append(f"마감: {kst_label(deadline)}까지 (원본 업로드 +{deadline_days}일)")
    if candidate.get("signals"):
        lines.append("신호: " + " / ".join(candidate["signals"]))
    lines.append(f"https://youtu.be/{candidate['video_id']}")
    return "\n".join(lines)


def build_summary(
    pool: list[dict[str, Any]],
    upstream: list[dict[str, Any]],
    now: datetime,
    *,
    top_n: int,
    watch_count: int,
    alerts_today: int,
    quota_today: int,
    quota_cap: int,
    window_hours: int,
    errors: int = 0,
) -> str:
    local = now.astimezone(KST)
    lines = [
        f"📡 아웃라이어 레이더 | {kst_label(now)} {local:%H:%M}",
        f"최근 {window_hours}시간 · 감시 채널 {watch_count}개 + 검색어 순환 + GitHub·HN",
        "",
        f"🔥 평소 대비 TOP{top_n}",
    ]
    ranked = [item for item in pool if (item.get("multiplier") or 0) >= 2 or (item.get("sub_ratio") or 0) >= 1]
    ranked.sort(key=lambda item: item.get("score", 0), reverse=True)
    if not ranked:
        lines.append("- 평소 대비 2배 넘는 영상이 아직 없습니다.")
    for index, item in enumerate(ranked[:top_n], start=1):
        lines.append(f"{index}. [{item['channel_title']} · 구독 {compact_ko(item.get('channel_subs'))}] {item['title'][:60]}")
        usual = f"평소 {format_ratio(item['multiplier'])}배" if item.get("multiplier") is not None else "평소 기준 없음"
        lines.append(
            f"   {usual} · 구독자 {format_ratio(item.get('sub_ratio'))}배 · {compact_ko(item['views'])}회 · {item['age_hours']:.0f}시간"
            + (f" · 최근 {item['trend']}" if item.get("trend") else "")
        )
        lines.append(f"   https://youtu.be/{item['video_id']}")
    strong = [signal for signal in upstream if signal.get("ai_related", True)][:4]
    if strong:
        lines.append("")
        lines.append("🛰 상류 신호")
        for signal in strong:
            detail = signal.get("description") or ""
            lines.append(f"- {signal_label(signal)}{' · ' + detail[:50] if detail else ''}")
    lines.append("")
    lines.append(f"🚨 오늘 선점 알림 {alerts_today}건 · 유튜브 쿼터 {quota_today:,}/{quota_cap:,}")
    if errors:
        lines.append(f"⚠ 이번 실행 오류 {errors}건 (GitHub Actions 기록 확인)")
    return "\n".join(lines)


def send_telegram(text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 없습니다.")
    parts, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > TELEGRAM_LIMIT:
            parts.append(current)
            current = ""
        current += line
    if current:
        parts.append(current)
    for part in parts:
        http_json(
            f"https://api.telegram.org/bot{token}/sendMessage",
            payload={"chat_id": chat_id, "text": part, "disable_web_page_preview": True},
        )


def compact_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "video_id", "title", "channel_id", "channel_title", "published_at", "views", "duration_s", "channel_subs",
        "channel_baseline", "age_hours", "vph", "recent_hours", "recent_gain", "recent_vph", "trend", "multiplier",
        "sub_ratio", "lang", "passes", "score", "sources",
        "signals", "cluster", "topic_ko", "ko_query", "ko_terms", "fit", "format", "series", "title_ko", "why", "korea",
        "seen_at",
    ]
    record = {key: candidate[key] for key in keys if key in candidate}
    if candidate.get("cluster_items"):
        record["cluster_video_ids"] = [item["video_id"] for item in candidate["cluster_items"]]
    return record


# ---------------------------------------------------------------- 실행

def run(args: argparse.Namespace) -> int:
    load_env_file(Path(args.env_file) if args.env_file else ENV_FILE)
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        log("YOUTUBE_API_KEY가 없습니다.")
        return 1

    config = read_json(CONFIG_FILE, None)
    if not config:
        log(f"설정 파일을 읽지 못했습니다: {CONFIG_FILE}")
        return 1
    test_mode = bool(args.query)
    dry_run = args.dry_run or (test_mode and not args.send)
    state = read_json(STATE_FILE, {})
    now = datetime.now(timezone.utc)
    today = now.astimezone(KST).date().isoformat()
    daily = state.get("daily") if (state.get("daily") or {}).get("date") == today else {"date": today, "alerts": 0}
    quota = state.get("quota") if (state.get("quota") or {}).get("day") == quota_day(now) else {"day": quota_day(now), "used": 0}

    thresholds = config["thresholds"]
    alerts_cfg = config["alerts"]
    gap_cfg = config["korea_gap"]
    upstream_cfg = config["upstream"]
    window_hours = args.window_hours or config["window_hours"]
    window = timedelta(hours=window_hours)
    budget = max(0, min(config["quota_budget_per_run"], config["daily_quota_cap"] - quota["used"]))
    yt = YouTubeClient(api_key, budget)
    exclude_titles = {title.lower() for title in config.get("exclude_channel_titles", [])}
    errors: list[str] = []
    sources: dict[str, list[str]] = defaultdict(list)
    signals_by_video: dict[str, list[str]] = defaultdict(list)
    videos: dict[str, dict[str, Any]] = {}
    upstream: list[dict[str, Any]] = []
    watch_ids: list[str] = []
    searched_queries: list[str] = []

    def run_search(query: str, lang: str, label: str, *, hours: float, signal: str | None = None) -> bool:
        if not yt.can_search():
            return False
        try:
            found = yt.search(query, published_after=now - timedelta(hours=hours), lang=lang, max_results=config["search_results_per_query"])
        except QuotaExhausted:
            return False
        except Exception as exc:
            errors.append(f"검색 '{query}': {redact(str(exc))[:120]}")
            return False
        searched_queries.append(query)
        for video_id in found:
            sources[video_id].append(label)
            if signal:
                signals_by_video[video_id].append(signal)
        return True

    def guarded(name: str, step: Any) -> None:
        """한 단계가 실패해도(쿼터 소진, API 오류) 나머지 단계와 요약은 계속 돈다."""
        try:
            step()
        except QuotaExhausted as exc:
            errors.append(str(exc))
        except Exception as exc:
            errors.append(f"{name}: {redact(str(exc))[:160]}")

    def scan_watchlist() -> None:
        """1) 감시 채널: 최근 업로드를 읽으면서 평소 조회수도 함께 갱신"""
        watchlist = read_json(WATCHLIST_FILE, {}).get("channels", [])
        watch_ids.extend(c["youtube_channel_id"] for c in watchlist if c.get("is_active", True) and c.get("youtube_channel_id"))
        refresh_channels(yt, state, watch_ids, now, timedelta(days=7))
        for video in update_baselines(yt, state, watch_ids, now, config["baseline"], force=True).values():
            if age_hours(video, now) <= window_hours:
                videos[video["video_id"]] = video
                sources[video["video_id"]].append("감시 채널")

    def scan_upstream() -> None:
        """2) 상류 신호(GitHub·HN) → 고유명사 검색어"""
        for name, collect in (("GitHub", lambda: github_signals(state, now, upstream_cfg)), ("HN", lambda: hn_signals(now, upstream_cfg))):
            try:
                upstream.extend(collect())
            except Exception as exc:
                errors.append(f"{name}: {redact(str(exc))[:120]}")
        for query, signal in pick_upstream_queries(upstream, state, now, upstream_cfg):
            if run_search(query, "en", f"상류 '{query}'", hours=upstream_cfg["search_window_hours"], signal=signal_label(signal)):
                state.setdefault("upstream_searched", {})[query.lower()] = iso(now)

    def scan_queries() -> None:
        """3) 고정·페르소나 검색어 순환"""
        refresh_persona_queries(config, state, now)
        for item in next_queries(config, state, config["searches_per_run"]):
            run_search(item["q"], item.get("lang", "en"), f"검색 '{item['q']}'", hours=window_hours)

    def fetch_videos() -> None:
        """4) 지난 실행에서 본 후보도 다시 읽어 최근 증가량을 잰다 (영상 50개당 1단위라 거의 공짜)"""
        if not test_mode:
            for item in state.get("pool", []):
                if age_hours(item, now) <= window_hours:
                    sources[item["video_id"]].extend(item.get("sources") or ["추적"])
                    signals_by_video[item["video_id"]].extend(item.get("signals") or [])
        videos.update(yt.videos(video_id for video_id in sources if video_id not in videos))

    if test_mode:
        run_search(args.query, "ko" if has_hangul(args.query) else "en", f"검색 '{args.query}'", hours=window_hours)
    else:
        if not args.no_watchlist:
            guarded("감시 채널", scan_watchlist)
        if not args.no_upstream:
            guarded("상류 신호", scan_upstream)
        if not args.no_search:
            guarded("검색어", scan_queries)
    guarded("영상 정보", fetch_videos)

    # 5) 사전 거르기

    candidates = []
    for video in videos.values():
        hours = age_hours(video, now)
        lang = "ko" if has_hangul(video["title"]) else "en"
        if not is_longform(video) or hours < config["min_age_hours"] or hours > window_hours:
            continue
        if any(title in video["channel_title"].lower() for title in exclude_titles):
            continue
        if video["views"] < required_views(hours, lang, thresholds) * 0.5 and "감시 채널" not in sources[video["video_id"]]:
            continue
        candidates.append(video)

    def fetch_baselines() -> None:
        channel_ids = unique(video["channel_id"] for video in candidates)
        refresh_channels(yt, state, channel_ids, now, timedelta(hours=config["baseline"]["ttl_hours"]))
        update_baselines(yt, state, channel_ids, now, config["baseline"])

    guarded("채널 기준선", fetch_baselines)

    # 6) 점수 (직전 기록과 비교한 최근 증가량 포함) + 이번 조회수 기록
    channels = state.get("channels", {})
    snapshots = state.setdefault("snapshots", {})
    scored = []
    for video in candidates:
        record = snapshots.setdefault(video["video_id"], {"published_at": video["published_at"], "points": []})
        growth = recent_growth(record["points"], video["views"], now, thresholds["growth_min_gap_hours"])
        record["points"] = [*record["points"], [iso(now), video["views"]]][-4:]
        result = score_video(video, channels.get(video["channel_id"], {}), now, thresholds, growth)
        result["sources"] = unique(sources.get(video["video_id"], []))
        result["signals"] = unique(signals_by_video.get(video["video_id"], []))
        result["seen_at"] = iso(now)
        scored.append(result)
    scored.sort(key=lambda item: item["score"], reverse=True)

    # 7) 내 채널 적합도 (통과한 상위 후보만)
    alerted = state.setdefault("alerted", {})
    alerted_topics = state.setdefault("alerted_topics", {})
    passing = [item for item in scored if item["passes"]]
    if test_mode and not passing:
        passing = scored[:3]  # 시험 모드에서는 기준 미달도 판정까지 보여 준다
    fit_targets = [item for item in passing if test_mode or item["video_id"] not in alerted][: alerts_cfg["llm_candidates"]]
    if fit_targets and not enrich_fit(fit_targets, config.get("channel_profile", "")):
        errors.append("Gemini 적합도 판정 실패")

    # 8) 같은 소재끼리 묶고 대표 영상만 국내 공백 판정 (검색 쿼터가 커서 실행당 몇 개로 제한)
    recent_topic_cutoff = now - timedelta(days=7)
    gap_targets = []
    for item in group_by_cluster(fit_targets):
        if not item.get("ko_query"):
            continue
        if item.get("fit") is not None and item["fit"] < thresholds["fit_min"]:
            continue
        recent = [parse_time(alerted_topics.get(key)) for key in dedupe_keys(item)]
        if not test_mode and any(last and last > recent_topic_cutoff for last in recent):
            continue
        gap_targets.append(item)
    for item in gap_targets[: alerts_cfg["gap_checks_per_run"]]:
        if not yt.can_search():
            errors.append("쿼터 부족으로 국내 공백 판정 일부 생략")
            break
        try:
            item["korea"] = korea_gap(yt, item, now, gap_cfg, config["search_results_per_query"])
            gap = item["korea"]
            log(
                f"[국내] {GAP_LABELS[gap['verdict']]} \"{gap['query']}\" 롱폼 {gap['longform']}·쇼츠 {gap['shorts']}·최고 "
                f"{compact_ko(gap['top_views'])} ({gap['top_channel'][:12]}) ← {item['title'][:40]} (적합 {item.get('fit')})"
            )
        except Exception as exc:
            errors.append(f"국내 공백 '{item.get('ko_query')}': {redact(str(exc))[:120]}")

    # 9) 선점 알림
    messages: list[str] = []
    alerts_sent: list[dict[str, Any]] = []
    for item in gap_targets:
        gap = item.get("korea")
        if not gap or gap["verdict"] not in ("green", "yellow"):
            continue
        if not test_mode:
            if (item.get("fit") or 0) < thresholds["fit_min"]:
                continue
            if len(alerts_sent) >= alerts_cfg["max_per_run"] or daily["alerts"] + len(alerts_sent) >= alerts_cfg["max_per_day"]:
                break
        messages.append(build_alert(item, gap_cfg, alerts_cfg["deadline_days"]))
        alerts_sent.append(item)

    # 10) 하루 한 번 요약 (지난 24시간 동안 본 후보를 합쳐서)
    pool = {item["video_id"]: item for item in state.get("pool", []) if (parse_time(item.get("seen_at")) or now) > now - timedelta(hours=24)}
    for item in scored:
        pool[item["video_id"]] = compact_candidate(item)
    pool_list = sorted(pool.values(), key=lambda item: item.get("score", 0), reverse=True)[:40]
    local_now = now.astimezone(KST)
    want_summary = args.summary or (
        not test_mode and local_now.hour >= alerts_cfg["summary_hour_kst"] and state.get("last_summary_date") != today
    )
    if want_summary:
        messages.append(
            build_summary(
                pool_list,
                upstream,
                now,
                top_n=alerts_cfg["summary_top"],
                watch_count=len(watch_ids) or len(read_json(WATCHLIST_FILE, {}).get("channels", [])),
                alerts_today=daily["alerts"] + len(alerts_sent),
                quota_today=quota["used"] + yt.used,
                errors=len(errors),
                quota_cap=config["daily_quota_cap"],
                window_hours=window_hours,
            )
        )

    # 11) 발송·저장
    if args.table or dry_run:
        log("")
        log(f"{'점수':>5} {'평소배수':>7} {'구독배수':>7} {'조회수':>9} {'시간':>5} {'최근':>4}  통과  채널 | 제목")
        for item in scored[:15]:
            log(
                f"{item['score']:>5} {format_ratio(item.get('multiplier')):>7} {format_ratio(item.get('sub_ratio')):>7} "
                f"{item['views']:>9,} {item['age_hours']:>5.0f} {item.get('trend', '-'):>4}  {'O' if item['passes'] else '-':^4}  "
                f"{item['channel_title'][:14]} | {item['title'][:50]}"
            )
    if dry_run:
        for message in messages:
            print("\n" + message)
    else:
        for message in messages:
            send_telegram(message)
        for item in alerts_sent:
            for video in [item, *item.get("cluster_items", [])]:
                alerted[video["video_id"]] = iso(now)
            for key in dedupe_keys(item):
                alerted_topics[key] = iso(now)
        if want_summary:
            state["last_summary_date"] = today

    snapshot_cutoff = now - window - timedelta(hours=24)
    for video_id in [key for key, value in snapshots.items() if (parse_time(value.get("published_at")) or now) < snapshot_cutoff]:
        snapshots.pop(video_id, None)
    for memory in (alerted, alerted_topics, state.setdefault("upstream_searched", {})):
        for key in [key for key, value in memory.items() if (parse_time(value) or now) < now - timedelta(days=14)]:
            memory.pop(key, None)
    quota["used"] += yt.used
    daily["alerts"] += 0 if dry_run else len(alerts_sent)
    state["quota"] = quota
    state["daily"] = daily
    state["pool"] = pool_list
    state["last_run"] = {
        "at": iso(now),
        "quota_used": yt.used,
        "queries": searched_queries,
        "candidates": len(scored),
        "passing": len([item for item in scored if item["passes"]]),
        "alerts": len(alerts_sent),
        "errors": errors,
    }

    latest = {
        "generated_at": iso(now),
        "window_hours": window_hours,
        "quota_used": yt.used,
        "queries": searched_queries,
        "upstream": upstream,
        "alerts": [compact_candidate(item) for item in alerts_sent],
        "candidates": [compact_candidate(item) for item in scored[:50]],
        "errors": errors,
    }
    if not test_mode:
        write_json(LATEST_FILE, latest)
    if not dry_run:
        write_json(STATE_FILE, state)

    log(
        f"[radar] 후보 {len(scored)}개 · 통과 {state['last_run']['passing']}개 · 알림 {len(alerts_sent)}건 · "
        f"요약 {'O' if want_summary else '-'} · 쿼터 {yt.used} · 오류 {len(errors)}"
    )
    for error in errors:
        log(f"  ! {error}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="vidIQ식 아웃라이어 레이더")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램을 보내지 않고 상태도 저장하지 않는다")
    parser.add_argument("--query", help="시험 모드: 이 검색어 하나만 돌려 판정까지 보여 준다 (기본은 발송 안 함)")
    parser.add_argument("--send", action="store_true", help="시험 모드에서도 텔레그램을 보낸다")
    parser.add_argument("--window-hours", type=int, help="최근 몇 시간 영상까지 볼지 (기본: 설정값)")
    parser.add_argument("--summary", action="store_true", help="시간과 관계없이 요약을 만든다")
    parser.add_argument("--table", action="store_true", help="점수표를 출력한다")
    parser.add_argument("--no-watchlist", action="store_true")
    parser.add_argument("--no-upstream", action="store_true")
    parser.add_argument("--no-search", action="store_true")
    parser.add_argument("--env-file", help=".env 경로 (기본: 저장소 루트)")
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
