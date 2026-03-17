# CLAUDE.md

## 프로젝트 목적

이 저장소는 `AI 경쟁 유튜브 채널 벤치마크 대시보드`다.

- 최근 24시간 업로드를 수집하고
- 자막/댓글/메타데이터를 분석해서
- 한국어 브리프를 만들고
- Telegram과 GitHub Pages로 전달한다.

핵심 사용자는 `AI 유튜브 크리에이터`다.  
예쁜 카드보다 `오늘 뭘 찍을지 판단하는 정보 밀도`가 더 중요하다.

## 현재 운영 구조

- 정식 작업 루트:
  `C:\Users\DanKim\Desktop\Wealth\3. AI PROJECT\0. youtube benchmark dashboard`
- 예전 작업 루트:
  `C:\Users\DanKim\Desktop\blank-app\youtube-benchmark-dashboard-mvp`
- 기본 원칙:
  - 앞으로 코드 수정과 Git 작업은 `Wealth` 폴더 기준으로 한다.
  - `blank-app` 폴더는 이전 작업 복사본으로 보고, 새 작업 기준으로 사용하지 않는다.
- GitHub 저장소: `https://github.com/Davidsteakhouse/youtube-insider-dashboard`
- GitHub Pages: `https://davidsteakhouse.github.io/youtube-insider-dashboard/`
- 자동 실행: GitHub Actions `YouTube Insider Daily`
- 실행 시각: 매일 `08:07 KST`
- 모바일 확인: GitHub Pages 읽기 전용 대시보드
- 알림: Telegram bot message

## 현재 기본 규칙

1. 모든 사용자 노출 문구는 기본적으로 `한국어`를 유지한다.
2. `최근 24시간` 판정은 반드시 `published_at` 기준 실시간 계산으로 한다.
   `is_recent` 같은 오래된 플래그를 신뢰하지 않는다.
3. 날짜 표시는 `KST(Asia/Seoul)` 기준으로 맞춘다.
   - digest_date
   - 누적 영상 기록 날짜 그룹
   - 오늘/어제 판정
4. Telegram 브리프에는 `PUBLIC_DASHBOARD_URL`이 있으면 하단 링크를 붙인다.
5. GitHub Pages는 `읽기 전용`이다.
   - 탐색/검색/상세 보기: 가능
   - `Notion 다시 가져오기`, `업데이트 실행`: 로컬 API 모드에서만 가능
6. Notion은 현재 공개 URL 기준 import를 사용한다.
   공개 row 응답이 흔들릴 수 있으므로 `NOTION_TOKEN_V2`가 있으면 더 안정적이다.

## 최근에 고쳐둔 중요한 문제

- GitHub Actions Node 24 경고 대응
  - `actions/checkout@v5`
  - `actions/setup-python@v6`
- Telegram 브리프에 Pages 링크 추가
- 24시간 컷 로직 수정
  - 오래된 `is_recent` 재사용 제거
  - `published_at` 기준 실시간 계산으로 통일
- digest 날짜를 KST 기준으로 저장
- 누적 영상 기록 날짜 그룹을 KST 기준으로 변경

### 2026-03-17 수정

**문제 1: 로컬 대시보드가 GitHub Actions 최신 데이터를 반영 못함**
- 원인: 로컬 파일이 자동 동기화되지 않음
- 수정: `run_daily_update.bat` / `run_daily_update.pyw` 맨 앞에 `git pull --ff-only` 추가
- 함께 적용: 로컬 실행 시 `--notify-telegram` 제거 (Actions와 중복 발송 방지)

**문제 2: GitHub Pages preview 모드에서 "최근 24시간 영상 0개"**
- 원인: `hydrateVideos()`가 `is_recent`를 override하지 않고 `normalizeVideoPayload()`의 값을 그대로 사용
  - `normalizeVideoPayload`에서 `is_recent`를 `new Date()` 기준으로 계산하면, 데이터가 오래될수록 모든 영상이 24h 초과
- 수정 (`app.js`):
  - `isWithinRecentWindow(value, lookbackHours, referenceTime)` — referenceTime 파라미터 추가
  - `hydrateVideos(videos, referenceTime)` — return object에 `is_recent` override 추가 (referenceTime 전달)
  - `normalizeVideoPayload`의 `is_recent`는 `referenceTime` 없이 유지 (hydrateVideos가 덮어씀)
  - preview 모드 데이터 초기화: digest를 먼저 로드 → `generated_at` 추출 → hydrateVideos에 전달
- **주의**: `is_recent` override는 반드시 `hydrateVideos` return object 안에 있어야 한다.
  `normalizeVideoPayload` 안에서 `referenceTime`을 참조하면 `ReferenceError` 발생함.

**문제 3: Telegram TOP 3 제목 잘림**
- 원인: `truncate_text(title, 28)` → 너무 짧음
- 수정 (`scripts/digest_builder.py`): `truncate_text` 제거, 제목 전체 사용

**문제 4: 로컬 Telegram 발송 시 대시보드 URL 누락**
- 원인: `.env`에 `PUBLIC_DASHBOARD_URL` 미설정 (GitHub Actions에만 있었음)
- 수정: `.env`에 `PUBLIC_DASHBOARD_URL=https://davidsteakhouse.github.io/youtube-insider-dashboard/` 추가

## 파일별 역할

- `index.html`
  - 대시보드 구조
- `app.js`
  - 읽기 전용/로컬 API 모드 분기
  - 검색/필터/그룹핑
  - 영상/채널 상세 패널 렌더링
- `styles.css`
  - 표 중심 UI
- `data/watchlist.json`
  - 채널 export
- `data/videos.json`
  - 누적 영상 export
- `data/digest.json`
  - 최신 브리프 export
- `data_bundle.js`
  - 정적 미리보기 fallback bundle
- `scripts/run_pipeline.py`
  - 메인 파이프라인 진입점
- `scripts/serve_dashboard.py`
  - 로컬 API 서버
- `scripts/youtube_fetcher.py`
  - YouTube 채널/영상/댓글 수집
- `scripts/transcript_fetcher.py`
  - Apify + fallback transcript 수집
- `scripts/analyzer.py`
  - Gemini/OpenAI/휴리스틱 분석
- `scripts/digest_builder.py`
  - 브리프/텔레그램 메시지 생성
- `scripts/storage.py`
  - SQLite, snapshot export, bootstrap payload
- `.github/workflows/youtube-insider-daily.yml`
  - 매일 08:07 KST 자동 실행
- `.github/workflows/deploy-pages.yml`
  - Pages 배포

## 자주 쓰는 실행 명령

로컬 서버:

```powershell
C:\Users\DanKim\anaconda3\python.exe .\scripts\serve_dashboard.py
```

파이프라인:

```powershell
C:\Users\DanKim\anaconda3\python.exe .\scripts\run_pipeline.py
```

텔레그램까지 포함:

```powershell
C:\Users\DanKim\anaconda3\python.exe .\scripts\run_pipeline.py --notify-telegram
```

## Git / 협업 주의사항

1. 이 저장소는 GitHub Actions가 `data/*.json`, `data_bundle.js`를 자동 커밋한다.
2. 그래서 코드 수정 후 push할 때 원격이 종종 앞서 있다.
3. push 전에는 `pull --rebase`가 자주 필요하다.
4. SQLite 파일 `data/youtube_insider.db`는 GitHub에 올리지 않는다.
   GitHub Actions는 JSON export를 다시 읽어 DB를 재구성한다.

## 앞으로 수정할 때 우선순위

1. 크리에이터 활용도
   - 오늘 뭘 만들지 판단 가능한가
2. KST 기준 정확도
   - 날짜/24시간 컷
3. 모바일 가독성
   - 텔레그램과 GitHub Pages
4. Notion import 안정성
5. 과도한 장식보다 표/요약/실행 포인트
