from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from digest_builder import TELEGRAM_SAFE_MESSAGE_LIMIT, build_digest  # noqa: E402


def channel(key: str, name: str, category: str) -> dict:
    return {
        "channel_key": key,
        "youtube_channel_id": f"UC{key:0<22}"[:24],
        "name": name,
        "url": f"https://youtube.com/@{key}",
        "category": category,
        "is_active": True,
    }


def video(
    video_id: str,
    channel_key: str,
    channel_name: str,
    *,
    title: str,
    views: int,
    summary: str = "이 영상은 실제 AI 도구를 사용해 업무 자동화를 만들고 결과를 비교합니다.",
    highlights: list[str] | None = None,
) -> dict:
    return {
        "video_id": video_id,
        "channel_key": channel_key,
        "channel_name": channel_name,
        "title": title,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "view_count": views,
        "like_count": max(views // 20, 1),
        "comment_count": 3,
        "engagement_rate": 0.05,
        "video_url": f"https://youtube.com/watch?v={video_id}",
        "one_line_summary": summary,
        "transcript_highlights": highlights or [],
        "topic_tags": [],
        "keywords": [],
        "tools": [],
        "format": "워크플로우 튜토리얼",
    }


class DigestBuilderAiScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.watchlist = [
            channel("ai-core", "AI Core", "AI"),
            channel("tech", "일반 테크", "테크"),
            channel("business", "비즈니스 AI", "비즈니스/AI"),
        ]

    def test_ai_core_stays_ahead_of_higher_view_adjacent_channels(self) -> None:
        ai_videos = [
            video(
                f"ai-{index}",
                "ai-core",
                "AI Core",
                title=f"ChatGPT 자동화 실험 {index}",
                views=1_000 + index,
            )
            for index in range(12)
        ]
        excluded = [
            video("tech-million", "tech", "일반 테크", title="ChatGPT 신기능", views=1_000_000),
            video("business-million", "business", "비즈니스 AI", title="AI 사업 전략", views=900_000),
            video("non-ai", "ai-core", "AI Core", title="아침 루틴 공개", views=800_000),
        ]

        digest = build_digest([*ai_videos, *excluded], self.watchlist)

        self.assertEqual(digest["focus_scope"], "ai_priority_then_tech_fill")
        self.assertEqual(digest["video_count"], 14)
        self.assertEqual(len(digest["telegram_video_ids"]), 10)
        self.assertEqual(digest["telegram_video_ids"][0], "ai-11")
        self.assertNotIn("tech-million", digest["telegram_video_ids"])
        self.assertNotIn("business-million", digest["telegram_video_ids"])
        self.assertNotIn("non-ai", digest["telegram_video_ids"])
        self.assertIn("AI 우선 콘텐츠 TOP 10", digest["telegram_preview"])
        self.assertNotIn("테크 보충 · [일반 테크]", digest["telegram_preview"])

    def test_fills_only_remaining_slots_with_general_tech(self) -> None:
        ai_core = [
            video(
                f"ai-{index}",
                "ai-core",
                "AI Core",
                title=f"ChatGPT 자동화 실험 {index}",
                views=100 + index,
            )
            for index in range(5)
        ]
        adjacent_ai = video(
            "adjacent-ai",
            "tech",
            "일반 테크",
            title="Claude와 GPT 개발 비용 비교",
            views=50_000,
        )
        tech_fillers = [
            video(
                f"tech-{index}",
                "tech",
                "일반 테크",
                title=f"스마트폰 실사용 리뷰 {index}",
                views=1_000_000 - index,
            )
            for index in range(4)
        ]
        non_ai_business = video(
            "business-sales",
            "business",
            "비즈니스 AI",
            title="매출을 올리는 영업 대화법",
            views=2_000_000,
        )

        digest = build_digest(
            [*ai_core, adjacent_ai, *tech_fillers, non_ai_business],
            self.watchlist,
        )

        ids = digest["telegram_video_ids"]
        self.assertEqual(len(ids), 10)
        self.assertEqual(ids[:5], [f"ai-{index}" for index in range(4, -1, -1)])
        self.assertEqual(ids[5], "adjacent-ai")
        self.assertEqual(ids[6:], [f"tech-{index}" for index in range(4)])
        self.assertNotIn("business-sales", ids)
        self.assertEqual(digest["video_count"], 6)
        self.assertEqual(digest["telegram_candidate_count"], 10)
        self.assertEqual(digest["average_view_count"], 8418)
        self.assertIn(
            "총 10개 | AI 핵심 5 · 인접 AI 1 · 일반 테크 보충 4",
            digest["telegram_preview"],
        )
        self.assertIn("AI 인접 · [일반 테크]", digest["telegram_preview"])
        self.assertIn("테크 보충 · [일반 테크]", digest["telegram_preview"])

    def test_nine_ai_candidates_use_only_one_general_tech_slot(self) -> None:
        ai_videos = [
            video(
                f"ai-{index}",
                "ai-core",
                "AI Core",
                title=f"Claude 자동화 실험 {index}",
                views=100 + index,
            )
            for index in range(9)
        ]
        tech_videos = [
            video(
                f"tech-{index}",
                "tech",
                "일반 테크",
                title=f"스마트폰 카메라 비교 {index}",
                views=1_000_000 - index,
            )
            for index in range(2)
        ]

        ids = build_digest([*ai_videos, *tech_videos], self.watchlist)["telegram_video_ids"]

        self.assertEqual(len(ids), 10)
        self.assertEqual(ids[:9], [f"ai-{index}" for index in range(8, -1, -1)])
        self.assertEqual(ids[9], "tech-0")
        self.assertNotIn("tech-1", ids)

    def test_broad_workflow_word_does_not_promote_tech_video_to_ai_adjacent(self) -> None:
        ai_video = video(
            "ai",
            "ai-core",
            "AI Core",
            title="ChatGPT 문서 자동화",
            views=10,
        )
        camera_workflow = video(
            "camera-workflow",
            "tech",
            "일반 테크",
            title="카메라 workflow 촬영법",
            views=1_000_000,
        )

        digest = build_digest([camera_workflow, ai_video], self.watchlist)

        self.assertEqual(digest["telegram_video_ids"], ["ai", "camera-workflow"])
        self.assertIn("테크 보충 · [일반 테크]", digest["telegram_preview"])

    def test_missing_ai_summaries_backfill_from_general_tech(self) -> None:
        generic = "이 영상은 automation 이슈를 워크플로우 튜토리얼 포맷으로 압축해, 지금 왜 봐야 하는지와 실제 활용 맥락을 함께 보여줍니다."
        ai_videos = [
            video(
                f"valid-ai-{index}",
                "ai-core",
                "AI Core",
                title=f"Gemini 리서치 실험 {index}",
                views=1_000 - index,
                summary=f"Gemini 리서치 실험 {index}에서 출처 정확도와 처리 시간을 비교해 실제 결과를 정리합니다.",
            )
            for index in range(8)
        ]
        missing_ai = [
            video(
                f"missing-ai-{index}",
                "ai-core",
                "AI Core",
                title=f"ChatGPT 요약 실패 {index}",
                views=10_000 - index,
                summary=generic,
                highlights=["English only highlight."],
            )
            for index in range(2)
        ]
        tech_videos = [
            video(
                f"tech-{index}",
                "tech",
                "일반 테크",
                title=f"노트북 실사용 비교 {index}",
                views=500 - index,
                summary=f"노트북 실사용 비교 {index}에서 배터리와 성능을 측정해 구매 전에 확인할 차이를 정리합니다.",
            )
            for index in range(3)
        ]

        ids = build_digest([*ai_videos, *missing_ai, *tech_videos], self.watchlist)["telegram_video_ids"]

        self.assertEqual(len(ids), 10)
        self.assertNotIn("missing-ai-0", ids)
        self.assertNotIn("missing-ai-1", ids)
        self.assertEqual(ids[-2:], ["tech-0", "tech-1"])

    def test_fewer_than_ten_uses_actual_count_and_real_summary(self) -> None:
        videos = [
            video(
                "one",
                "ai-core",
                "AI Core",
                title="Claude 자동화 만들기",
                views=200,
                summary="Claude에 문서 분류 규칙을 넣어 반복 업무를 자동 처리하고 수작업 결과와 정확도를 비교합니다.",
            ),
            video(
                "two",
                "ai-core",
                "AI Core",
                title="Gemini 리서치 대결",
                views=100,
                summary="Gemini의 리서치 결과를 ChatGPT와 같은 질문으로 대결시켜 출처 정확도와 속도 차이를 확인합니다.",
            ),
        ]

        preview = build_digest(videos, self.watchlist)["telegram_preview"]

        self.assertIn("TOP 2 (최대 10)", preview)
        self.assertIn("반복 업무를 자동 처리", preview)
        self.assertIn("출처 정확도와 속도 차이", preview)

    def test_zero_ai_content_falls_back_to_general_tech(self) -> None:
        videos = [
            video("tech", "tech", "일반 테크", title="노트북 배터리 실사용 리뷰", views=999_999),
            video("lifestyle", "ai-core", "AI Core", title="아침 루틴 공개", views=500_000),
        ]

        digest = build_digest(videos, self.watchlist)

        self.assertEqual(digest["video_count"], 0)
        self.assertEqual(digest["telegram_video_ids"], ["tech"])
        self.assertIn(
            "총 1개 | AI 핵심 0 · 인접 AI 0 · 일반 테크 보충 1",
            digest["telegram_preview"],
        )
        self.assertIn("노트북 배터리 실사용 리뷰", digest["telegram_preview"])

    def test_generic_summary_uses_korean_transcript_highlight(self) -> None:
        generic = "이 영상은 automation 이슈를 워크플로우 튜토리얼 포맷으로 압축해, 지금 왜 봐야 하는지와 실제 활용 맥락을 함께 보여줍니다."
        videos = [
            video(
                "highlight",
                "ai-core",
                "AI Core",
                title="AI 인플루언서 만들기",
                views=100,
                summary=generic,
                highlights=["10분 안에 캐릭터 정체성과 목소리를 정한 뒤 장면마다 같은 외형을 유지하는 AI 인플루언서를 만듭니다."],
            )
        ]

        preview = build_digest(videos, self.watchlist)["telegram_preview"]

        self.assertIn("장면마다 같은 외형을 유지", preview)
        self.assertNotIn("포맷으로 압축해", preview)

    def test_ai_content_can_be_detected_from_korean_suffix_tool_or_description(self) -> None:
        ai_suffix = video(
            "suffix",
            "ai-core",
            "AI Core",
            title="AI로 하루 만에 앱 만들기",
            views=300,
        )
        midjourney = video(
            "midjourney",
            "ai-core",
            "AI Core",
            title="Midjourney V7 캐릭터 일관성 실험",
            views=200,
        )
        description_only = video(
            "description",
            "ai-core",
            "AI Core",
            title="업무 시간을 절반으로 줄였습니다",
            views=100,
        )
        description_only["description"] = "Claude 에이전트가 문서를 읽고 담당 팀으로 자동 전달하도록 구성한 실험입니다."
        openai = video(
            "openai",
            "ai-core",
            "AI Core",
            title="OpenAI developer update",
            views=50,
        )

        digest = build_digest([ai_suffix, midjourney, description_only, openai], self.watchlist)

        self.assertEqual(digest["video_count"], 4)
        self.assertEqual(
            set(digest["telegram_video_ids"]),
            {"suffix", "midjourney", "description", "openai"},
        )

    def test_missing_real_summary_is_excluded_instead_of_invented(self) -> None:
        generic = "이 영상은 automation 이슈를 워크플로우 튜토리얼 포맷으로 압축해, 지금 왜 봐야 하는지와 실제 활용 맥락을 함께 보여줍니다."
        videos = [
            video(
                "missing",
                "ai-core",
                "AI Core",
                title="AI workflow test",
                views=100,
                summary=generic,
                highlights=["Build a workflow and connect it to the publishing system."],
            )
        ]

        preview = build_digest(videos, self.watchlist)["telegram_preview"]

        self.assertIn("실제 내용 요약을 만들지 못했습니다", preview)
        self.assertIn("제목만 보내지 않고", preview)
        self.assertNotIn("AI 활용 과정과 핵심 결과", preview)

    def test_english_summary_is_not_exposed_as_korean_content_summary(self) -> None:
        videos = [
            video(
                "english",
                "ai-core",
                "AI Core",
                title="Claude vs ChatGPT",
                views=100,
                summary="This compares Claude and ChatGPT on research speed and source accuracy.",
                highlights=["The test compares research speed and source accuracy."],
            )
        ]

        preview = build_digest(videos, self.watchlist)["telegram_preview"]

        self.assertIn("실제 내용 요약을 만들지 못했습니다", preview)
        self.assertNotIn("This compares Claude", preview)

    def test_missing_top_summaries_are_backfilled_by_lower_ranked_valid_items(self) -> None:
        generic = "이 영상은 automation 이슈를 워크플로우 튜토리얼 포맷으로 압축해, 지금 왜 봐야 하는지와 실제 활용 맥락을 함께 보여줍니다."
        videos = [
            video(
                f"valid-{index}",
                "ai-core",
                "AI Core",
                title=f"ChatGPT 자동화 실험 {index}",
                views=1_000 - index,
                summary=f"ChatGPT 자동화 실험 {index}에서 문서 분류와 전달 과정을 연결하고 처리 시간을 직접 비교합니다.",
            )
            for index in range(10)
        ]
        videos.extend(
            [
                video(
                    "missing-1",
                    "ai-core",
                    "AI Core",
                    title="AI summary missing one",
                    views=10_000,
                    summary=generic,
                    highlights=["English only highlight."],
                ),
                video(
                    "missing-2",
                    "ai-core",
                    "AI Core",
                    title="AI summary missing two",
                    views=9_000,
                    summary=generic,
                    highlights=["English only highlight."],
                ),
            ]
        )

        digest = build_digest(videos, self.watchlist)

        self.assertEqual(len(digest["telegram_video_ids"]), 10)
        self.assertNotIn("missing-1", digest["telegram_video_ids"])
        self.assertNotIn("missing-2", digest["telegram_video_ids"])
        self.assertIn("AI 우선 콘텐츠 TOP 10", digest["telegram_preview"])

    def test_ten_long_items_stay_inside_telegram_limit(self) -> None:
        long_summary = "ChatGPT와 Claude에 같은 자료를 넣고 조사 과정, 출처 정확도, 작업 시간을 차례로 비교한 뒤 실제 업무에서는 Claude가 더 안정적이라는 결론을 냅니다. " * 8
        videos = [
            video(
                f"long-{index}",
                "ai-core",
                "AI Core",
                title=f"ChatGPT와 Claude 실전 비교 {index} " + "아주 긴 제목 " * 10,
                views=10_000 - index,
                summary=long_summary,
            )
            for index in range(10)
        ]

        preview = build_digest(videos, self.watchlist)["telegram_preview"]

        self.assertLessEqual(len(preview), TELEGRAM_SAFE_MESSAGE_LIMIT)
        self.assertIn("TOP 10", preview)


if __name__ == "__main__":
    unittest.main()
