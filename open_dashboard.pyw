from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import Tk, messagebox


ROOT_DIR = Path(__file__).resolve().parent
SERVER_SCRIPT = ROOT_DIR / "scripts" / "serve_dashboard.py"
SERVER_URL = "http://127.0.0.1:8000"
HEALTH_URL = f"{SERVER_URL}/api/health"


def show_error(message: str) -> None:
    root = Tk()
    root.withdraw()
    messagebox.showerror("대시보드 실행 실패", message)
    root.destroy()


def server_is_ready() -> bool:
    request = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
            return bool(payload.get("ok"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return False


def main() -> int:
    if not SERVER_SCRIPT.exists():
        show_error("scripts/serve_dashboard.py 파일을 찾을 수 없습니다.")
        return 1

    try:
        if not server_is_ready():
            subprocess.Popen(
                [sys.executable, str(SERVER_SCRIPT)],
                cwd=str(ROOT_DIR),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )

            deadline = time.time() + 15
            while time.time() < deadline:
                if server_is_ready():
                    break
                time.sleep(0.5)

            if not server_is_ready():
                show_error("대시보드 서버를 시작했지만 응답을 받지 못했습니다.")
                return 1

        webbrowser.open(SERVER_URL)
        return 0
    except Exception as exc:
        show_error(f"대시보드를 실행하지 못했습니다.\n\n{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
