# PROJECT_STATUS.md

## 현재 상태

기준 시점: `2026-03-15`

이 프로젝트는 현재 `실사용 가능한 상태`다.

- GitHub Actions 자동 실행: 설정 완료
- GitHub Pages 읽기 전용 대시보드: 동작 확인
- Telegram 브리프: 동작 확인
- Notion 채널 import: 현재 공개 URL 기준 동작 확인

## 현재 운영 URL

- 저장소: `https://github.com/Davidsteakhouse/youtube-insider-dashboard`
- Pages: `https://davidsteakhouse.github.io/youtube-insider-dashboard/`
- 정식 작업 루트:
  `C:\Users\DanKim\Desktop\blank-app\youtube-benchmark-dashboard-mvp`
- 사용자가 직접 열어보는 미러 폴더:
  `C:\Users\DanKim\Desktop\Wealth\ai project\0. youtube benchmark dashboard`
- Notion 채널 리스트:
  `https://www.notion.so/1c61ff0d0be880d39d6dd9faf563ed5c?v=1c61ff0d0be880d3b12d000c5768d1c9&source=copy_link`

## 현재 자동화

- 워크플로우 이름: `YouTube Insider Daily`
- 실행 시각: `매일 오전 8:07 KST`
- cron: `7 23 * * *`
- 처리 순서:
  - watchlist sync
  - YouTube 수집
  - transcript 수집
  - 분석
  - digest 생성
  - Telegram 전송
  - JSON export 커밋

## 현재 핵심 환경 변수

필수:

- `YOUTUBE_API_KEY`
- `APIFY_TOKEN`
- `GEMINI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

선택:

- `OPENAI_API_KEY`
- `NOTION_TOKEN_V2`
- `PUBLIC_DASHBOARD_URL`

## 현재 데이터 구조

- `data/watchlist.json`
  - 채널 스냅샷
- `data/videos.json`
  - 누적 영상 스냅샷
- `data/digest.json`
  - 최신 브리프
- `data_bundle.js`
  - 정적 fallback
- `data/youtube_insider.db`
  - 로컬 SQLite
  - GitHub에는 커밋하지 않음

## 최근 중요 수정 이력

### 1. GitHub Actions 안정화

- Node 24 경고 대응
- Actions schedule을 `08:07 KST`로 이동

### 2. 모바일 사용성

- GitHub Pages URL 연결
- Telegram 브리프 하단에 모바일 대시보드 링크 추가

### 3. 날짜/브리프 정확도

- digest_date를 KST 기준으로 수정
- 누적 영상 기록 그룹을 KST 기준으로 수정
- 24시간 컷을 `published_at` 기준 실시간 계산으로 수정

## 현재 알려진 주의점

1. GitHub Actions가 데이터 파일을 자동 커밋하므로, 사람이 코드 push할 때 rebase가 자주 필요하다.
2. 공개 Notion import는 row 응답이 흔들릴 수 있다.
3. GitHub Pages는 읽기 전용이라, 업데이트 실행/Notion 다시 가져오기는 로컬 API 모드에서만 된다.
4. 텔레그램 봇 토큰은 대화에 노출된 적이 있으므로 추후 재발급 권장.
5. `Wealth` 폴더는 배포/사용용 미러라서, 기본 수정 대상은 아니다.

## 다음 작업자에게 권장하는 순서

1. `CLAUDE.md` 먼저 읽기
2. `README.md`로 실행 구조 확인
3. `GITHUB_ACTIONS_SETUP.md`로 배포/자동화 구조 확인
4. UI 수정이면 `app.js`, `styles.css`, `index.html`
5. 데이터/브리프 수정이면 `scripts/digest_builder.py`, `scripts/storage.py`, `scripts/run_pipeline.py`
6. transcript 문제면 `scripts/transcript_fetcher.py`
