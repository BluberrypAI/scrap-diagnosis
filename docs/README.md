# 문서 목차

처음이면 **[team/guide.md](team/guide.md)** 부터 읽으세요. 엔진이 하는 일과 팀별로 할 일을 쉽게 정리했습니다.

## 폴더 구성

| 폴더·파일 | 내용 | 주로 읽는 사람 |
|---|---|---|
| [team/guide.md](team/guide.md) | 팀원용 연동 안내(용어 풀이, 처리 순서, 역할별 체크리스트, 정해야 할 것) | 모두 |
| [team/integration-changes-20261109.md](team/integration-changes-20261109.md) | 통합 작업안(E·S·W·D) 반영 결과 전체 목록, 팀 기술스택과 다른 점 | 모두 |
| [api/server-engine-contract.md](api/server-engine-contract.md) | 서버 ↔ 엔진 내부 API 규약: 인증, 엔드포인트, 서류 검수·적용, 오류 코드 | 서버 |
| [api/api-spec.md](api/api-spec.md) | API 전체 명세(상태 전이 포함) | 서버·웹 |
| [api/openapi.json](api/openapi.json) | 요청·응답 스키마(`scripts/export_openapi.py`로 생성) | 서버·웹 |
| [handoff-contract.md](handoff-contract.md) | 확정 결과를 경로추천 AI에 넘기는 인계 객체(`diagnosis-handoff-v1`) | AI·서버 |
| [document-extraction-contract.md](document-extraction-contract.md) | 서류 자동 읽기(OCR·AI)를 붙일 때의 입출력 형식(지금은 미구현) | 서류 담당 |
| [llm-data-policy.md](llm-data-policy.md) | AI 전송 정책: 개인정보 가리기, 문서 원문 차단, 기록 최소화 | 모두 |
| [ui/](ui/) | 화면 설계(`ui-design.md`), 화면용 API 계약(`ui-contract.md`), 프론트 인수인계(`handover.md`) | 웹 |
| [perf/sync-vs-async.md](perf/sync-vs-async.md) | 동기·비동기 서버 부하 측정 결과 | 서버·DB 결정 |
| [perf/turn-latency.md](perf/turn-latency.md) | 실제 Azure로 잰 문진 한 턴의 지연, 서버 타임아웃 제안 | 서버 |
| [agent-changelog.md](agent-changelog.md) | AI 코딩 도구 규칙(`AGENTS.md`, `CLAUDE.md`) 변경 기록 | 개발자 |
| [history/](history/) | 개발 단계별 결과 보고(M3 AI 추출, M4 API·저장, 소재 2단계 질문) | 기록용 |

## 문서 관리 규칙

- `handoff-contract.md`, `document-extraction-contract.md`, `ui/ui-contract.md`, `api/server-engine-contract.md`는 코드·테스트가 경로를 참조합니다. 옮기거나 이름을 바꾸지 마세요(`tests/test_document_contract.py`는 파일을 직접 읽습니다).
- API를 바꾸면 `uv run python scripts/export_openapi.py`로 `openapi.json`을 다시 만듭니다.
- 날짜가 붙은 결과 문서는 그 시점 기록입니다. 새 변경은 새 문서로 남기고 이 목차에 추가합니다.
