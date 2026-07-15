from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
ENV_FILE = ROOT_DIR / ".env"
KST = timezone(timedelta(hours=9))
SENSITIVE_QUERY_KEYS = {
    "key",
    "api_key",
    "token",
    "access_token",
    "refresh_token",
    "client_secret",
}
SENSITIVE_ENV_NAMES = (
    "TELEGRAM_BOT_TOKEN",
    "YOUTUBE_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "APIFY_TOKEN",
    "NOTION_TOKEN_V2",
)


def redact_sensitive_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(str(url or ""))
    safe_path = re.sub(r"/bot[^/]+", "/bot***", parsed.path, flags=re.IGNORECASE)
    safe_query = urllib.parse.urlencode(
        [
            (key, "***" if key.lower() in SENSITIVE_QUERY_KEYS else value)
            for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, safe_path, safe_query, parsed.fragment))


def redact_sensitive_text(value: str) -> str:
    text = str(value or "")
    for env_name in SENSITIVE_ENV_NAMES:
        secret = os.getenv(env_name, "")
        if secret:
            text = text.replace(secret, "***")
    return text


def load_env_file(path: Path = ENV_FILE) -> None:
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


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def within_lookback_hours(value: str | datetime | None, *, lookback_hours: int = 24, now: datetime | None = None) -> bool:
    parsed = parse_datetime(value)
    if not parsed:
        return False
    reference = now or datetime.now(timezone.utc)
    age = reference.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)
    return age <= timedelta(hours=lookback_hours)


def kst_date_key(value: str | datetime | None = None) -> str:
    parsed = parse_datetime(value)
    target = parsed.astimezone(KST) if parsed else datetime.now(KST)
    return target.date().isoformat()


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


def chunks(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    bucket: list[Any] = []
    for item in items:
        bucket.append(item)
        if len(bucket) == size:
            yield bucket
            bucket = []
    if bucket:
        yield bucket


def safe_median(values: list[float]) -> float | None:
    filtered = [value for value in values if value is not None]
    if not filtered:
        return None
    return float(median(filtered))


def parse_datetime(value: str | datetime | None) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | list[Any] | None = None,
    timeout: int = 30
) -> Any:
    if params:
        query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
        url = f"{url}?{query}"

    raw_payload = None
    request_headers = {"User-Agent": "Mozilla/5.0"}
    if headers:
        request_headers.update(headers)
    if payload is not None:
        raw_payload = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(url, data=raw_payload, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="ignore"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        safe_url = redact_sensitive_url(url)
        safe_detail = redact_sensitive_text(detail)[:500]
        raise RuntimeError(f"{method} {safe_url} failed: HTTP {exc.code} {safe_detail}") from exc


def request_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 30
) -> str:
    request_headers = {"User-Agent": "Mozilla/5.0"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9가-힣]+", "-", value).strip("-")
    return value.lower() or "untitled"
