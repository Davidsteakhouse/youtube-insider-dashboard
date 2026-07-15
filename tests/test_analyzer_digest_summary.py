from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import analyzer  # noqa: E402


class AnalyzerDigestSummaryTests(unittest.TestCase):
    def test_generates_korean_summaries_in_one_batch(self) -> None:
        videos = [
            {
                "video_id": "video-1",
                "title": "Build an AI influencer",
                "description": "Create a consistent character and voice.",
                "transcript_highlights": ["Choose an identity, voice, and consistent visual style."],
            },
            {
                "video_id": "video-2",
                "title": "Claude automation",
                "description": "Automate document routing.",
                "transcript_highlights": ["Claude classifies documents and routes them to the right team."],
            },
        ]
        response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "not-json reasoning"},
                            {
                                "text": json.dumps(
                                    {
                                        "summaries": [
                                            {
                                                "video_id": "video-1",
                                                "summary": "캐릭터의 정체성과 목소리를 먼저 설계한 뒤 장면마다 같은 외형을 유지하는 AI 인플루언서를 만듭니다.",
                                            },
                                            {
                                                "video_id": "video-2",
                                                "summary": "Claude가 문서를 분류해 담당 팀으로 자동 전달하도록 만들고 수작업 흐름을 대체합니다.",
                                            },
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            },
                        ]
                    }
                }
            ]
        }

        with patch.dict(analyzer.os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False), patch.object(
            analyzer,
            "request_json",
            return_value=response,
        ) as request_mock:
            summaries = analyzer.generate_digest_summaries(videos)

        self.assertEqual(set(summaries), {"video-1", "video-2"})
        self.assertIn("AI 인플루언서", summaries["video-1"])
        self.assertIn("자동 전달", summaries["video-2"])
        self.assertEqual(request_mock.call_count, 1)

    def test_rejects_non_korean_or_unknown_video_summaries(self) -> None:
        response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "summaries": [
                                            {"video_id": "known", "summary": "This is only English and should be rejected."},
                                            {"video_id": "unknown", "summary": "존재하지 않는 영상의 요약은 제외합니다."},
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        ]
                    }
                }
            ]
        }
        with patch.dict(analyzer.os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False), patch.object(
            analyzer,
            "request_json",
            return_value=response,
        ):
            summaries = analyzer.generate_digest_summaries([{"video_id": "known", "title": "AI test"}])

        self.assertEqual(summaries, {})

    def test_rejects_korean_but_generic_summary(self) -> None:
        response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "summaries": [
                                            {
                                                "video_id": "known",
                                                "summary": "이 영상은 AI 관련 내용을 다룹니다. 실제 활용 맥락을 함께 보여줍니다.",
                                            }
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        ]
                    }
                }
            ]
        }
        with patch.dict(analyzer.os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False), patch.object(
            analyzer,
            "request_json",
            return_value=response,
        ):
            summaries = analyzer.generate_digest_summaries([{"video_id": "known", "title": "AI test"}])

        self.assertEqual(summaries, {})


if __name__ == "__main__":
    unittest.main()
