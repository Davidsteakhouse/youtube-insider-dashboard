"""
YouTube Analytics API OAuth 초기 설정 스크립트.
최초 1회 로컬 실행 → 브라우저 인증 → refresh_token 출력.
출력된 값을 GitHub Secrets에 등록하면 GitHub Actions에서 자동 실행됨.

실행 방법:
  python setup_yt_oauth.py

사전 준비:
  1. Google Cloud Console(console.cloud.google.com)에서 프로젝트 생성 또는 기존 프로젝트 선택
  2. "YouTube Analytics API" 활성화
  3. OAuth 2.0 클라이언트 ID 생성 (유형: 데스크톱 앱)
  4. 클라이언트 ID / 시크릿을 아래에 입력하거나 환경변수로 설정

등록할 GitHub Secrets:
  YT_CLIENT_ID      — OAuth 클라이언트 ID
  YT_CLIENT_SECRET  — OAuth 클라이언트 시크릿
  YT_REFRESH_TOKEN  — 이 스크립트 실행 후 출력되는 값
  YT_CHANNEL_NAME   — 채널 표시 이름 (예: 스마트대디)
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

REDIRECT_URI = "http://localhost:8080"
SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def main() -> None:
    client_id = os.getenv("YT_CLIENT_ID") or input("YT_CLIENT_ID 입력: ").strip()
    client_secret = os.getenv("YT_CLIENT_SECRET") or input("YT_CLIENT_SECRET 입력: ").strip()

    auth_url = (
        AUTH_URL + "?"
        + urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        })
    )

    print(f"\n브라우저에서 인증 페이지를 엽니다: {auth_url}\n")
    webbrowser.open(auth_url)

    auth_code: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            if code:
                auth_code.append(code)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h1>인증 완료! 이 탭을 닫고 터미널로 돌아가세요.</h1>")

        def log_message(self, fmt: str, *args: object) -> None:
            pass

    print("localhost:8080 에서 인증 콜백 대기 중...")
    server = HTTPServer(("localhost", 8080), Handler)
    server.handle_request()

    if not auth_code:
        print("인증 코드를 받지 못했습니다.")
        return

    data = urllib.parse.urlencode({
        "code": auth_code[0],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        tokens = json.loads(resp.read())

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print(f"refresh_token이 없습니다. 응답: {tokens}")
        return

    print("\n" + "=" * 60)
    print("GitHub Actions Secrets에 아래 값을 등록하세요:")
    print("=" * 60)
    print(f"YT_CLIENT_ID      = {client_id}")
    print(f"YT_CLIENT_SECRET  = {client_secret}")
    print(f"YT_REFRESH_TOKEN  = {refresh_token}")
    print(f"YT_CHANNEL_NAME   = 스마트대디")
    print("=" * 60)


if __name__ == "__main__":
    main()
