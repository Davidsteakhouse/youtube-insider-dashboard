from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import os
import re
from typing import Any

from common import parse_datetime, utcnow_iso, within_lookback_hours

GENERIC_TOPIC_LABELS = {
    "ai",
    "뉴스",
    "뉴스 분석",
    "미분류",
    "기타",
    "비교",
    "comparison",
    "news",
}

CANONICAL_CLUSTER_LABELS = {
    "automation": "자동화",
    "research": "리서치",
    "coding": "코딩",
    "comparison": "비교",
    "news": "뉴스",
    "gpt-5": "GPT-5",
    "gemini": "Gemini",
    "claude": "Claude",
    "ai": "AI",
    "chatgpt": "ChatGPT",
}

AI_PRIORITY_TERMS = {
    "ai",
    "gpt",
    "chatgpt",
    "claude",
    "gemini",
    "cursor",
    "copilot",
    "mcp",
    "agent",
    "automation",
    "workflow",
    "llm",
    "prompt",
    "notion ai",
    "perplexity",
}

AI_CREATOR_EMPTY_ANGLES = {
    "GPT-5": "업데이트 요약보다 '기존 워크플로우에서 뭐가 실제로 빨라졌는지'를 보여주는 콘텐츠 영역이 아직 비어 있습니다.",
    "ChatGPT": "기능 소개보다 '지금 바로 복붙해서 쓰는 프롬프트/자동화 루틴'으로 좁힌 콘텐츠 영역이 비어 있습니다.",
    "Claude": "성능 비교 대신 '리서치와 문서 정리에서 Claude를 어떻게 배치하는지'를 보여주는 실무형 콘텐츠 영역이 비어 있습니다.",
    "Gemini": "신기능 나열보다 'Google 생태계 안에서 실제 작업이 얼마나 바뀌는지'를 검증하는 콘텐츠 영역이 비어 있습니다.",
    "자동화": "툴 나열보다 '반복 업무 한 장면을 자동화 전/후로 비교하는 사례형 콘텐츠'가 비어 있습니다.",
    "리서치": "리서치 자체보다 '영상 기획 전에 어떤 질문 순서로 브리프를 뽑는지'를 보여주는 프로세스형 콘텐츠 영역이 비어 있습니다.",
}


def normalize_label(value: str | None) -> str:
    return " ".join(str(value or "").strip().split())


def normalized_search_text(value: str | None) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]+", " ", normalize_label(value).lower()).strip()


def contains_priority_term(text: str, term: str) -> bool:
    haystack = f" {normalized_search_text(text)} "
    needle = normalized_search_text(term)
    return bool(needle) and f" {needle} " in haystack


def compact_number(value: float | int | None) -> str:
    safe = float(value or 0)
    if safe >= 1_000_000:
        return f"{safe / 1_000_000:.1f}M"
    if safe >= 1_000:
        return f"{safe / 1_000:.1f}K"
    return f"{int(safe)}"


def percent_text(value: float | int | None) -> str:
    return f"{float(value or 0) * 100:.1f}%"


def truncate_text(value: str, max_length: int = 110) -> str:
    text = normalize_label(value)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1].rstrip()}…"


def pick_recent_videos(videos: list[dict[str, Any]], *, lookback_hours: int = 24) -> list[dict[str, Any]]:
    recent: list[dict[str, Any]] = []
    for video in videos:
        if within_lookback_hours(video.get("published_at"), lookback_hours=lookback_hours):
            recent.append(video)
    return sorted(recent, key=lambda item: item.get("published_at") or "", reverse=True)


def classify_topic_cluster(video: dict[str, Any]) -> str:
    label_sources = [
        *[normalize_label(tool) for tool in video.get("tools", [])],
        *[normalize_label(tag) for tag in video.get("topic_tags", [])],
        *[normalize_label(keyword) for keyword in video.get("keywords", [])],
        normalize_label(video.get("format")),
    ]
    for label in label_sources:
        lowered = label.lower()
        if not label or lowered in GENERIC_TOPIC_LABELS:
            continue
        return CANONICAL_CLUSTER_LABELS.get(lowered, label)
    for label in label_sources:
        if label:
            return CANONICAL_CLUSTER_LABELS.get(label.lower(), label)
    return "기타"


def video_text(video: dict[str, Any]) -> str:
    return " ".join(
        [
            normalize_label(video.get("title")),
            normalize_label(video.get("one_line_summary")),
            " ".join(normalize_label(item) for item in video.get("topic_tags", [])),
            " ".join(normalize_label(item) for item in video.get("tools", [])),
            " ".join(normalize_label(item) for item in video.get("keywords", [])),
            " ".join(normalize_label(item) for item in video.get("transcript_highlights", [])),
            normalize_label(video.get("transcript_text"))[:1200],
        ]
    ).lower()


def channel_text(channel: dict[str, Any]) -> str:
    return " ".join(
        [
            normalize_label(channel.get("name")),
            normalize_label(channel.get("category")),
            normalize_label(channel.get("description")),
        ]
    ).lower()


def is_ai_relevant(video: dict[str, Any]) -> bool:
    title_text = normalize_label(video.get("title"))
    tool_text = " ".join(normalize_label(item) for item in video.get("tools", []))
    topic_text = " ".join(
        normalize_label(item)
        for item in video.get("topic_tags", [])
        if normalize_label(item).lower() not in {"ai"}
    )
    if any(contains_priority_term(title_text, term) for term in AI_PRIORITY_TERMS):
        return True
    if any(contains_priority_term(tool_text, term) for term in AI_PRIORITY_TERMS):
        return True
    if any(contains_priority_term(topic_text, term) for term in AI_PRIORITY_TERMS if term != "ai"):
        return True

    channel = video.get("channel", {}) or {}
    channel_category = normalize_label(channel.get("category"))
    channel_name = normalize_label(channel.get("name"))
    if contains_priority_term(channel_category, "ai"):
        return True
    if contains_priority_term(channel_name, "ai") and any(
        contains_priority_term(title_text, term) for term in {"automation", "agent", "workflow", "gpt", "claude", "gemini", "copilot", "cursor"}
    ):
        return True
    return False


def pick_creator_scope_videos(videos: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    ai_videos = [video for video in videos if is_ai_relevant(video)]
    if ai_videos:
        return ai_videos, "ai_creator_priority"
    return videos, "all_watchlist"


def count_topic_clusters(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for video in videos:
        grouped[classify_topic_cluster(video)].append(video)

    clusters: list[dict[str, Any]] = []
    for label, items in grouped.items():
        ranked_items = sorted(
            items,
            key=lambda item: (
                int(item.get("view_count", 0) or 0),
                float(item.get("engagement_rate", 0) or 0),
                int(item.get("like_count", 0) or 0),
            ),
            reverse=True,
        )
        representative = ranked_items[0]
        avg_view_count = sum(float(item.get("view_count", 0) or 0) for item in items) / len(items)
        avg_engagement = sum(float(item.get("engagement_rate", 0) or 0) for item in items) / len(items)
        avg_like_count = sum(float(item.get("like_count", 0) or 0) for item in items) / len(items)
        avg_comment_count = sum(float(item.get("comment_count", 0) or 0) for item in items) / len(items)
        clusters.append(
            {
                "label": label,
                "count": len(items),
                "avg_view_count": round(avg_view_count),
                "avg_engagement_rate": avg_engagement,
                "avg_like_count": round(avg_like_count),
                "avg_comment_count": round(avg_comment_count),
                "source_titles": [item.get("title", "제목 없음") for item in ranked_items[:3]],
                "thumbnail_url": representative.get("thumbnail_url", ""),
                "representative_video_id": representative.get("video_id", ""),
                "representative_title": representative.get("title", "제목 없음"),
            }
        )

    clusters.sort(
        key=lambda item: (
            int(item.get("count", 0) or 0),
            float(item.get("avg_view_count", 0) or 0),
            float(item.get("avg_engagement_rate", 0) or 0),
        ),
        reverse=True,
    )
    return clusters[:8]


def build_comment_signal(video: dict[str, Any]) -> str:
    comments = video.get("top_comments", []) or []
    if comments:
        first = comments[0]
        if isinstance(first, dict):
            return truncate_text(first.get("text", ""), 96)
        return truncate_text(str(first), 96)

    comment_count = int(video.get("comment_count", 0) or 0)
    if comment_count >= 100:
        return "댓글 반응이 빠르게 형성된 영상입니다."
    if comment_count > 0:
        return "초기 댓글 반응은 붙었지만 아직 대화가 확장되지는 않았습니다."
    return "댓글 반응은 아직 약한 편입니다."


def build_video_highlights(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        videos,
        key=lambda item: (
            int(item.get("view_count", 0) or 0),
            float(item.get("engagement_rate", 0) or 0),
            int(item.get("like_count", 0) or 0),
        ),
        reverse=True,
    )

    highlights: list[dict[str, Any]] = []
    for video in ranked[:5]:
        highlights.append(
            {
                "video_id": video.get("video_id"),
                "channel_name": video.get("channel_name") or "알 수 없는 채널",
                "title": video.get("title", "제목 없음"),
                "thumbnail_url": video.get("thumbnail_url", ""),
                "video_url": video.get("video_url", ""),
                "published_at": video.get("published_at"),
                "view_count": int(video.get("view_count", 0) or 0),
                "like_count": int(video.get("like_count", 0) or 0),
                "comment_count": int(video.get("comment_count", 0) or 0),
                "engagement_rate": float(video.get("engagement_rate", 0) or 0),
                "topic_cluster": classify_topic_cluster(video),
                "summary": truncate_text(video.get("one_line_summary", ""), 92),
                "comment_signal": build_comment_signal(video),
                "hook_type": normalize_label(video.get("hook_type")) or "문제 해결",
            }
        )
    return highlights


def pick_best_video(videos: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not videos:
        return None
    return max(
        videos,
        key=lambda item: (
            int(item.get("view_count", 0) or 0),
            float(item.get("engagement_rate", 0) or 0),
            int(item.get("like_count", 0) or 0),
        ),
    )


def pick_best_topic(topic_clusters: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not topic_clusters:
        return None
    candidates = [
        cluster for cluster in topic_clusters
        if normalize_label(cluster.get("label", "")).lower() not in GENERIC_TOPIC_LABELS
    ] or topic_clusters
    return max(
        candidates,
        key=lambda item: (
            int(item.get("count", 0) or 0),
            float(item.get("avg_view_count", 0) or 0),
            float(item.get("avg_engagement_rate", 0) or 0),
        ),
    )


def build_summary(videos: list[dict[str, Any]], best_video: dict[str, Any] | None, best_topic: dict[str, Any] | None) -> str:
    if not videos:
        return "최근 24시간 내 수집된 영상이 없습니다."
    if not best_video or not best_topic:
        return f"최근 24시간 기준 신규 영상 {len(videos)}개가 수집되었습니다."
    return (
        f"최근 24시간 영상 {len(videos)}개를 기준으로 보면, 오늘 가장 먼저 볼 축은 '{best_topic['label']}'입니다. "
        f"특히 '{best_video.get('title', '제목 없음')}'는 조회수 {compact_number(best_video.get('view_count', 0))}, "
        f"참여율 {percent_text(best_video.get('engagement_rate', 0))}로 가장 강하게 반응했습니다."
    )


def build_summary_points(videos: list[dict[str, Any]], best_video: dict[str, Any] | None, best_topic: dict[str, Any] | None) -> list[str]:
    if not videos:
        return ["최근 24시간 내 확인할 신규 영상이 없습니다."]
    points: list[str] = []
    if best_topic:
        points.append(
            f"가장 겹친 주제는 '{best_topic['label']}'이며 {best_topic['count']}개 영상, 평균 조회수 {compact_number(best_topic['avg_view_count'])}, 평균 참여율 {percent_text(best_topic['avg_engagement_rate'])}입니다."
        )
    if best_video:
        points.append(
            f"최고 실적 영상은 '{best_video.get('title', '제목 없음')}'이며 {normalize_label(best_video.get('hook_type')) or '문제 해결'} 훅과 {normalize_label(best_video.get('format')) or '정보형'} 포맷 조합이 강했습니다."
        )
    if videos:
        repeated_tools = Counter(tool for video in videos for tool in (video.get("tools") or [])).most_common(2)
        if repeated_tools:
            joined = ", ".join(f"{label} {count}회" for label, count in repeated_tools)
            points.append(f"반복 노출된 툴은 {joined} 순이어서, 크리에이터 관점에서는 같은 툴을 다른 사용 장면으로 분화해 다루는 편이 좋습니다.")
    return points[:3]


def build_action_chips(best_video: dict[str, Any] | None, best_topic: dict[str, Any] | None) -> list[str]:
    chips: list[str] = []
    if best_topic:
        chips.append(f"주제: {best_topic['label']}")
    if best_video and best_video.get("hook_type"):
        chips.append(f"훅: {best_video['hook_type']}")
    if best_video and best_video.get("format"):
        chips.append(f"포맷: {best_video['format']}")
    if best_video and best_video.get("channel_name"):
        chips.append(f"기준 채널: {best_video['channel_name']}")
    return chips[:4]


def build_creator_takeaway(videos: list[dict[str, Any]], best_video: dict[str, Any] | None, best_topic: dict[str, Any] | None) -> str:
    if not best_video or not best_topic:
        return "오늘은 먼저 업로드 수와 댓글 반응이 붙는 영상부터 확인하세요."
    topic_label = best_topic["label"]
    tools = [normalize_label(tool) for tool in (best_video.get("tools") or []) if normalize_label(tool)]
    lead_tool = tools[0] if tools else topic_label
    if topic_label in {"GPT-5", "ChatGPT", "Claude", "Gemini"}:
        return (
            f"오늘은 '{topic_label}'를 넓은 뉴스 묶음으로 따라가기보다, '{lead_tool}' 하나를 대표 썸네일로 세우고 "
            "실제 워크플로우 한 장면을 앞 20초 안에 보여주는 구성이 더 유리합니다. "
            "업데이트 나열보다 '이 기능을 쓰면 뭐가 바로 빨라지는지'를 먼저 못 박는 편이 클릭과 시청 유지에 모두 좋습니다."
        )
    if topic_label == "리서치":
        return (
            "리서치 주제는 결과 요약보다 '어떤 질문 순서로 자료를 뽑고, 그걸 어떻게 영상 기획으로 연결하는지'를 보여줄 때 더 강합니다. "
            "즉, 정보 자체보다 프로세스를 전면에 두는 편이 크리에이터 관점에서 재사용 가치가 높습니다."
        )
    return (
        f"오늘은 '{best_topic['label']}' 주제를 단순 뉴스 요약으로 따라가기보다, "
        f"'{best_video.get('title', '제목 없음')}'처럼 실제 사용 장면과 결과를 앞쪽에 배치하는 쪽이 유리합니다. "
        f"특히 {normalize_label(best_video.get('hook_type')) or '문제 해결'} 훅과 {normalize_label(best_video.get('format')) or '정보형'} 포맷 조합을 눈여겨보세요."
    )


def build_title_suggestions(best_topic: dict[str, Any] | None, best_video: dict[str, Any] | None) -> list[str]:
    topic_label = best_topic.get("label") if best_topic else "AI"
    seed_title = normalize_label(best_video.get("title", "")) if best_video else ""
    if "Claude" in topic_label:
        return [
            "Claude를 리서치 실무에 붙이면 달라지는 3가지",
            "Claude 브리핑 워크플로우, 크리에이터가 바로 쓰는 방식만 정리",
            "Claude 관련 영상이 몰린 날, 내 채널에 바로 적용하는 포장법",
        ]
    if "Gemini" in topic_label:
        return [
            "Gemini 업데이트를 바로 콘텐츠로 바꾸는 가장 쉬운 방식",
            "Gemini 최신 기능, 크리에이터가 실제로 써볼 포인트만 정리",
            "Gemini 관련 경쟁 영상, 제목과 포장 구조만 뜯어봤습니다",
        ]
    if "GPT" in topic_label or "ChatGPT" in topic_label:
        return [
            "GPT 업데이트보다 중요한 건 실제 사용 장면입니다",
            "GPT 관련 경쟁 영상이 강한 이유, 제목과 포장만 분석했습니다",
            "GPT 주제로 오늘 바로 만들 수 있는 후속 아이디어 3개",
        ]
    if topic_label == "자동화":
        return [
            "자동화 영상이 뜨는 날, 내 채널은 어디를 좁혀야 할까?",
            "툴 나열 말고 자동화 한 장면으로 클릭을 만드는 법",
            "자동화 경쟁 영상에서 바로 가져올 수 있는 콘텐츠 구조",
        ]
    if topic_label == "리서치":
        return [
            "리서치 영상을 내 채널 기획 프로세스로 바꾸는 방법",
            "리서치 브리핑 영상이 먹히는 이유와 바로 써먹는 구조",
            "리서치 관련 경쟁 영상이 몰린 날, 내가 먼저 찍을 제목",
        ]
    if seed_title:
        return [
            f"{topic_label} 주제를 내 채널 관점으로 다시 잘라보자",
            f"{seed_title}에서 바로 뽑아온 후속 콘텐츠 아이디어",
            f"{topic_label}를 지금 찍는다면 이렇게 포장하면 됩니다",
        ]
    return [
        f"{topic_label} 관련 경쟁 채널 반응 정리",
        f"{topic_label} 주제로 오늘 바로 만들면 좋은 영상",
        f"{topic_label}를 내 채널 포맷으로 바꾸는 방법",
    ]


def build_thumbnail_copy(topic_label: str, hook_type: str) -> str:
    if "비교" in hook_type:
        return f"{topic_label} 뭐가 다를까?"
    if "강한 주장" in hook_type or "긴급성" in hook_type:
        return f"{topic_label} 지금 봐야 함"
    if "문제" in hook_type:
        return f"{topic_label} 바로 해결"
    return f"{topic_label} 핵심 3가지"


def creator_packaging_angle(video: dict[str, Any], topic_label: str) -> str:
    hook_type = normalize_label(video.get("hook_type")) or "문제 해결"
    tools = [normalize_label(tool) for tool in (video.get("tools") or []) if normalize_label(tool)]
    lead_tool = tools[0] if tools else topic_label
    if topic_label in {"GPT-5", "ChatGPT", "Claude", "Gemini"}:
        return (
            f"'{lead_tool}'를 제목 첫머리에 두고, 큰 트렌드 설명보다 "
            "지금 당장 써볼 수 있는 실무 장면 1개와 후속 변화 2개만 묶어 압축하는 포장이 좋습니다."
        )
    if topic_label == "자동화":
        return "자동화 전체를 설명하지 말고, 반복 업무 하나를 전/후 비교 화면으로 보여주는 식으로 포장을 좁히는 편이 좋습니다."
    if topic_label == "리서치":
        return "리서치 결과물보다 질문 순서, 프롬프트, 정리 화면을 함께 보여줘서 프로세스 자체를 상품화하는 포장이 좋습니다."
    if "문제 해결" in hook_type:
        return "제목 첫 문장에서 문제를 못 박고, 본문 초반에 바로 해결 결과를 보여주는 식으로 압축하는 편이 유리합니다."
    return "큰 주제 하나를 대표 제목으로 세우고, 나머지 포인트는 보조 정보처럼 정리하는 압축형 포장이 좋습니다."


def creator_empty_angle(video: dict[str, Any], topic_label: str) -> str:
    return AI_CREATOR_EMPTY_ANGLES.get(
        topic_label,
        "기능 소개를 넘어 실제 작업 흐름에서 어디에 꽂을지, 어떤 사람이 가장 먼저 써봐야 하는지까지 좁힌 콘텐츠 영역이 비어 있습니다.",
    )


def creator_hook_line(video: dict[str, Any], topic_label: str) -> str:
    title = normalize_label(video.get("title"))
    if "breakdown" in title.lower() or "full" in title.lower():
        return "첫 15초에 '이번 업데이트에서 진짜 써볼 만한 것만 추려준다'는 약속을 분명하게 주는 구조"
    if topic_label in {"GPT-5", "ChatGPT", "Claude", "Gemini"}:
        return "기능 발표보다 '내 일에서 뭐가 바로 바뀌는지'를 질문형으로 던지는 훅"
    return "지금 봐야 하는 이유를 먼저 박고, 세부 설명은 뒤로 미루는 압축형 훅"


def build_recommendations(videos: list[dict[str, Any]], title_suggestions: list[str], best_topic: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not videos:
        return []

    preferred_label = best_topic.get("label") if best_topic else None
    preferred = [video for video in videos if classify_topic_cluster(video) == preferred_label] if preferred_label else []
    candidates = preferred or videos
    ranked = sorted(
        candidates,
        key=lambda item: (
            int(item.get("view_count", 0) or 0),
            float(item.get("engagement_rate", 0) or 0),
            int(item.get("comment_count", 0) or 0),
        ),
        reverse=True,
    )

    recommendations: list[dict[str, Any]] = []
    for index, video in enumerate(ranked[:3]):
        topic_label = classify_topic_cluster(video)
        title = title_suggestions[index] if index < len(title_suggestions) else video.get("title", "제목 없음")
        recommendations.append(
            {
                "title": title,
                "hook": creator_hook_line(video, topic_label),
                "angle": creator_packaging_angle(video, topic_label),
                "thumbnail_copy": build_thumbnail_copy(topic_label, normalize_label(video.get("hook_type")) or "문제 해결"),
                "reason": creator_empty_angle(video, topic_label),
                "source_video_id": video.get("video_id"),
                "source": video.get("title", "제목 없음"),
            }
        )
    return recommendations


def build_keyword_counts(videos: list[dict[str, Any]], *, key: str, limit: int = 8) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for video in videos:
        seen: set[str] = set()
        for raw_value in video.get(key, []) or []:
            label = normalize_label(raw_value)
            if not label:
                continue
            lowered = label.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            counter[label] += 1
    return [{"label": label, "count": count} for label, count in counter.most_common(limit)]


def build_telegram_preview(
    videos: list[dict[str, Any]],
    best_video: dict[str, Any] | None,
    best_topic: dict[str, Any] | None,
    title_suggestions: list[str],
) -> str:
    if not videos:
        return "📡 YouTube Insider _ v2\n최근 24시간 내 수집된 영상이 없습니다."

    topic_line = (
        f"{best_topic['label']} · {best_topic['count']}개 · 평균 조회수 {compact_number(best_topic['avg_view_count'])} · 평균 참여율 {percent_text(best_topic['avg_engagement_rate'])}"
        if best_topic
        else "주제 클러스터를 아직 계산하지 못했습니다."
    )
    top_title = title_suggestions[0] if title_suggestions else "오늘은 최고 실적 주제를 내 채널 포맷으로 바꿔보세요."
    dashboard_url = str(os.getenv("PUBLIC_DASHBOARD_URL", "") or "").strip()
    message = (
        "📡 YouTube Insider _ v2\n\n"
        f"🗓 최근 24시간 영상 {len(videos)}개\n\n"
        f"🏆 오늘 최고 실적 영상\n"
        f"• {best_video.get('channel_name', '알 수 없는 채널') if best_video else '알 수 없는 채널'}\n"
        f"• {best_video.get('title', '제목 없음') if best_video else '제목 없음'}\n"
        f"• 조회수 {compact_number(best_video.get('view_count', 0) if best_video else 0)} · "
        f"좋아요 {compact_number(best_video.get('like_count', 0) if best_video else 0)} · "
        f"댓글 {compact_number(best_video.get('comment_count', 0) if best_video else 0)} · "
        f"참여율 {percent_text(best_video.get('engagement_rate', 0) if best_video else 0)}\n\n"
        f"📌 오늘 최고 실적 주제\n• {topic_line}\n\n"
        f"💡 추천 제목\n• {top_title}"
    )
    if dashboard_url:
        message += f"\n\n🔎 자세히 보기\n{dashboard_url}"
    return message


def build_digest(videos: list[dict[str, Any]], watchlist: list[dict[str, Any]]) -> dict[str, Any]:
    channel_lookup = {
        channel.get("youtube_channel_id") or channel.get("channel_key") or channel.get("url") or channel.get("name"): channel
        for channel in watchlist
    }

    recent_videos = pick_recent_videos(videos)
    hydrated_recent: list[dict[str, Any]] = []
    for video in recent_videos:
        channel = channel_lookup.get(video.get("channel_id")) or channel_lookup.get(video.get("channel_key")) or {}
        hydrated_recent.append(
            {
                **video,
                "channel_name": video.get("channel_name") or channel.get("name") or "알 수 없는 채널",
                "channel": channel,
                "channel_category": channel.get("category", "미분류"),
            }
        )

    digest_videos, focus_scope = pick_creator_scope_videos(hydrated_recent)
    topic_clusters = count_topic_clusters(digest_videos)
    best_video = pick_best_video(digest_videos)
    best_topic = pick_best_topic(topic_clusters)

    average_view_count = (
        sum(float(video.get("view_count", 0) or 0) for video in digest_videos) / len(digest_videos)
        if digest_videos
        else 0
    )
    average_engagement_rate = (
        sum(float(video.get("engagement_rate", 0) or 0) for video in digest_videos) / len(digest_videos)
        if digest_videos
        else 0
    )
    average_like_count = (
        sum(float(video.get("like_count", 0) or 0) for video in digest_videos) / len(digest_videos)
        if digest_videos
        else 0
    )
    average_comment_count = (
        sum(float(video.get("comment_count", 0) or 0) for video in digest_videos) / len(digest_videos)
        if digest_videos
        else 0
    )

    title_suggestions = build_title_suggestions(best_topic, best_video)
    recommendations = build_recommendations(digest_videos, title_suggestions, best_topic)
    video_highlights = build_video_highlights(digest_videos)

    return {
        "generated_at": utcnow_iso(),
        "summary": build_summary(digest_videos, best_video, best_topic),
        "summary_points": build_summary_points(digest_videos, best_video, best_topic),
        "action_chips": build_action_chips(best_video, best_topic),
        "creator_takeaway": build_creator_takeaway(digest_videos, best_video, best_topic),
        "topic_clusters": topic_clusters,
        "title_suggestions": title_suggestions,
        "recommendations": recommendations,
        "video_highlights": video_highlights,
        "telegram_preview": build_telegram_preview(digest_videos, best_video, best_topic, title_suggestions),
        "video_count": len(digest_videos),
        "total_recent_video_count": len(hydrated_recent),
        "focus_scope": focus_scope,
        "keyword_counts": build_keyword_counts(digest_videos, key="topic_tags"),
        "tool_counts": build_keyword_counts(digest_videos, key="tools"),
        "format_counts": [{"label": label, "count": count} for label, count in Counter(
            normalize_label(video.get("format", "미분류")) for video in digest_videos
        ).most_common(8)],
        "average_view_count": round(average_view_count),
        "average_engagement_rate": average_engagement_rate,
        "average_like_count": round(average_like_count),
        "average_comment_count": round(average_comment_count),
        "best_video_id": best_video.get("video_id") if best_video else "",
        "best_topic": best_topic.get("label") if best_topic else "",
    }
