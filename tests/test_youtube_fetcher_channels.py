from __future__ import annotations

import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import youtube_fetcher  # noqa: E402


class YoutubeChannelResolutionTests(unittest.TestCase):
    def test_handle_is_canonical_even_when_saved_id_is_wrong(self) -> None:
        watchlist = [
            {
                "name": "Jeff Su",
                "url": "https://youtube.com/@jeffsu",
                "youtube_channel_id": "UCWo4IA01TXzBeGJJKWHOG9g",
            }
        ]

        with patch.object(
            youtube_fetcher,
            "youtube_get",
            return_value={"items": [{"id": "UCwAnu01qlnVg1Ai2AbtTMaA"}]},
        ) as youtube_get_mock:
            resolved = youtube_fetcher.resolve_channel_ids(watchlist)

        self.assertEqual(resolved[0]["youtube_channel_id"], "UCwAnu01qlnVg1Ai2AbtTMaA")
        endpoint, params = youtube_get_mock.call_args.args
        self.assertEqual(endpoint, "channels")
        self.assertEqual(params["forHandle"], "jeffsu")

    def test_percent_encoded_korean_handle_is_decoded(self) -> None:
        encoded_url = "https://youtube.com/@%EB%8F%99%ED%85%8C%ED%81%AC"

        with patch.object(
            youtube_fetcher,
            "youtube_get",
            return_value={"items": [{"id": "UCAAAAAAAAAAAAAAAAAAAAAA"}]},
        ) as youtube_get_mock:
            youtube_fetcher.resolve_channel_ids(
                [{"name": "동테크", "url": encoded_url, "youtube_channel_id": ""}]
            )

        self.assertEqual(youtube_get_mock.call_args.args[1]["forHandle"], "동테크")

    def test_raw_korean_handle_is_supported(self) -> None:
        with patch.object(
            youtube_fetcher,
            "youtube_get",
            return_value={"items": [{"id": "UCAAAAAAAAAAAAAAAAAAAAAA"}]},
        ) as youtube_get_mock:
            youtube_fetcher.resolve_channel_ids(
                [{"name": "동테크", "url": "https://youtube.com/@동테크", "youtube_channel_id": ""}]
            )

        self.assertEqual(youtube_get_mock.call_args.args[1]["forHandle"], "동테크")

    def test_empty_exact_handle_result_keeps_existing_id_without_search(self) -> None:
        existing_id = "UCQNE2JmbasNYbjGAcuBiRRg"
        with patch.object(youtube_fetcher, "youtube_get", return_value={"items": []}) as youtube_get_mock:
            resolved = youtube_fetcher.resolve_channel_ids(
                [
                    {
                        "name": "조코딩",
                        "url": "https://youtube.com/@jocoding",
                        "youtube_channel_id": existing_id,
                    }
                ]
            )

        self.assertEqual(resolved[0]["youtube_channel_id"], existing_id)
        self.assertEqual(youtube_get_mock.call_count, 1)

    def test_direct_channel_url_does_not_call_handle_lookup(self) -> None:
        direct_id = "UCQNE2JmbasNYbjGAcuBiRRg"
        with patch.object(youtube_fetcher, "youtube_get") as youtube_get_mock:
            resolved = youtube_fetcher.resolve_channel_ids(
                [
                    {
                        "name": "조코딩",
                        "url": f"https://youtube.com/channel/{direct_id}",
                        "youtube_channel_id": "UCWRONGWRONGWRONGWRONG12",
                    }
                ]
            )

        self.assertEqual(resolved[0]["youtube_channel_id"], direct_id)
        youtube_get_mock.assert_not_called()

    def test_handle_lookup_failure_keeps_existing_id(self) -> None:
        existing_id = "UCQNE2JmbasNYbjGAcuBiRRg"
        output = StringIO()
        with patch.object(
            youtube_fetcher,
            "youtube_get",
            side_effect=RuntimeError("https://example.test?key=SECRET"),
        ), redirect_stdout(output):
            resolved = youtube_fetcher.resolve_channel_ids(
                [
                    {
                        "name": "조코딩",
                        "url": "https://youtube.com/@jocoding",
                        "youtube_channel_id": existing_id,
                    }
                ]
            )

        self.assertEqual(resolved[0]["youtube_channel_id"], existing_id)
        self.assertNotIn("SECRET", output.getvalue())


if __name__ == "__main__":
    unittest.main()
