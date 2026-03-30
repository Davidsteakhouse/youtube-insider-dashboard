from __future__ import annotations

import json
import os
import re
from typing import Any

from common import request_json


OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
GEMINI_ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"
KNOWN_TOOLS = [
    "OpenAI",
    "ChatGPT",
    "Claude",
    "Gemini",
    "Cursor",
    "MCP",
    "Perplexity",
    "Notion",
    "Zapier",
    "Supabase",
    "Whisper",
    "Beehiiv",
    "Arc"
]
SYSTEM_PROMPT = (
    "당신은 AI 유튜브 경쟁채널 분석 전문가다. 반드시 JSON만 반환하라. "
    "키는 format, hook_type, title_pattern, topic_tags, keywords, tools, one_line_summary, "
    "why_it_works, recommendation, flow, claims, transcript_highlights 로 고정한다. "
    "모든 문자열과 배열 내부 문장은 반드시 자연스러운 한국어로 작성하라. "
    "영어 제목이나 영어 자막이어도 최종 요약은 한국어로 번역해서 반환하라. "
    "recommendation은 3~5개 bullet 느낌의 실행 포인트를 한 문자열 안에 '• '로 구분해 작성하라. "
    "이 분석의 활용자는 '스마트대디' 유튜브 채널 운영자다. "
    "스마트대디 채널 특성: "
    "① 타겟 — AI 용어가 낯선 일반인(직장인/주부/학생), "
    "② 포지셔닝 — 가르치는 선생님이 아닌 먼저 시도하는 AI 모험가, "
    "③ 핵심 포맷 — VS 비교와 리얼 실험기('이게 될까?' → '진짜 되네!'), "
    "④ 피해야 할 것 — 뉴스 나열, 기능 스펙 설명, 감성 의존 구성. "
    "recommendation은 반드시 스마트대디가 이 영상에서 벤치마킹할 수 있는 "
    "VS 비교 각도, 일반인도 이해할 수 있는 실험 구도, "
    "경쟁 채널이 아직 안 한 대결 콘텐츠 영역을 포함하라."
)
FORMAT_RULES = [
    (r"talking head|news", "뉴스 분석"),
    (r"screen recording|tutorial|workflow", "워크플로우 튜토리얼"),
    (r"demo", "빌드 데모"),
    (r"case study|analysis", "사례 분석"),
    (r"video essay|explainer", "비교/해설"),
]
HOOK_RULES = [
    (r"provocative|strong claim|statement|replace|urgent|breaking", "강한 주장"),
    (r"problem.?solution|time|save|faster", "문제 해결"),
    (r"comparison|compare|versus|difference", "비교"),
    (r"statistic|outcome|mrr|revenue|money", "성과 약속"),
    (r"demo|experiment|build", "실험 데모"),
]
CANONICAL_TOOL_RULES = [
    ("GPT-5", [r"gpt-5"]),
    ("ChatGPT", [r"chatgpt", r"openai"]),
    ("Claude", [r"claude"]),
    ("Gemini", [r"gemini"]),
    ("Cursor", [r"cursor"]),
    ("MCP", [r"\bmcp\b"]),
    ("Perplexity", [r"perplexity"]),
    ("Whisper", [r"whisper"]),
    ("Notion", [r"notion"]),
    ("Zapier", [r"zapier"]),
    ("Supabase", [r"supabase"]),
    ("에이전트 프레임워크", [r"auto-gpt", r"babyagi", r"langchain", r"agent framework"]),
]
CANONICAL_TAG_RULES = [
    ("GPT-5", [r"gpt-5"]),
    ("Gemini", [r"gemini"]),
    ("Claude", [r"claude"]),
    ("에이전트", [r"\bagent", r"\bagents"]),
    ("자동화", [r"automation", r"workflow"]),
    ("한국어 자막", [r"korean", r"transcript", r"subtitle", r"subtitl"]),
    ("리서치", [r"research", r"brief"]),
    ("코딩", [r"cursor", r"code", r"repo", r"\bmcp\b"]),
    ("수익화", [r"mrr", r"revenue", r"monetization", r"brand"]),
    ("비교", [r"versus", r"compare", r"difference"]),
    ("Perplexity", [r"perplexity"]),
]
KOREAN_TEXT_FIELDS = ("one_line_summary", "why_it_works", "recommendation")
KOREAN_LIST_FIELDS = ("flow", "claims", "transcript_highlights")
TRANSLATION_PROMPT = (
    "다음 JSON의 문자열을 자연스럽고 실무적인 한국어로 번역/정리하라. "
    "반드시 같은 키만 유지하고 JSON만 반환하라. "
    "문장 톤은 AI 유튜브 크리에이터가 바로 이해할 수 있는 수준으로 간결하게 맞춘다."
)


def normalize_label(value: str | None) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_text_field(value: Any, *, fallback: str = "") -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                return normalize_text_field(parsed, fallback=fallback)
            except Exception:
                pass
        return normalize_label(value) or fallback
    if isinstance(value, (int, float)):
        return normalize_label(str(value)) or fallback
    if isinstance(value, list):
        parts = [normalize_text_field(item) for item in value]
        return normalize_label(" ".join(part for part in parts if part)) or fallback
    if isinstance(value, dict):
        preferred = [
            value.get("text"),
            value.get("summary"),
            value.get("value"),
            value.get("title"),
            value.get("reason"),
            value.get("angle"),
            value.get("hook"),
            value.get("click_appeal"),
            value.get("clickability_why"),
            value.get("recommended_title"),
            value.get("suggested_title"),
            value.get("thumbnail_copy_hint"),
            value.get("thumbnail_hint"),
            value.get("gaps_for_followup"),
            value.get("unfilled_angles"),
            value.get("replication_elements"),
        ]
        joined = " ".join(normalize_text_field(item) for item in preferred if item)
        if joined:
            return normalize_label(joined)
        return normalize_label(json.dumps(value, ensure_ascii=False)) or fallback
    return fallback


def normalize_text_list(value: Any, *, limit: int = 5) -> list[str]:
    if isinstance(value, list):
        cleaned = [normalize_text_field(item) for item in value]
        return [item for item in cleaned if item][:limit]
    if isinstance(value, str):
        lines = [normalize_label(item) for item in re.split(r"[\n•\-]+", value)]
        return [item for item in lines if item][:limit]
    return []


def has_hangul(text: str | None) -> bool:
    return bool(re.search(r"[가-힣]", str(text or "")))


def needs_korean_localization(analysis: dict[str, Any]) -> bool:
    for field in KOREAN_TEXT_FIELDS:
        value = normalize_text_field(analysis.get(field))
        if value and not has_hangul(value):
            return True
    for field in KOREAN_LIST_FIELDS:
        values = normalize_text_list(analysis.get(field), limit=5)
        if values and not any(has_hangul(item) for item in values):
            return True
    return False


def translate_analysis_fields_with_gemini(analysis: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {}

    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    subset = {field: analysis.get(field) for field in [*KOREAN_TEXT_FIELDS, *KOREAN_LIST_FIELDS]}
    payload = {
        "systemInstruction": {"parts": [{"text": TRANSLATION_PROMPT}]},
        "generationConfig": {"responseMimeType": "application/json"},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": json.dumps(subset, ensure_ascii=False)}],
            }
        ],
    }

    try:
        response = request_json(
            GEMINI_ENDPOINT_TEMPLATE.format(model=model),
            method="POST",
            params={"key": api_key},
            payload=payload,
            timeout=60,
        )
        content = clean_json_text(response["candidates"][0]["content"]["parts"][0]["text"])
        parsed = json.loads(content)
        return {
            "one_line_summary": normalize_text_field(parsed.get("one_line_summary")),
            "why_it_works": normalize_text_field(parsed.get("why_it_works")),
            "recommendation": normalize_text_field(parsed.get("recommendation")),
            "flow": normalize_text_list(parsed.get("flow"), limit=5),
            "claims": normalize_text_list(parsed.get("claims"), limit=5),
            "transcript_highlights": normalize_text_list(parsed.get("transcript_highlights"), limit=5),
        }
    except Exception:
        return {}


def infer_format(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    # 한국어 패턴
    if any(token in text for token in ["vs", "versus", "compare", "difference", "비교", "대결", "차이", "뭐가 다"]):
        return "비교"
    if any(token in text for token in ["tutorial", "workflow", "how to", "방법", "사용법", "쓰는 법", "활용법", "따라하기", "세팅"]):
        return "워크플로우 튜토리얼"
    if any(token in text for token in ["build", "repo", "command", "mcp", "cursor", "만들어", "개발", "코딩", "자동화"]):
        return "빌드 데모"
    if any(token in text for token in ["mrr", "revenue", "$", "brand", "수익", "매출", "후기", "사용기", "한달", "일주일"]):
        return "사례 분석"
    return "뉴스 분석"


def infer_hook(title: str) -> str:
    lowered = title.lower()
    # 한국어 패턴
    if any(token in lowered for token in ["replace", "now", "urgent", "breaking", "드디어", "마침내", "출시", "공개", "발표", "긴급"]):
        return "긴급성"
    if any(token in lowered for token in ["beat", "save", "faster", "절약", "빠른", "줄이", "단축", "효율"]):
        return "시간 절약"
    if any(token in lowered for token in ["versus", "difference", "compare", "vs", "비교", "대결", "차이", "뭐가 나"]):
        return "비교"
    if any(token in lowered for token in ["mrr", "revenue", "money", "made", "수익", "돈", "매출", "만원", "억"]):
        return "수익"
    if any(token in lowered for token in ["build", "turned", "one command", "직접", "실험", "해봤", "써봤", "테스트"]):
        return "실험"
    if any(token in lowered for token in ["진짜", "솔직", "현실", "실제", "후기", "실망", "놀라"]):
        return "솔직 검증"
    return "문제 해결"


def infer_title_pattern(title: str, format_type: str) -> str:
    lowered = title.lower()
    if "versus" in lowered or "difference" in lowered or "비교" in lowered or "대결" in lowered:
        return "A 대 B + 실전 약속"
    if any(token in lowered for token in ["mrr", "revenue", "made", "수익", "매출"]):
        return "금액 수치 + 성과 서사"
    if any(token in lowered for token in ["replace", "now", "beat", "드디어", "마침내", "출시"]):
        return "강한 주장 + 결과 약속"
    if any(token in lowered for token in ["직접", "해봤", "써봤", "실험", "테스트"]):
        return "직접 실험 + 결과 공개"
    if format_type == "빌드 데모":
        return "툴 조합 + 압축 약속"
    return "핵심 포인트 직설형"


def infer_tools(text: str) -> list[str]:
    found = [tool for tool in KNOWN_TOOLS if tool.lower() in text.lower()]
    return found[:6]


def infer_topic_tags(text: str) -> list[str]:
    text = text.lower()
    tags = []
    mapping = {
        "agents": ["agent", "agents", "mcp", "에이전트"],
        "automation": ["automation", "workflow", "zapier", "자동화", "워크플로우"],
        "research": ["research", "search", "brief"],
        "coding": ["cursor", "repo", "code", "build"],
        "monetization": ["mrr", "revenue", "brand", "offer"],
        "transcript": ["transcript", "subtitle", "whisper"],
        "localization": ["korean", "localization"],
        "comparison": ["versus", "difference", "compare"],
        "news": ["release", "update", "breaking", "announced"]
    }
    for tag, keywords in mapping.items():
        if any(keyword in text for keyword in keywords):
            tags.append(tag)
    return tags[:6]


def unique_keywords(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        cleaned = re.sub(r"[^A-Za-z0-9가-힣@._+-]+", "", value).strip()
        if not cleaned:
            continue
        if cleaned.lower() in {item.lower() for item in seen}:
            continue
        seen.append(cleaned)
    return seen[:8]


def comment_texts(raw_comments: list[Any]) -> list[str]:
    texts: list[str] = []
    for item in raw_comments or []:
        if isinstance(item, dict):
            text = normalize_label(item.get("text"))
        else:
            text = normalize_label(str(item))
        if text:
            texts.append(text)
    return texts


def is_informative_description(text: str) -> bool:
    normalized = normalize_label(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    if len(normalized) < 24:
        return False
    if lowered.startswith("email") or "@" in normalized:
        return False
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return False
    return True


def sanitize_highlight_line(value: str | None) -> str:
    text = normalize_label(value)
    if not text:
        return ""
    lowered = text.lower()
    if len(text) < 12:
        return ""
    if lowered.startswith("email") or "@" in text:
        return ""
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return ""
    return text


def transcript_sentence_candidates(text: str, *, limit: int = 5) -> list[str]:
    normalized = normalize_label(text)
    if not normalized:
        return []
    parts = [
        sanitize_highlight_line(item)
        for item in re.split(r"(?<=[.!?。！？])\s+|(?<=다\.)\s+|(?<=요\.)\s+", normalized)
    ]
    return [item for item in parts if item][:limit]


def safe_transcript_highlights(video: dict[str, Any], candidate_highlights: list[str] | None = None) -> list[str]:
    cleaned = [
        sanitize_highlight_line(item)
        for item in (candidate_highlights if candidate_highlights is not None else video.get("transcript_highlights", []))
    ]
    filtered = [item for item in cleaned if item]
    if len(filtered) < 5 and video.get("transcript_text"):
        extra = transcript_sentence_candidates(video.get("transcript_text", ""), limit=8)
        merged: list[str] = []
        seen: set[str] = set()
        for item in [*filtered, *extra]:
            key = item.lower()
            if not item or key in seen:
                continue
            seen.add(key)
            merged.append(item)
        filtered = merged
    if filtered:
        return filtered[:5]
    if is_informative_description(video.get("description", "")):
        description = video.get("description", "")
        return transcript_sentence_candidates(description, limit=2) or [description[:140]]
    return ["자막을 확보하지 못해 제목·댓글·메타데이터 기준으로 분석했습니다."]


def fallback_analysis(video: dict[str, Any]) -> dict[str, Any]:
    title = video.get("title", "")
    description = video.get("description", "")
    combined = " ".join(
        [
            title,
            description,
            " ".join(comment_texts(video.get("top_comments", []))),
            video.get("transcript_text", "")
        ]
    )
    format_type = infer_format(title, description)
    topic_tags = infer_topic_tags(combined)
    tools = infer_tools(combined)
    hook_type = infer_hook(title)
    title_pattern = infer_title_pattern(title, format_type)
    primary_topic = topic_tags[0] if topic_tags else format_type
    suggested_title = f"{primary_topic} 이슈를 내 채널 관점으로 다시 정리해보자"
    thumbnail_copy = f"{primary_topic} 지금 봐야 할 3가지"
    recommendation_points = [
        f"훅 구조: 도입 15초 안에 '{hook_type}' 관점으로 문제를 못 박고, 왜 지금 봐야 하는지 먼저 선언합니다.",
        f"복제할 포장 요소: {format_type} 형식을 유지하되 {primary_topic}를 실제 사용 장면 1개와 결과 변화 2개로 더 좁혀 설명합니다.",
        f"비어 있는 콘텐츠 영역: '{primary_topic}가 내 작업 흐름에서 어디에 꽂히는가'를 사례 중심으로 보여주는 후속 영상이 비어 있습니다.",
        f"추천 제목: {suggested_title}",
        f"썸네일 카피 힌트: {thumbnail_copy}",
    ]

    return {
        "format": format_type,
        "hook_type": hook_type,
        "title_pattern": title_pattern,
        "topic_tags": topic_tags,
        "keywords": unique_keywords([*topic_tags, *tools, *title.split()[:4]]),
        "tools": tools,
        "one_line_summary": f"이 영상은 {primary_topic} 이슈를 {format_type} 포맷으로 압축해, 지금 왜 봐야 하는지와 실제 활용 맥락을 함께 보여줍니다.",
        "why_it_works": f"{hook_type} 훅으로 관심을 끌고, {format_type} 형식으로 내용을 빠르게 정리해 시청자가 '바로 써먹을 수 있다'고 느끼게 만듭니다.",
        "recommendation": " • ".join(recommendation_points),
        "flow": [
            "처음 15초 안에 문제를 선명하게 정의하고 왜 지금 봐야 하는지 못 박는다.",
            "중간 구간에서 툴, 사례, 비교 포인트를 빠르게 제시해 정보 밀도를 높인다.",
            "마지막에는 시청자가 바로 따라할 수 있는 다음 액션과 적용 예시로 닫는다."
        ],
        "claims": [
            "단순 소개보다 실제 사용 장면을 바로 보여주는 구조가 반응을 만든다.",
            "큰 담론보다 작은 병목 하나를 해결해주는 포장 방식이 클릭으로 이어지기 쉽다."
        ],
        "transcript_highlights": safe_transcript_highlights(video)
    }


def analyze_thumbnail(thumbnail_url: str) -> dict[str, Any]:
    """Gemini Vision으로 썸네일 패턴 분석. 실패 시 빈 dict 반환."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not thumbnail_url:
        return {}

    import base64
    import urllib.request
    try:
        req = urllib.request.Request(thumbnail_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            image_data = base64.b64encode(resp.read()).decode("utf-8")
    except Exception:
        return {}

    prompt = (
        "이 유튜브 썸네일을 분석해서 JSON으로만 반환하라. "
        "키: "
        "text_overlay(썸네일에 적힌 텍스트 내용, 없으면 null), "
        "face_visible(얼굴 등장 여부 true/false), "
        "expression(표정 묘사, 없으면 null), "
        "color_scheme(주요 색상 2-3개, 예: ['빨강', '검정']), "
        "layout_type(텍스트위주/얼굴중심/제품중심/혼합 중 하나), "
        "urgency_level(낮음/보통/높음). "
        "JSON만 반환하라."
    )

    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    payload = {
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": "image/jpeg", "data": image_data}},
                {"text": prompt},
            ]
        }],
        "generationConfig": {"responseMimeType": "application/json"},
    }

    try:
        response = request_json(
            GEMINI_ENDPOINT_TEMPLATE.format(model=model),
            method="POST",
            params={"key": api_key},
            payload=payload,
            timeout=30,
        )
        content = clean_json_text(response["candidates"][0]["content"]["parts"][0]["text"])
        return json.loads(content)
    except Exception:
        return {}


def build_prompt(video: dict[str, Any]) -> dict[str, Any]:
    return {
        "video_id": video.get("video_id"),
        "title": video.get("title"),
        "description": video.get("description"),
        "published_at": video.get("published_at"),
        "view_count": video.get("view_count"),
        "like_count": video.get("like_count"),
        "comment_count": video.get("comment_count"),
        "top_comments": comment_texts(video.get("top_comments", []))[:3],
        "transcript_language": video.get("transcript_language"),
        "transcript_status": video.get("transcript_status"),
        "output_language": "ko",
        "transcript_text": (video.get("transcript_text", "") or "")[:12000]
    }


def canonicalize_format(value: str, title: str, description: str) -> str:
    text = normalize_label(f"{value} {title} {description}").lower()
    for pattern, label in FORMAT_RULES:
        if re.search(pattern, text):
            return label
    return infer_format(title, description)


def canonicalize_hook(value: str, title: str) -> str:
    text = normalize_label(f"{value} {title}").lower()
    for pattern, label in HOOK_RULES:
        if re.search(pattern, text):
            return label
    return infer_hook(title)


def canonicalize_title_pattern(value: str, title: str, format_type: str) -> str:
    label = normalize_label(value)
    if not label or "[" in label or len(label) > 44:
        return infer_title_pattern(title, format_type)
    return label


def detect_labels(text: str, rules: list[tuple[str, list[str]]], *, limit: int) -> list[str]:
    found: list[str] = []
    lowered = text.lower()
    for label, patterns in rules:
        if any(re.search(pattern, lowered) for pattern in patterns):
            found.append(label)
    return found[:limit]


def canonicalize_tools(values: list[str], fallback_text: str) -> list[str]:
    joined = " ".join([fallback_text, *[str(value) for value in values]])
    detected = detect_labels(joined, CANONICAL_TOOL_RULES, limit=6)
    if detected:
        return detected
    inferred = infer_tools(joined)
    if inferred:
        return inferred[:6]
    return []


def canonicalize_topic_tags(values: list[str], fallback_text: str) -> list[str]:
    joined = " ".join([fallback_text, *[str(value) for value in values]])
    detected = detect_labels(joined, CANONICAL_TAG_RULES, limit=6)
    if detected:
        return detected
    cleaned = [normalize_label(value) for value in values if normalize_label(value)]
    return unique_keywords(cleaned)[:6] or infer_topic_tags(joined)[:6]


def clean_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return text


def merge_analysis(video: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    fallback = fallback_analysis(video)
    raw_keywords = parsed.get("keywords") or fallback["keywords"]
    raw_tools = parsed.get("tools") or fallback["tools"]
    raw_tags = parsed.get("topic_tags") or fallback["topic_tags"]
    fallback_text = " ".join(
        [
            video.get("title", ""),
            video.get("description", ""),
            " ".join(str(item) for item in raw_keywords),
            " ".join(str(item) for item in raw_tools),
            " ".join(str(item) for item in raw_tags),
        ]
    )
    format_type = canonicalize_format(parsed.get("format") or fallback["format"], video.get("title", ""), video.get("description", ""))
    hook_type = canonicalize_hook(parsed.get("hook_type") or fallback["hook_type"], video.get("title", ""))
    return {
        "format": format_type,
        "hook_type": hook_type,
        "title_pattern": canonicalize_title_pattern(normalize_text_field(parsed.get("title_pattern")) or fallback["title_pattern"], video.get("title", ""), format_type),
        "topic_tags": canonicalize_topic_tags([*raw_tags, *raw_keywords], fallback_text),
        "keywords": unique_keywords([*raw_keywords, *raw_tags])[:8] or fallback["keywords"],
        "tools": canonicalize_tools(raw_tools, fallback_text),
        "one_line_summary": normalize_text_field(parsed.get("one_line_summary"), fallback=fallback["one_line_summary"]),
        "why_it_works": normalize_text_field(parsed.get("why_it_works"), fallback=fallback["why_it_works"]),
        "recommendation": normalize_text_field(parsed.get("recommendation"), fallback=fallback["recommendation"]),
        "flow": normalize_text_list(parsed.get("flow"), limit=5) or fallback["flow"],
        "claims": normalize_text_list(parsed.get("claims"), limit=5) or fallback["claims"],
        "transcript_highlights": safe_transcript_highlights(video, parsed.get("transcript_highlights") or fallback["transcript_highlights"])
    }


def ensure_korean_output(video: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    fallback = fallback_analysis(video)
    localized = dict(analysis)

    if needs_korean_localization(localized):
        translated = translate_analysis_fields_with_gemini(localized)
        localized.update({key: value for key, value in translated.items() if value})

    for field in KOREAN_TEXT_FIELDS:
        value = normalize_text_field(localized.get(field))
        localized[field] = value if value and has_hangul(value) else fallback[field]

    for field in KOREAN_LIST_FIELDS:
        values = normalize_text_list(localized.get(field), limit=5)
        localized[field] = values if values and any(has_hangul(item) for item in values) else fallback[field]

    return localized


def openai_analysis(video: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return fallback_analysis(video)

    prompt = build_prompt(video)
    payload = {
        "model": os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    }

    try:
        response = request_json(
            OPENAI_ENDPOINT,
            method="POST",
            headers={"Authorization": f"Bearer {api_key}"},
            payload=payload,
            timeout=90
        )
        content = clean_json_text(response["choices"][0]["message"]["content"])
        parsed = json.loads(content)
        return merge_analysis(video, parsed)
    except Exception:
        return fallback_analysis(video)


def gemini_analysis(video: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return fallback_analysis(video)

    prompt = build_prompt(video)
    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "generationConfig": {"responseMimeType": "application/json"},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": json.dumps(prompt, ensure_ascii=False)}],
            }
        ],
    }

    try:
        response = request_json(
            GEMINI_ENDPOINT_TEMPLATE.format(model=model),
            method="POST",
            params={"key": api_key},
            payload=payload,
            timeout=90
        )
        content = clean_json_text(response["candidates"][0]["content"]["parts"][0]["text"])
        parsed = json.loads(content)
        return merge_analysis(video, parsed)
    except Exception:
        return fallback_analysis(video)


def analyze_video(video: dict[str, Any]) -> dict[str, Any]:
    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if provider == "gemini":
        return ensure_korean_output(video, gemini_analysis(video))
    if provider == "openai":
        return ensure_korean_output(video, openai_analysis(video))
    if os.getenv("GEMINI_API_KEY"):
        return ensure_korean_output(video, gemini_analysis(video))
    if os.getenv("OPENAI_API_KEY"):
        return ensure_korean_output(video, openai_analysis(video))
    return ensure_korean_output(video, fallback_analysis(video))


def enrich_videos_with_analysis(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for video in videos:
        analysis = analyze_video(video)
        thumbnail_url = video.get("thumbnail_url", "")
        thumbnail_analysis = analyze_thumbnail(thumbnail_url) if thumbnail_url else {}
        enriched.append({**video, **analysis, "thumbnail_analysis": thumbnail_analysis})
    return enriched
