from __future__ import annotations

import argparse
import json
import subprocess
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from build_static_bundle import write_bundle
from common import ROOT_DIR, load_env_file
from notion_importer import import_watchlist
from storage import (
    build_bootstrap_payload,
    build_channel_detail,
    export_snapshot_files,
    init_db,
    load_channels,
    search_dashboard,
    upsert_channels,
)


PIPELINE_PATH = Path(__file__).resolve().parent / "run_pipeline.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YouTube Insider v2 로컬 서버를 실행합니다.")
    parser.add_argument("--host", default="127.0.0.1", help="바인딩할 호스트 주소")
    parser.add_argument("--port", default=8000, type=int, help="바인딩할 포트")
    return parser.parse_args()


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _json_response(self, payload: dict, status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._json_response({"ok": True, "service": "youtube-insider-v2"})
            return

        if parsed.path == "/api/bootstrap":
            self._json_response(build_bootstrap_payload())
            return

        if parsed.path == "/api/search":
            query = parse_qs(parsed.query).get("q", [""])[0]
            self._json_response(search_dashboard(query))
            return

        if parsed.path.startswith("/api/channel/"):
            channel_key = parsed.path.rsplit("/", 1)[-1]
            payload = build_channel_detail(channel_key)
            if not payload:
                self._json_response({"error": "channel_not_found"}, status=404)
                return
            self._json_response(payload)
            return

        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        body = self._read_json_body()

        if parsed.path == "/api/pipeline/run":
            command = [sys.executable, str(PIPELINE_PATH)]
            if body.get("notion_url"):
                command.extend(["--notion-url", body["notion_url"]])
            if body.get("notify_telegram"):
                command.append("--notify-telegram")
            process = subprocess.run(
                command,
                cwd=str(ROOT_DIR),
                capture_output=True,
                text=True,
                check=False,
            )
            payload = {
                "ok": process.returncode == 0,
                "returncode": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr,
                "bootstrap": build_bootstrap_payload() if process.returncode == 0 else None,
            }
            self._json_response(payload, status=200 if process.returncode == 0 else 500)
            return

        if parsed.path == "/api/watchlist/import-notion":
            notion_url = body.get("notion_url")
            import_file = body.get("import_file")
            try:
                channels, warnings = import_watchlist(notion_url=notion_url, import_file=import_file)
                persisted = upsert_channels(channels)
                export_snapshot_files()
                write_bundle()
                payload = {
                    "ok": True,
                    "warnings": warnings,
                    "channel_count": len(persisted),
                    "bootstrap": build_bootstrap_payload(),
                }
                self._json_response(payload)
            except Exception as error:
                existing = load_channels()
                if existing:
                    self._json_response(
                        {
                            "ok": True,
                            "warnings": [
                                f"Notion 다시 가져오기에 실패해 기존 워치리스트를 유지했습니다: {error}",
                            ],
                            "channel_count": len(existing),
                            "bootstrap": build_bootstrap_payload(),
                        }
                    )
                    return
                self._json_response({"ok": False, "error": str(error)}, status=500)
            return

        self._json_response({"error": "not_found"}, status=404)


def main() -> int:
    load_env_file()
    init_db()
    handler = partial(DashboardHandler, directory=str(ROOT_DIR))
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"대시보드 서버 실행: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("서버를 종료합니다.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
