# 프론트 인수인계 (web/)

## 파일 지도
| 경로 | 역할 |
|---|---|
| `web/src/theme/tokens.css` | **바꿔도 되는 유일한 값 파일**(색·글꼴·간격·모서리). 변수 이름은 scrap-web `global.css`와 같다 |
| `web/src/theme/base.css`, `web/src/app.css` | 공통 모양과 배치. `var(--…)`만 쓴다 |
| `web/src/api/client.js` | 실제 API 호출·오류 처리(401/409/422/네트워크) |
| `web/src/api/normalize.js` | ui-v1 필드가 없는 서버에서도 화면이 돌도록 기존 필드로 채움 |
| `web/src/api/mock/` | 목 API + 시나리오 JSON(`VITE_USE_MOCK=1`) |
| `web/src/screens/` | CompanyPage(`#/company`), CasesPage, NewCasePage, CasePage(문진), HistoryPage |
| `web/src/components/` | QuestionCard(질문 카드 1종), Board(판정 보드), BranchCards(서류·충돌·결과·판정 불가) |

## 규칙
- 테마는 `tokens.css`만 바꾼다. 컴포넌트 로직·API 형식·`docs/ui/ui-contract.md`는 건드리지 않는다.
- 화면 문구·흐름 기준은 `docs/ui/ui-design.md`다.

## scrap-web 셸에 붙이기
1. 라우트 `#/company`, `#/cases`, `#/cases/new`, `#/cases/:id`, `#/cases/:id/history`를 scrap-web 라우터에 연결한다(`web/src/lib/router.js`가 같은 `currentRoute/navigate` 형태).
2. `web/src/App.jsx`의 상단 바와 `l3-shell`을 scrap-web 레이아웃으로 바꾸고, 화면 컴포넌트(`screens/*`)만 가져간다.
3. 개발용 회사 선택(`CompanyPage`의 Picker, `api/company.js`)은 scrap-web의 실제 로그인으로 바꾼다. `api/client.js`의 `companyId()`가 `X-Company-Id` 헤더를 만든다.
4. `/api` 접두어는 개발 프록시가 떼 준다. 배포 시 `VITE_API_BASE`로 서버 주소를 지정한다.

## 대체되는 scrap-web 화면
scrap-web의 survey 화면과 `classification-view-v1` 화면을 이 문진 화면(`CasePage`/`CasesPage`)이 대체한다.
