# PROJECT_STATUS.md

## 현재 상태

기준 시점: `2026-03-30`

이 프로젝트는 현재 `실사용 가능한 상태`다.  
다만 transcript 수집 경로는 지금 조정 중이다.

- GitHub Actions 자동 실행: 설정 완료
- GitHub Pages 읽기 전용 대시보드: 동작 확인
- Telegram 브리핑: 동작 확인
- Notion watchlist import: 공개 URL 기준 동작 확인
- transcript 수집: `supreme_coder + 상태 분리(unavailable)` 기준으로 운영 전환 완료

## 현재 운영 URL

- 저장소: `https://github.com/Davidsteakhouse/youtube-insider-dashboard`
- Pages: `https://davidsteakhouse.github.io/youtube-insider-dashboard/`
- 정식 작업 루트:
  `C:\Users\DanKim\Desktop\Wealth\3. ai project\0. youtube benchmark dashboard`
- 예전 작업 루트:
  `C:\Users\DanKim\Desktop\blank-app\youtube-benchmark-dashboard-mvp`
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

## transcript 수집 현황

### 현재 결론

- 목표는 `7개 전부 강제 회수`가 아니라 `자막이 실제로 존재하는 영상 최대 회수`다.
- `TranscriptsDisabled` 영상은 caption API 계열로는 회수할 수 없다.
- 같은 IP에서 짧은 시간에 반복 테스트하면 `RequestBlocked / 429`가 걸릴 수 있다.
- 차단이 감지되면 그 실행에서는 추가 개별 수집을 멈추는 쪽이 맞다.

### 최근 실험 결과

1. `futurizerush/youtube-transcript-scraper`
- 성공률은 높지만 비용이 `약 $0.05/video`
- 한국어 채널이 많을 때 월 `$5` 예산을 넘기기 쉬움

2. `johnvc/youtubetranscripts`
- 비용은 매우 저렴함
- 하지만 한국어 영상에서 `en` 편향 + `RequestBlocked`가 겹쳐 성공률이 낮았음
- 특히 `ko auto-generated`만 있는 영상을 안정적으로 못 가져옴

3. 로컬 `youtube-transcript-api`
- 초반에는 일부 한국어 영상 회수 성공
- 이후 반복 테스트 누적으로 현재 IP에서 `YouTube is blocking requests from your IP` 발생
- `yt-dlp`도 같은 시점에 `HTTP Error 429: Too Many Requests` 확인

4. `supreme_coder/youtube-transcript-scraper`
- 샘플 3개 테스트에서 `영어 1개 + 한국어 1개 성공`, `자막 비활성 1개 unavailable` 확인
- 동일 7개 세트 테스트에서 `6개 available + 1개 unavailable`, `unresolved 0`
- 현재 watchlist 용도로는 `johnvc`보다 훨씬 유력함

### 현재 코드 반영 사항

- `youtube-transcript-api 1.2.4` 기준으로 정적 `get_transcript()` 대신 인스턴스 `api.fetch()` 사용
- `RequestBlocked / IPBlocked / 429` 감지 로직 추가
- 한 영상당 transcript API 요청을 최대한 `1회`로 단순화
- `TRANSCRIPT_FETCH_DELAY_SEC` 기본값을 `8초`로 반영
- 현재 IP 차단이 감지되면 그 실행의 나머지 개별 수집을 즉시 중단
- `TRANSCRIPTS_DISABLED`, `PRIVATE_VIDEO`, `AGE_RESTRICTED` 등은 `unavailable`로 저장해 재시도 낭비 방지

### 운영 판단

- 당일 수동 테스트를 여러 번 반복하지 말 것
- 차단이 걸리면 몇 시간 뒤 또는 다음날 `2~3개`만 소량 재테스트할 것
- 현재 기준 추천안은 `로컬 transcript_api 1차 시도 + blocked 감지 시 supreme_coder Apify fallback`이다
- `supreme_coder`는 한국어/영어 모두 실제 샘플 검증을 통과했다

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
- `APIFY_YOUTUBE_TRANSCRIPT_ACTOR_ID`
- `APIFY_YOUTUBE_TRANSCRIPT_FALLBACK_ACTOR_ID`
- `TRANSCRIPT_FETCH_LIMIT`
- `TRANSCRIPT_FETCH_DELAY_SEC`

## 현재 데이터 구조

- `data/watchlist.json`
  - 채널 스냅샷
- `data/videos.json`
  - 누적 영상 스냅샷
- `data/digest.json`
  - 최신 브리핑
- `data_bundle.js`
  - 정적 fallback
- `data/youtube_insider.db`
  - 로컬 SQLite
  - GitHub에는 커밋하지 않음

## 현재 알려진 주의점

1. GitHub Actions가 `data/*.json`, `data_bundle.js`를 자동 커밋하므로, 사람이 코드 push할 때 rebase가 자주 필요하다.
2. 공개 Notion import는 row 응답이 흔들릴 수 있다.
3. GitHub Pages는 읽기 전용이라, 업데이트 실행/Notion 다시 가져오기는 로컬 API 모드에서만 된다.
4. transcript 수집은 현재 IP 상태에 민감하다. `RequestBlocked`가 뜨면 그날은 추가 수동 테스트를 줄여야 한다.
5. `johnvc` actor는 가격은 좋지만 한국어 중심 watchlist에서는 신뢰도가 낮았다.
6. `futurizerush` actor는 성공률은 높지만 비용이 높다.
7. `supreme_coder` actor는 현재 샘플 기준 가장 균형이 좋다.
8. 예전 `blank-app` 폴더는 복사본으로 남아 있을 수 있으니 새 작업은 `Wealth` 폴더 기준으로 이어간다.

## 다음 작업자에게 권장하는 순서

1. `CLAUDE.md` 먼저 읽기
2. `README.md`로 실행 구조 확인
3. transcript 문제면 `scripts/transcript_fetcher.py`부터 확인
4. 자동화 문제면 `.github/workflows/youtube-insider-daily.yml` 확인
5. 데이터/브리핑 수정이면 `scripts/digest_builder.py`, `scripts/storage.py`, `scripts/run_pipeline.py`
6. UI 수정이면 `app.js`, `styles.css`, `index.html`
