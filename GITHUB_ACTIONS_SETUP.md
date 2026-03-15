# GitHub Actions / GitHub Pages 설정

이 프로젝트는 `GitHub Actions + GitHub Pages` 조합으로 무료 자동화에 맞춰져 있습니다.

구성:

- `YouTube Insider Daily`
  - 매일 `오전 8:07 KST`
  - 파이프라인 실행
  - 텔레그램 전송
  - 최신 `data/*.json`, `data_bundle.js` 갱신 후 커밋
- `Deploy Dashboard Pages`
  - main 브랜치에 데이터가 갱신되면 자동 배포
  - 휴대폰에서 읽기 전용 대시보드를 브라우저로 접속 가능

## 1. GitHub 저장소 만들기

무료로 유지하려면 `public repository`로 시작하는 것을 권장합니다.

프로젝트 루트에서 한 번만 실행합니다.

```powershell
cd 'C:\Users\DanKim\Desktop\blank-app\youtube-benchmark-dashboard-mvp'
git init
git branch -M main
git add .
git commit -m "Initial commit"
```

그다음 GitHub에서 새 저장소를 만든 뒤 remote를 연결하고 push합니다.

```powershell
git remote add origin https://github.com/<YOUR_ID>/<YOUR_REPO>.git
git push -u origin main
```

## 2. GitHub Secrets 넣기

저장소 `Settings -> Secrets and variables -> Actions -> New repository secret`

필수 secret:

- `YOUTUBE_API_KEY`
- `APIFY_TOKEN`
- `GEMINI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

선택 secret:

- `OPENAI_API_KEY`
- `NOTION_TOKEN_V2`

현재 워크플로우는 아래 값을 기본으로 사용합니다.

- `LLM_PROVIDER=gemini`
- `GEMINI_MODEL=gemini-2.5-flash-lite`
- `NOTION_SOURCE_URL=https://www.notion.so/1c61ff0d0be880d39d6dd9faf563ed5c?v=1c61ff0d0be880d3b12d000c5768d1c9&source=copy_link`
- `PUBLIC_DASHBOARD_URL=https://davidsteakhouse.github.io/youtube-insider-dashboard/`

노션 URL을 바꾸고 싶으면 workflow 파일이나 코드 기본값을 수정하면 됩니다.

## 3. GitHub Pages 켜기

저장소 `Settings -> Pages`

- `Source`: `GitHub Actions`

설정 후 `Deploy Dashboard Pages` 워크플로우가 읽기 전용 사이트를 배포합니다.

처음에는 404가 보일 수 있습니다. 아래 순서로 맞추면 해결됩니다.

1. `Settings -> Pages -> Source`를 `GitHub Actions`로 설정
2. `Actions -> Deploy Dashboard Pages`를 한 번 수동 실행
3. 1~2분 뒤 다시 접속

## 4. 자동 실행 시간

GitHub Actions의 cron은 `UTC` 기준입니다.

- 현재 설정: `7 23 * * *`
- 한국 시간 기준: `매일 오전 8:07`

## 5. 휴대폰에서 보는 방식

GitHub Pages 배포가 끝나면 주소는 보통 아래 형태입니다.

```text
https://<YOUR_ID>.github.io/<YOUR_REPO>/
```

이 주소는 `읽기 전용 대시보드`입니다.

- 검색/탐색/상세 보기 가능
- `업데이트 실행`
- `Notion 다시 가져오기`

위 두 기능은 로컬 API가 필요한 기능이라 GitHub Pages에서는 비활성화됩니다.

## 6. 권장 운영 방식

- 자동 수집/알림: GitHub Actions
- 휴대폰 확인: GitHub Pages
- 로컬 수정/점검: `serve_dashboard.py`

## 7. 데이터 보관 방식

- GitHub에는 `data/watchlist.json`, `data/videos.json`, `data/digest.json`, `data_bundle.js`만 반영됩니다.
- 로컬 SQLite 파일 `data/youtube_insider.db`는 GitHub에 올리지 않습니다.
- Actions 러너는 실행 시 JSON export를 다시 읽어 SQLite를 재구성합니다.

## 8. 참고

- GitHub Actions은 public repository에서 무료로 사용할 수 있습니다.
- GitHub Pages는 public repository에서는 GitHub Free로 사용할 수 있습니다.
- private repository에서 Pages를 쓰려면 GitHub Pro 이상이 필요할 수 있습니다.
