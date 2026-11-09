# 폐기물 문진 참조 프론트 (web/)

UI팀이 문진 흐름과 API 응답 형식을 직접 눌러 보며 이해하도록 만든 **테스트용 화면**입니다. scrap-web에 복사하지 않습니다(안내: `docs/ui/handover.md`).

React 19 + Vite. 화면 설계는 `docs/ui/ui-design.md`, API 형식은 `docs/ui/ui-contract.md`.

## 실행
```
cd web
npm install
npm run dev        # 실제 서버: /api → VITE_PROXY_TARGET(기본 http://127.0.0.1:8030), 포트 5180
npm run dev:mock   # 백엔드 없이 목 API (VITE_USE_MOCK=1)
npm run build      # dist/
npm test           # vitest
npm run fixtures   # 목 예시 JSON 다시 만들기
```
첫 화면에서 `#/company`로 회사를 만들거나 골라야 합니다(X-Company-Id를 localStorage에 저장).
목 모드에서 메모에 "PP", "오니", "황산" 등을 넣으면 시나리오(PP / 오니 서류 요청·충돌 / 폐산)가 정해집니다.

## 환경 변수 (`.env.example`)
`VITE_API_BASE`(기본 /api) · `VITE_PROXY_TARGET` · `VITE_PORT` · `VITE_USE_MOCK`(1이면 목) · `VITE_MOCK_DELAY`(ms)

## 구조
`src/api`(client·normalize·mock) · `src/screens`(화면 5개) · `src/components`(QuestionCard·Board·BranchCards) · `src/lib` · `src/theme`.
색·글꼴 값은 `src/theme/tokens.css`에만 있습니다.
