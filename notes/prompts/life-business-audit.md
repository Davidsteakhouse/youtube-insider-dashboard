# 라이프/비즈니스 종합 감사 프롬프트 (Astra 나오면 사용)

- 출처: X(트위터) 스크린샷 캡처, 2026-09-04 저장
- 맥락: 커넥터로 Email, Slack, Business Texts, Notion 등 모든 워크스페이스를
  붙여둔 상태(수개월간 여러 팀과 진행한 20여 개 프로젝트)에서 아래 프롬프트를 한 번에 던짐.
- 작성자 코멘트: "잘 다듬은 프롬프트도 아니고 그냥 음성으로 주절거린 것"인데
  "AI가 준 결과물 중 가장 유용했다"고 함.

## 사용 전 체크리스트
1. 커넥터 연결: 이메일 / Slack / 문자 / Notion / 캘린더 / 문서
2. 기간 지정: 최근 3~6개월
3. 모델: GPT6 Astra (혹은 Claude 최신 모델)로 동일 실행 후 결과 비교 → 영상 소재

## 원문 프롬프트 (영어)

```
"I'm about to plan the next month, quarter, and year." Make one document that
aligns me on all of those timeframes. Look for my flaws, look for my strengths,
and highlight those. Look at ALL of my activities, which activities do you think
I'm wasting the most time. Which activities should I do more of? Of the people I
work with who seem the most dependable? Where am I the least dependable? If I
could only upskill in one area over the next year what would it be and why?
Where can I organize my company better, and how would I do that?

Use text when necessary, use charts/visuals when necessary, but never ever fill
space for the sake of it. Every graphic and word should matter. I want to know
about finances, relationships, business model, everything.
```

## 한국어 버전

```
나는 지금 다음 한 달, 분기, 1년을 계획하려고 한다. 이 세 시간축을 한 번에
정렬해주는 문서 하나를 만들어줘.

- 내 약점을 찾아내고, 강점도 찾아서 각각 명확히 짚어줘.
- 내 모든 활동을 살펴보고, 가장 시간을 낭비하고 있다고 생각되는 활동은 무엇인지 알려줘.
- 반대로 더 많이 해야 할 활동은 무엇인가?
- 함께 일하는 사람들 중 가장 믿을 만한 사람은 누구인가?
- 나는 어느 부분에서 가장 덜 믿음직한가?
- 앞으로 1년간 딱 한 가지 역량만 키울 수 있다면 무엇을, 왜 골라야 하나?
- 회사를 더 잘 조직화할 수 있는 지점은 어디이고, 구체적으로 어떻게 하면 되나?

필요할 때만 텍스트를 쓰고, 필요할 때만 차트/시각자료를 써라. 분량을 채우기 위한
내용은 절대 넣지 마라. 모든 그래픽과 모든 단어에 의미가 있어야 한다.
재무, 인간관계, 비즈니스 모델까지 전부 다루라.
```

## 영상 활용 아이디어
- "GPT6 Astra에게 내 3개월치 업무 데이터를 다 던져봤다" 포맷
- 같은 프롬프트를 Claude Fable 5.1 / Astra에 각각 넣고 결과물 비교
- 실제로 지적당한 약점 공개 → 반응 유도
