from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import outlier_radar as radar  # noqa: E402


NOW = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
THRESHOLDS = {
    "multiplier_min": 5,
    "sub_ratio_min": 3,
    "views_min": {"en": 30000, "ko": 10000},
    "views_min_hours": 24,
    "growth_min_gap_hours": 3,
    "fit_min": 3,
}
GAP_CFG = {"lookback_days": 14, "green_longform_max": 2, "green_top_views_max": 10000, "red_longform_min": 6, "red_top_views_min": 100000}


def video(views: int, *, days_ago: float, duration: int = 600, title: str = "Somebody vibe coded every Adobe app") -> dict:
    return {
        "video_id": f"v{views}_{days_ago}",
        "title": title,
        "description": "",
        "channel_id": "UC1",
        "channel_title": "FUTC",
        "published_at": radar.iso(NOW - timedelta(days=days_ago)),
        "views": views,
        "duration_s": duration,
        "live": "none",
    }


class BaselineTests(unittest.TestCase):
    def test_median_ignores_recent_shorts_and_live(self) -> None:
        videos = [video(1000 * i, days_ago=10 + i) for i in range(1, 6)]
        videos += [video(9_000_000, days_ago=1), video(500_000, days_ago=20, duration=40)]
        videos.append({**video(800_000, days_ago=30), "live": "upcoming"})
        baseline, sample = radar.compute_baseline(videos, NOW, min_age_days=7, sample_size=15)
        self.assertEqual(sample, 5)
        self.assertEqual(baseline, 3000)

    def test_falls_back_to_two_days_then_none(self) -> None:
        videos = [video(100, days_ago=3), video(200, days_ago=4), video(300, days_ago=5)]
        self.assertEqual(radar.compute_baseline(videos, NOW, min_age_days=7, sample_size=15), (200.0, 3))
        self.assertEqual(radar.compute_baseline(videos[:2], NOW, min_age_days=7, sample_size=15), (None, 0))


class ScoreTests(unittest.TestCase):
    def test_small_channel_breakout_passes(self) -> None:
        # 노아 모리스 예시: 구독자 500명 채널에서 18만 회
        result = radar.score_video(video(180_000, days_ago=2), {"baseline": 2_000, "subs": 500}, NOW, THRESHOLDS)
        self.assertEqual(result["multiplier"], 90)
        self.assertEqual(result["sub_ratio"], 360)
        self.assertTrue(result["passes"])

    def test_big_channel_normal_video_fails(self) -> None:
        result = radar.score_video(video(345_000, days_ago=1), {"baseline": 300_000, "subs": 2_840_000}, NOW, THRESHOLDS)
        self.assertFalse(result["is_outlier"])
        self.assertFalse(result["passes"])

    def test_outlier_needs_minimum_views(self) -> None:
        result = radar.score_video(video(3_000, days_ago=3), {"baseline": 300, "subs": 900}, NOW, THRESHOLDS)
        self.assertTrue(result["is_outlier"])
        self.assertFalse(result["is_big"])
        self.assertFalse(result["passes"])

    def test_older_outlier_is_not_penalized_after_24_hours(self) -> None:
        # 시간당 평균으로는 떨어지던 67시간 된 영상(시간당 약 960회)도 3만 회를 넘으면 통과
        result = radar.score_video(video(64_574, days_ago=67 / 24), {"baseline": 4_348, "subs": 600_000}, NOW, THRESHOLDS)
        self.assertTrue(result["passes"])

    def test_korean_floor_is_ten_thousand_per_day(self) -> None:
        title = "AI가 어도비를 죽였다"
        self.assertTrue(radar.score_video(video(12_000, days_ago=1, title=title), {"baseline": 1_500, "subs": 30_000}, NOW, THRESHOLDS)["passes"])
        self.assertFalse(radar.score_video(video(9_000, days_ago=2, title=title), {"baseline": 1_000, "subs": 30_000}, NOW, THRESHOLDS)["passes"])

    def test_floor_is_prorated_before_24_hours(self) -> None:
        title = "AI가 어도비를 죽였다"
        self.assertEqual(radar.required_views(12, "ko", THRESHOLDS), 5_000)
        self.assertEqual(radar.required_views(48, "ko", THRESHOLDS), 10_000)
        young = video(6_000, days_ago=0.5, title=title)
        self.assertTrue(radar.score_video(young, {"baseline": 500, "subs": 30_000}, NOW, THRESHOLDS)["passes"])


class GrowthTests(unittest.TestCase):
    def test_uses_latest_record_at_least_three_hours_old(self) -> None:
        points = [
            [radar.iso(NOW - timedelta(hours=12)), 40_000],
            [radar.iso(NOW - timedelta(hours=6)), 70_000],
            [radar.iso(NOW - timedelta(hours=1)), 99_000],
        ]
        growth = radar.recent_growth(points, 100_000, NOW, 3)
        self.assertEqual(growth, {"hours": 6.0, "gained": 30_000, "per_hour": 5_000})

    def test_first_sighting_has_no_growth(self) -> None:
        self.assertIsNone(radar.recent_growth([], 100_000, NOW, 3))
        self.assertIsNone(radar.recent_growth([[radar.iso(NOW - timedelta(hours=1)), 90_000]], 100_000, NOW, 3))

    def test_trend_labels(self) -> None:
        self.assertEqual(radar.growth_trend(3_000, 2_000), "가속")
        self.assertEqual(radar.growth_trend(1_000, 2_000), "유지")
        self.assertEqual(radar.growth_trend(500, 2_000), "둔화")

    def test_growth_feeds_score_and_text(self) -> None:
        growth = {"hours": 6.0, "gained": 30_000, "per_hour": 5_000}
        result = radar.score_video(video(100_000, days_ago=1), {"baseline": 10_000, "subs": 50_000}, NOW, THRESHOLDS, growth)
        self.assertEqual(result["trend"], "가속")
        self.assertEqual(radar.growth_text(result), "최근 6시간 +3만회 (시간당 5,000 · 가속)")


class GapTests(unittest.TestCase):
    def test_verdicts(self) -> None:
        self.assertEqual(radar.classify_gap(0, 0, GAP_CFG), "green")
        self.assertEqual(radar.classify_gap(2, 9_999, GAP_CFG), "green")
        self.assertEqual(radar.classify_gap(3, 5_000, GAP_CFG), "yellow")
        self.assertEqual(radar.classify_gap(1, 20_000, GAP_CFG), "yellow")
        self.assertEqual(radar.classify_gap(6, 1_000, GAP_CFG), "red")
        self.assertEqual(radar.classify_gap(1, 150_000, GAP_CFG), "red")


class FormatTests(unittest.TestCase):
    def test_compact_ko(self) -> None:
        self.assertEqual(radar.compact_ko(9_999), "9,999")
        self.assertEqual(radar.compact_ko(1_950_000), "195만")
        self.assertEqual(radar.compact_ko(12_345), "1.2만")
        self.assertEqual(radar.compact_ko(None), "비공개")

    def test_quota_day_follows_pacific_midnight(self) -> None:
        # 유튜브 한도는 태평양 자정(한국 오후 4~5시)에 초기화된다
        self.assertEqual(radar.quota_day(datetime(2026, 10, 22, 7, 59, tzinfo=timezone.utc)), "2026-10-21")
        self.assertEqual(radar.quota_day(datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)), "2026-10-22")

    def test_duration(self) -> None:
        self.assertEqual(radar.parse_duration_seconds("PT20M21S"), 1221)
        self.assertEqual(radar.parse_duration_seconds("PT1H"), 3600)
        self.assertEqual(radar.parse_duration_seconds("P0D"), 0)

    def test_alert_has_core_lines(self) -> None:
        candidate = radar.score_video(video(1_950_000, days_ago=1), {"baseline": 40_000, "subs": 300_000}, NOW, THRESHOLDS)
        candidate.update(
            topic_ko="AI가 만든 어도비 대체앱",
            ko_query="어도비 대체 앱",
            fit=5,
            format="AI 대체 실험",
            why="사건 포장형",
            title_ko="오늘, AI가 어도비를 죽였습니다",
            korea={"verdict": "green", "query": "어도비 대체 앱", "longform": 0, "shorts": 2, "top_views": 1293},
            signals=["GitHub brandon/photocraft ★2.4만 (+1.1만/일)"],
        )
        text = radar.build_alert(candidate, GAP_CFG, 5)
        self.assertIn("🚨 선점 기회 | AI가 만든 어도비 대체앱", text)
        self.assertIn("평소 대비 49배", text)
        self.assertIn("시간당 평균 8.1만회 (첫 관측)", text)
        self.assertIn("🟢 공백", text)
        self.assertIn("마감: 10/26(월)까지", text)
        self.assertIn("https://youtu.be/", text)


class ClusterTests(unittest.TestCase):
    def test_same_topic_becomes_one_alert_with_merged_signals(self) -> None:
        first = {"video_id": "a", "cluster": "claude-tv-adblock", "ko_query": "AI 안드로이드 TV 광고", "signals": ["GitHub x/free-my-tv ★2,916 (+1,157/일)"]}
        second = {"video_id": "b", "cluster": "claude-tv-adblock", "ko_query": "AI 스마트 TV 최적화", "signals": []}
        third = {"video_id": "c", "cluster": "adobe-clones", "ko_query": "어도비 대체 앱", "signals": []}
        leaders = radar.group_by_cluster([first, second, third])
        self.assertEqual([leader["video_id"] for leader in leaders], ["a", "c"])
        self.assertEqual([item["video_id"] for item in leaders[0]["cluster_items"]], ["b"])
        self.assertEqual(
            radar.dedupe_keys(leaders[0]),
            ["ai안드로이드tv광고", "cluster:claude-tv-adblock", "signal:github x/free-my-tv"],
        )


class GeminiRetryTests(unittest.TestCase):
    def test_retries_overload_then_falls_back(self) -> None:
        ok = {"candidates": [{"content": {"parts": [{"text": "[{\"id\": \"a\"}]"}]}}]}
        calls = []

        def fake_http(url, **kwargs):
            calls.append(url.rsplit("/", 1)[-1])
            if len(calls) <= 3:
                raise RuntimeError("HTTP 503 overloaded")
            return ok

        with patch.dict(radar.os.environ, {"GEMINI_API_KEY": "k", "GEMINI_MODEL": "lite"}), patch.object(
            radar, "http_json", side_effect=fake_http
        ), patch.object(radar.time, "sleep"):
            self.assertEqual(radar.gemini_json("p", []), [{"id": "a"}])
        self.assertEqual(calls, ["lite:generateContent"] * 3 + [f"{radar.GEMINI_FALLBACK_MODEL}:generateContent"])

    def test_does_not_retry_bad_request(self) -> None:
        with patch.dict(radar.os.environ, {"GEMINI_API_KEY": "k", "GEMINI_MODEL": "lite"}), patch.object(
            radar, "http_json", side_effect=RuntimeError("HTTP 400 bad")
        ) as http_mock, patch.object(radar.time, "sleep"):
            self.assertIsNone(radar.gemini_json("p", []))
        self.assertEqual(http_mock.call_count, 2)  # 모델당 한 번씩만


class RotationTests(unittest.TestCase):
    def test_cycles_through_fixed_and_persona_queries(self) -> None:
        config = {"queries": [{"q": "a"}, {"q": "b"}, {"q": "c"}]}
        state = {"persona": {"queries": [{"q": "d"}]}}
        self.assertEqual([q["q"] for q in radar.next_queries(config, state, 3)], ["a", "b", "c"])
        self.assertEqual([q["q"] for q in radar.next_queries(config, state, 3)], ["d", "a", "b"])


if __name__ == "__main__":
    unittest.main()
