# YouTube Insider _ v2

이 프로젝트는 `정적 HTML 대시보드 + Python 로컬 API 서버 + SQLite 누적 저장소` 구조로 동작합니다.  
핵심 목적은 `최근 24시간 경쟁 채널 분석`만 보는 것이 아니라, `누적 벤치마킹 기록을 검색하고 날짜별로 다시 꺼내보는 운영 콘솔`을 만드는 것입니다.

## 현재 구현된 범위

- `SQLite` 기반 누적 저장
  - `channels`
  - `videos`
  - `video_comments`
  - `daily_digests`
- `run_pipeline.py`
  - 기본 실행 시 `Notion 자동 동기화 -> YouTube 수집 -> transcript -> 분석 -> digest -> JSON export -> data_bundle.js`
- 로컬 API 서버
  - `GET /api/bootstrap`
  - `GET /api/search?q=...`
  - `GET /api/channel/{channel_key}`
  - `POST /api/pipeline/run`
  - `POST /api/watchlist/import-notion`
- 표 중심 대시보드
  - `일별 종합`
  - `일별 상세`
  - `모니터링 리스트`
- 누적 히스토리 탐색
  - 날짜별 접기/펼치기
  - 키워드/채널/카테고리/날짜 검색
  - 영상 상세 + 채널 상세
- transcript 강화
  - Apify 우선
  - 실패 시 `youtube-transcript-api` 또는 `yt-dlp` fallback 시도

## 주요 파일

- `index.html`: 화면 구조
- `styles.css`: 표 중심 UI 스타일
- `app.js`: API/bootstrap 로딩, 검색/필터, 날짜 그룹, 상세 패널 렌더링
- `scripts/storage.py`: SQLite 스키마와 조회/export 로직
- `scripts/run_pipeline.py`: 전체 파이프라인 진입점
- `scripts/serve_dashboard.py`: 정적 파일 + JSON API 로컬 서버
- `scripts/youtube_fetcher.py`: YouTube 채널/영상/댓글 수집
- `scripts/transcript_fetcher.py`: transcript 수집
- `scripts/analyzer.py`: Gemini/OpenAI/휴리스틱 분석
- `scripts/digest_builder.py`: 크리에이터용 브리프 생성

## 빠른 시작

1. `.env.example`를 참고해 `.env`를 만듭니다.
2. 가장 쉬운 실행 방식은 `open_dashboard.pyw` 더블클릭입니다.
   - 로컬 API 서버를 먼저 띄운 뒤 브라우저를 엽니다.
   - 이 모드에서만 `Notion 다시 가져오기`, `업데이트 실행` 버튼이 동작합니다.
3. 수동으로 실행하려면 서버를 직접 띄웁니다.

```powershell
cd 'C:\Users\DanKim\Desktop\blank-app\youtube-benchmark-dashboard-mvp'
C:\Users\DanKim\anaconda3\python.exe .\scripts\serve_dashboard.py
```

4. 브라우저에서 `http://127.0.0.1:8000`으로 접속합니다.

### `index.html` 직접 열기

- `index.html`을 탐색기에서 직접 열어도 대시보드를 볼 수 있습니다.
- 이 경우 `data_bundle.js` 기반의 `읽기 전용 미리보기`로 동작합니다.
- 검색/탐색/상세 보기까지는 가능하지만, `Notion 다시 가져오기`와 `업데이트 실행`은 비활성화됩니다.

## 파이프라인 실행

### 전체 업데이트

```powershell
C:\Users\DanKim\anaconda3\python.exe .\scripts\run_pipeline.py
```

기본 동작:

- Notion 워치리스트 자동 동기화
- 활성 채널만 수집
- 최근 24시간 영상 수집
- transcript / 분석 / digest 생성
- `data/watchlist.json`, `data/videos.json`, `data/digest.json`, `data_bundle.js` 갱신

### Notion 수동 동기화만

```powershell
C:\Users\DanKim\anaconda3\python.exe .\scripts\run_pipeline.py --sync-watchlist
```

### Telegram 전송 포함

```powershell
C:\Users\DanKim\anaconda3\python.exe .\scripts\run_pipeline.py --notify-telegram
```

### 자동 Notion sync 비활성화

```powershell
C:\Users\DanKim\anaconda3\python.exe .\scripts\run_pipeline.py --no-sync-watchlist
```

## 필요한 환경 변수

필수:

- `YOUTUBE_API_KEY`
- `APIFY_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

선택:

- `GEMINI_API_KEY`
- `OPENAI_API_KEY`
- `LLM_PROVIDER=gemini`
- `NOTION_SOURCE_URL`
- `WATCHLIST_IMPORT_FILE`
- `NOTION_TOKEN_V2`
- `APIFY_YOUTUBE_TRANSCRIPT_ACTOR_ID`

## 메모

- 검색과 히스토리는 `SQLite` 기준입니다.
- `data/*.json`과 `data_bundle.js`는 프런트 fallback용 파생 export입니다.
- 한국어 transcript 기본 actor는 `futurizerush~youtube-transcript-scraper` 기준으로 잡혀 있습니다.
- 공개 Notion DB는 익명으로 row 값을 못 주는 경우가 있으므로, 안정적으로 쓰려면 `NOTION_TOKEN_V2` 또는 수동 import 파일이 필요할 수 있습니다.
- `youtube-transcript-api`, `yt-dlp`가 설치돼 있지 않으면 fallback transcript 단계는 자동으로 건너뜁니다.

## GitHub Actions 자동화

이 프로젝트는 `GitHub Actions + GitHub Pages` 기준 자동화를 포함합니다.

가장 단순하고 무료로 유지하려면 `public repository` 기준이 좋습니다.

- 매일 `오전 8시 KST` 자동 실행
- Telegram 브리프 전송
- 최신 `data/*.json`, `data_bundle.js` 갱신
- GitHub Pages 읽기 전용 대시보드 자동 배포

워크플로우 파일:

- `.github/workflows/youtube-insider-daily.yml`
- `.github/workflows/deploy-pages.yml`

설정 문서는 [GITHUB_ACTIONS_SETUP.md](./GITHUB_ACTIONS_SETUP.md)에 정리돼 있습니다.

핵심 포인트:

- GitHub Actions cron은 UTC 기준이라 `오전 8시 KST = 전날 23:00 UTC`
- 읽기 전용 모바일 대시보드는 GitHub Pages로 보는 구조
- `업데이트 실행`, `Notion 다시 가져오기`는 여전히 로컬 API 모드에서만 동작
- SQLite는 로컬 전용이고, GitHub Actions에서는 JSON export를 읽어 매 실행마다 다시 복원
