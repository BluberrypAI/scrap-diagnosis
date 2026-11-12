# 참조 화면 안내 (web/, UI팀용)

`web/`은 **동작과 형식을 확인하는 테스트용 화면**입니다. UI팀이 다음을 직접 눌러 보며 이해하도록 만들었습니다.

- 문진이 어떤 흐름으로 진행되는지(질문 → 서류 요청 → 결과 확인 → 확정 → 인계)
- 응답의 어떤 필드로 어떤 화면을 그리는지(`branch`, `ui.question`, `ui.board`, `ui.result` 등)
- 오류·충돌·재시도 같은 예외 상황을 화면에서 어떻게 다루는지

팀 규칙(저장소 사이의 약속은 API 형식뿐, 다른 저장소 코드를 복사하지 않음)에 따라 **이 코드를 scrap-web에 복사하지 않습니다.** scrap-web에서는 이 화면과 [ui-design.md](ui-design.md), [ui-contract.md](ui-contract.md)를 기준으로 직접 구현합니다.

## 실행해 보기

```bash
cd web && npm install
npm run dev:mock   # 백엔드 없이 목 API로 화면만 보기(메모에 "PP", "오니", "황산" → 시나리오)
npm run dev        # 실제 엔진에 붙여 보기(엔진: uv run uvicorn app.main:app --port 8030)
```

목 모드의 응답 예시는 `web/src/api/mock/`의 JSON이며, 실제 엔진 응답과 같은 형식입니다.

## 테스트용이라 실제와 다른 점

| 참조 화면 | 실제 서비스(scrap-web) |
|---|---|
| 엔진을 **직접** 부른다(개발용 루트 경로, `X-Company-Id`만) | scrap-web은 **scrap-server만** 부른다. 서버가 엔진 `/internal/v1`을 대신 부른다 |
| 개발용 회사 선택 화면(`#/company`)으로 기업을 고른다 | 실제 로그인. 기업은 서버가 정한다 |
| "검수 완료로 적용 (개발용)" 버튼으로 서류 값을 바로 적용한다 | 서버의 서류 검수 화면에서 사람이 원문을 보고 검수한다 |
| 색·글꼴은 `web/src/theme/tokens.css`(scrap-web `global.css`와 같은 변수 이름) | scrap-web 테마 그대로 |

## 어디를 보면 되나

| 보고 싶은 것 | 파일 |
|---|---|
| 응답 필드를 화면으로 바꾸는 방법 | `web/src/screens/CasePage.jsx`(분기별 카드 선택), `web/src/components/` |
| 질문 카드 입력 형태(버튼·숫자·범위·묶음) | `web/src/components/QuestionCard.jsx` |
| 판정 보드(확인된 사실·남은 후보·되돌리기) | `web/src/components/Board.jsx` |
| 서류·충돌·결과·판정 불가 카드 | `web/src/components/BranchCards.jsx` |
| 오류 처리(401·409·422·네트워크) | `web/src/api/client.js` |
| 화면 문구·흐름 기준 | [ui-design.md](ui-design.md) |
| 화면이 쓰는 API 필드 | [ui-contract.md](ui-contract.md) |

## 개발자 화면 (개발 서버에서만)

참조 화면을 개발 모드(`npm run dev`, 목 API 아님)로 띄우면 개발자용 화면 두 개가 보입니다. 엔진 API(`/dev/rules/*`)도 `APP_ENV=prod`에서는 404입니다.

| 화면 | 주소 | 보는 것 |
|---|---|---|
| 규칙 보기 | `#/dev/rules` (상단 "규칙 그래프(개발)") | **전체 구조**: 공통 단계(폐기물 해당 → 법 적용 → 사업장, 해당하면 빠지는 결론), 소재 분류 × 지정폐기물 법 조항 표(칸 = 확인하는 소재 수), 모든 소재 공통 오염 확인(폐유·PCB·유해화학물질), 결론. **소재별 판정 흐름**: 판정 순서대로 규칙 카드(조건 → 결론), 검색. 카드·칸을 누르면 오른쪽에 규칙·소재 목록 |
| AI 데이터 확인 | `#/cases/{id}/dev` (문진 화면 "AI 데이터(개발)") | 턴마다 AI에 보낸 지침·데이터(식별 정보 가림)와 받은 값, guard 채택·버림, 분기 이유·질문 점수, 응답 검사·보충 설명, 유효 사실. **"안내용으로 찾은 자료만"** 보기: 사용자가 "왜?", "뭐예요?"라고 물은 턴만 모아, 엔진이 찾은 자료(가장 가까운 FAQ·질문 안내·참고 주제·용어집·규칙 근거·웹 검색)와 AI가 인용한 근거, 최종 설명 문장을 보여 줌 |
