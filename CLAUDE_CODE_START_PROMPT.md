# Claude Code 시작 프롬프트

아래 내용을 Claude Code에 그대로 붙여넣고 시작하면 됩니다.

```text
앞으로 이 프로젝트를 이어서 작업해줘.

프로젝트 정식 작업 루트:
C:\Users\DanKim\Desktop\Wealth\ai project\0. youtube benchmark dashboard

중요:
- 이 폴더를 기준으로 작업해.
- 예전 작업 복사본인 `C:\Users\DanKim\Desktop\blank-app\youtube-benchmark-dashboard-mvp`는 기준 루트로 사용하지 마.
- 먼저 문서부터 읽고 현재 상태를 파악한 뒤 작업을 시작해.

반드시 먼저 읽을 문서:
1. CLAUDE.md
2. PROJECT_STATUS.md
3. README.md
4. GITHUB_ACTIONS_SETUP.md

이 프로젝트의 목적:
- AI 유튜브 크리에이터용 경쟁 채널 벤치마크 대시보드
- 최근 24시간 업로드를 수집하고
- 자막/댓글/메타데이터를 분석해
- 한국어 브리프를 만들고
- Telegram과 GitHub Pages로 전달하는 운영 콘솔

현재 운영 구조:
- GitHub 저장소: https://github.com/Davidsteakhouse/youtube-insider-dashboard
- GitHub Pages: https://davidsteakhouse.github.io/youtube-insider-dashboard/
- GitHub Actions 자동 실행: 매일 오전 8:07 KST
- Telegram 브리프 발송: 동작 중

작업할 때 꼭 지킬 규칙:
- 사용자 노출 문구는 기본적으로 한국어 유지
- 최근 24시간 판정은 반드시 `published_at` 기준 실시간 계산
- 날짜 표시는 KST(Asia/Seoul) 기준
- GitHub Pages는 읽기 전용
- `Notion 다시 가져오기`, `업데이트 실행`은 로컬 API 모드에서만 동작
- Telegram 브리프에는 Pages 링크가 붙어야 함

특히 주의할 점:
- 이 저장소는 GitHub Actions가 `data/*.json`, `data_bundle.js`를 자동 커밋함
- 그래서 push 전에 remote가 앞서 있을 수 있으니 rebase/pull 상태를 항상 확인해
- 공개 Notion import는 응답이 흔들릴 수 있으니 import 안정성은 조심해서 다뤄

지금 Claude에게 기대하는 작업 방식:
1. 먼저 문서 4개를 읽고 현재 상태를 짧게 요약
2. 구조와 제약사항을 이해했다고 설명
3. 그다음 내가 요청하는 작업을 진행
4. 수정 시에는 어떤 파일을 왜 바꾸는지 짧게 설명
5. 작업 후에는 검증 결과까지 같이 알려줘

시작할 때는 먼저:
- 현재 프로젝트 상태 요약
- 자동화/배포 구조 요약
- 다음 작업 시 주의할 리스크

이 3가지를 먼저 정리해줘.
```
