from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tkinter import Tk, messagebox


ROOT_DIR = Path(__file__).resolve().parent
PIPELINE_SCRIPT = ROOT_DIR / "scripts" / "run_pipeline.py"


def show_message(title: str, message: str, *, error: bool = False) -> None:
    root = Tk()
    root.withdraw()
    if error:
        messagebox.showerror(title, message)
    else:
        messagebox.showinfo(title, message)
    root.destroy()


def run_step(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PIPELINE_SCRIPT), *args],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def main() -> int:
    if not PIPELINE_SCRIPT.exists():
        show_message("업데이트 실행 실패", "scripts/run_pipeline.py 파일을 찾을 수 없습니다.", error=True)
        return 1

    subprocess.run(
        ["git", "-C", str(ROOT_DIR), "pull", "--ff-only"],
        capture_output=True,
        text=True,
    )

    pipeline = run_step([])
    if pipeline.returncode != 0:
        show_message(
            "업데이트 실행 실패",
            f"파이프라인 실행 중 오류가 발생했습니다.\n\n{pipeline.stderr or pipeline.stdout}",
            error=True,
        )
        return pipeline.returncode

    show_message(
        "업데이트 완료",
        "데이터 갱신이 완료되었습니다.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
