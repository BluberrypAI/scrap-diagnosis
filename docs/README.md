# 문서 목차

처음이면 **[team/guide.md](team/guide.md)** 부터 읽으세요. 엔진이 하는 일과 팀별로 할 일을 쉽게 정리했습니다.

## 폴더 구성

| 폴더·파일 | 내용 | 주로 읽는 사람 |
|---|---|---|
| [team/guide.md](team/guide.md) | 팀원용 연동 안내(용어 풀이, 처리 순서, 역할별 체크리스트, 정해야 할 것) | 모두 |
| [team/integration-changes-20261109.md](team/integration-changes-20261109.md) | 통합 작업안(E·S·W·D) 반영 결과 전체 목록, 팀 기술스택과 다른 점 | 모두 |
| [engine/algorithm.md](engine/algorithm.md) | 엔진 내부 알고리즘: 규칙 데이터, 3값 평가와 확정, 질문 고르기(PP 계산 예시), 분기, 한 턴의 처리 순서 | 모두(1절), 엔진 개발자 |
| [api/engine-api-summary.md](api/engine-api-summary.md) | **API 요약(명세서 반영용)**: API 주소·Request·Response·설명 한 장 정리 | 서버 |
| [api/server-engine-contract.md](api/server-engine-contract.md) | 서버 ↔ 엔진 내부 API 규약: 인증, 엔드포인트, 서류 검수·적용, 오류 코드 | 서버 |
| [api/api-spec.md](api/api-spec.md) | API 전체 명세(상태 전이 포함) | 서버·웹 |
| [api/openapi.json](api/openapi.json) | 요청·응답 스키마(`scripts/export_openapi.py`로 생성) | 서버·웹 |
| [handoff-contract.md](handoff-contract.md) | 확정 결과를 경로추천 AI에 넘기는 인계 객체(`diagnosis-handoff-v1`) | AI·서버 |
| [document-extraction-contract.md](document-extraction-contract.md) | 서류 자동 읽기(OCR·AI)를 붙일 때의 입출력 형식(지금은 미구현) | 서류 담당 |
| [llm-data-policy.md](llm-data-policy.md) | AI 전송 정책: 개인정보 가리기, 문서 원문 차단, 기록 최소화 | 모두 |
| [design/rule-review-and-amendment.md](design/rule-review-and-amendment.md) | (제안) 전문가 규칙 검토와 법령 개정 반영 설계 | 모두, 도메인 전문가 |
| [design/reliability-roadmap.md](design/reliability-roadmap.md) | (제안, 향후 할 일) 장기 운영 신뢰성: 경로 자동 탐색, 규칙 증명 검사, 안전 원칙, 그림자 판정, 개정 감시 | 모두 |
| [design/agent-skill-harness.md](design/agent-skill-harness.md) | (제안) 규칙 엔진 위에 스킬·하네스를 얹어 보충 설명·부가 기능을 붙이는 설계(판정은 엔진 유지) | 모두 |
| [design/test-report-table-extraction.md](design/test-report-table-extraction.md) | (제안) 시험성적서 표 인식: 칸 단위 표 → 칸 좌표로 값 검증 | 엔진, AI |
| [design/image-recognition-mapping.md](design/image-recognition-mapping.md) | (초안) AI허브 산업 폐기물 이미지 클래스 → 문진 소재·질문 대응표 | 엔진, AI |
| [ui/](ui/) | 화면 설계(`ui-design.md`), 화면용 API 계약(`ui-contract.md`), 프론트 인수인계(`handover.md`) | 웹 |
| [perf/sync-vs-async.md](perf/sync-vs-async.md) | 동기·비동기 서버 부하 측정 결과 | 서버·DB 결정 |
| [perf/turn-latency.md](perf/turn-latency.md) | 실제 Azure로 잰 문진 한 턴의 지연, 서버 타임아웃 제안 | 서버 |
| [rule-changes/](rule-changes/) | 규칙 내용 수정 기록(D1 비폐기물·적용 제외, D2 오니·PCB, D4 문구, D5 유기용매 섞인 산 폐액). 바뀐 조건·판정 영향·전문가 확인 항목 | 도메인 전문가·개발자 |
| [../knowledge/README.md](../knowledge/README.md) | 규칙 원본 형식, 질문 전략, 용어집, 전문가 검토 카드(`tools/review_kit.py`) | 개발자·도메인 전문가 |
| [agent-changelog.md](agent-changelog.md) | AI 코딩 도구 규칙(`AGENTS.md`, `CLAUDE.md`) 변경 기록 | 개발자 |
| [history/](history/) | 개발 단계별 결과 보고(M3 AI 추출, M4 API·저장, 소재 2단계 질문) | 기록용 |

## 문서 관리 규칙

- `handoff-contract.md`, `document-extraction-contract.md`, `ui/ui-contract.md`, `api/server-engine-contract.md`는 코드·테스트가 경로를 참조합니다. 옮기거나 이름을 바꾸지 마세요(`tests/test_document_contract.py`는 파일을 직접 읽습니다).
- API를 바꾸면 `uv run python scripts/export_openapi.py`로 `openapi.json`을 다시 만듭니다.
- 날짜가 붙은 결과 문서는 그 시점 기록입니다. 새 변경은 새 문서로 남기고 이 목차에 추가합니다.
