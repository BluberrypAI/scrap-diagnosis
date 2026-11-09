# 통합 작업안 반영 결과 (진단 엔진, 2026-11-09)

팀이 공유한 기능·API·기술스택 명세와 Codex 통합 작업안(`integration-work-items.md`의 E·S·W·D 항목)을 바탕으로 **진단 엔진(waste-diagnosis) 쪽 항목**을 반영했다. 이 문서는 다른 팀이 확인할 변경 요약이다. 상세 계약은 링크한 문서를 본다.

- 기준 커밋: `main` `a62b4a8`
- 서버 담당자가 읽을 문서: [docs/api/server-engine-contract.md](../api/server-engine-contract.md) (호출 순서·인증·오류 코드·예시), [docs/api/openapi.json](../api/openapi.json)
- 인계 객체: [docs/handoff-contract.md](../handoff-contract.md) (`diagnosis-handoff-v1`, 필드 추가만 함)

## 1. 엔진에 반영한 것

| 항목 | 상태 | 내용 |
|---|---|---|
| E1 서버 간 인증 | 반영 | 서버용 경로 `/internal/v1/...`. `Authorization: Bearer <ENGINE_SERVICE_TOKEN>` + `X-Company-Id`(서버 기업 ID, 처음 보면 자동 등록). 다른 기업의 건은 404. `APP_ENV=prod`에서 개발용 `/companies` 생성·수정은 막힘(404 `ENDPOINT_DISABLED`) |
| API 규약 | 반영 | 오류 `{"detail": {"code", "message", "details"}}`(422 검증 오류 포함), 내부 목록 `{items, pagingInfo}`. 코드 목록은 계약 문서 5절 |
| E2 서류 후보와 증빙 분리 | 반영 | 업로드·직접 입력 값은 `UNVERIFIED` 후보로만 저장하고 판정에 쓰지 않는다. 서버가 검수 결과를 `values/apply`로 보내야 `EVIDENCED`가 된다 |
| E3 서류 검증 | **축소 반영** | 엔진은 원문과 값을 대조하지 않는다(값이 맞는지 엔진이 판단할 수 없음). "-"·빈 값·숫자 칸의 글자·선택지 밖 값·다른 단위 같은 **형식 오류만** 422로 거른다. 자동 읽기(OCR·AI)는 미구현이고 값은 사람이 입력한다. `…/extract`는 계약에 "미구현"으로만 표시 |
| E4 AI 전송 정책 | 반영 | AI로 보내기 전에 사업자·법인·주민번호, 전화, 이메일, 상세주소를 가린다. 가리기에 실패하면 보내지 않는다(버튼 답변으로 안내). 문서 원문은 기본 차단(`ALLOW_DOCUMENT_LLM=false`). Trace에는 가린 문장과 해시만 남는다. [docs/llm-data-policy.md](../llm-data-policy.md) |
| E5 기업 정보 | 반영(서버 spec 기준) | 서버가 사용자에게 확인받은 값만 `confirmed_facts`로 보낸다. 엔진은 `PROFILE_CONFIRMED`로 기록하고 `company_profile_version`을 판정 버전과 `handoff.inputs`에 남긴다. 확인 전 기본값은 받지 않는다 |
| E6 규칙 버전·증빙 철회 | 반영 | 저장된 규칙 버전과 지금 규칙이 다르면 쓰기 요청은 `409 KB_CHANGED`, `POST …/rebase`로 이어 간다. 서류 `revoke`·파일 교체(`versions`) 시 그 서류에서 온 증빙을 평가에서 뺀다(이력은 보존). 확정된 판정 버전은 그대로 |
| E7 화면 계약 | 이미 반영 | 판정 보드·대화 복원·철회(retract). 서류 값 되돌리기는 E6의 revoke로 해결 |
| E8 DB(PostgreSQL) | **보류** | 아래 3절 |
| E9 기업 데이터 삭제 | 반영 | `DELETE /internal/v1/companies/{id}/data`(여러 번 불러도 결과가 같음). 그 기업의 건·사실·서류·판정·Trace를 삭제한다. 이력에는 기업 ID 해시와 건수만 남는다. 실패하면 되돌리고 `500 DELETION_FAILED`, 재호출로 재시도 |
| 버그 | 수정 | 서류 업로드 처리가 `async def` 안에서 동기 DB·AI 호출을 해서, 처리하는 동안 서버의 다른 요청이 모두 멈추던 문제 |

검증(기준 커밋): 테스트 430개 통과, ruff 통과, 기존 판정표 회귀 수치 동일(CODE/MATCH 2332 등 5개 지표), mock 골든 16/16, OpenAPI 최신, 참조 화면 테스트 7개·빌드 통과. 운영 모드(`APP_ENV=prod`)에서 내부 API로 "건 생성 → PP 문진 → 확정 → 인계 → 다른 기업 접근 거부 → 기업 데이터 삭제" 흐름을 확인했다.

## 2. 서버(scrap-server) 담당자에게 바뀐 점

1. **경로와 인증**: 서버는 `/internal/v1/...`만 부른다. 브라우저는 엔진을 직접 부르지 않는다. 토큰은 서버 설정에만 둔다.
2. **오류 변환**: 엔진 오류는 `detail.code`로 구분한다. 서버 공통 오류 형식으로 바꿀 때 `code`를 그대로 쓰면 된다. 특히 409 `KB_CHANGED`(→ rebase 호출 후 재시도)와 `CONCURRENT_UPDATE`(→ 다시 조회 후 재시도)는 서버가 처리할 흐름이다.
3. **서류**: 서버의 기존 업로드·검수·교체 API를 그대로 쓰고, 검수가 끝나면 엔진 `values/apply`로 보낸다. 파일 교체는 엔진 `versions`, 검수 취소는 `revoke`. 엔진은 `document_version`이 다르면 409 `DOCUMENT_VERSION_MISMATCH`로 막는다.
4. **기업 정보**: 확인된 값만 `confirmed_facts`로, 버전은 `company_profile_version`으로 보낸다. 회사명·상세주소·연락처는 보내지 않는다.
5. **탈퇴**: 유예 기간이 끝나면 `DELETE …/companies/{id}/data`를 부르고, 응답 `status`가 `DONE`일 때만 완료로 기록한다.

## 3. 팀 기술스택과 다른 점

| 항목 | 팀 명세 | 엔진 현재 | 이유·다음 단계 |
|---|---|---|---|
| DB 접근 | 비동기 | 동기 SQLAlchemy 2.x + Alembic | 부하 측정 결과 스레드 수를 200으로 올린 동기 서버와 비동기 서버의 처리량이 거의 같았다(동시 200턴: 4.3s vs 4.4s). 실제 병목은 Azure OpenAI 쿼터일 가능성이 크다. 근거: [docs/perf/sync-vs-async.md](../perf/sync-vs-async.md) |
| 운영 DB | PostgreSQL | 개발은 SQLite. PostgreSQL 드라이버는 아직 추가하지 않음 | E8은 방식 결정 후 진행한다. 기본안은 동기 유지 + `psycopg` 추가 + PostgreSQL에서 마이그레이션·전체 테스트(반나절). 비동기로 정하면 DB 층과 AI 호출 층 전환(1~1.5일) |
| Python | 3.12 | `>=3.12`, Dockerfile 포함 | 맞춤 |

팀 저장소 코드 점검(정적 분석, 실행·부하 측정 없음, 2026-11-09)
- **scrap-server**: DB(`AsyncSession`·asyncpg)와 외부 HTTP(`httpx.AsyncClient`)는 비동기다. 라우트도 모두 `async def`다. 다만 서류 업로드·교체·추가 자료 저장에서 `async def` 안의 동기 파일 쓰기가 이벤트 루프를 잡는다. 시설 검색 경로는 외부 검색을 기다리는 동안 DB 트랜잭션을 열어 둔다(풀 5+10).
- **scrap-ai**: 동기다. 라우트 14개가 모두 `def`이고 psycopg·Neo4j도 동기다. 자기 문서에 동기 실행이 명시돼 있다. 서버 ADR도 AI 쪽 구성은 그 저장소에서 정하도록 나눠 두었다.
- 정리하면 팀 전체가 비동기로 통일돼 있지는 않다. 엔진은 scrap-ai와 같은 방식이다(일반 `def` 라우트 → FastAPI 스레드 실행). 서버가 엔진을 비동기 HTTP로 부르므로 연동에도 문제가 없다.
- **타임아웃 주의**: 서버의 기존 분류 호출 타임아웃은 12초다. 새 엔진은 한 턴에 AI를 최대 2번 부르고 추론 모델이라 12초를 넘을 수 있다(턴당 지연은 아직 실측하지 않음). S2에서 이 경로의 타임아웃을 따로 정해야 한다.

## 4. 다른 팀이 할 일 (엔진은 계약만 제공)

| 항목 | 담당 | 엔진이 준비한 것 |
|---|---|---|
| S1 review ↔ 엔진 case 연결, 중복 시작 방지 | 서버 | `case.id`, 판정 버전, `kb_version`, `company_profile_version`, 서류 버전이 응답·인계에 있음 |
| S2 문진 라우터·클라이언트·오류 변환 | 서버 | `/internal/v1`, 오류 `code` 목록 |
| S3 서류 추출 연동·검수 값 전달 | 서버 | `values/apply`·`revoke`·`versions`, 형식 검사(422 `problems`) |
| S4 기업 프로필 최소 필드·버전 | 서버 | `confirmed_facts`, `company_profile_version` |
| S5 새 판정용 검증 분기(NO_CODE·UNVERIFIED) | 서버 | `handoff.result_type`, `route_guidance`, 규칙 검토 상태 `UNVERIFIED` |
| S6 판정·증빙 변경 시 추천 결과를 오래된 것으로 표시 | 서버 | 판정 버전 번호, reopen 시 `superseded_verdict` |
| S7 탈퇴 시 엔진 삭제 호출·재시도 기록 | 서버 | 삭제 API, `DeletionOut.status`·`attempts` |
| W1~W5 새 문진 화면·서류 검수 화면·결과 화면 | 웹 | 참조 화면 `web/`(기능·흐름 확인용), [docs/ui/](../ui/) |
| D 재활용 유형(R코드)·투입 형태 보완 | 경로추천 | 엔진은 R코드를 내지 않는다. 확정 분류·확인된 사실을 인계 객체로 넘긴다 |

## 5. 정해야 할 것

1. **DB 방식(E8)**: 동기 유지 + PostgreSQL 드라이버 추가로 갈지, 비동기로 바꿀지.
2. **서류 값 검증 책임**: 엔진은 원문 대조를 하지 않는다. "원문 2%를 7%로 잘못 입력" 같은 오류는 서버 검수 화면(W3)과 검수자가 걸러야 한다. 팀이 이 책임 분담에 동의하는지.
3. **검수 원장 위치**: 서버에도 검수 상태가 있고 엔진에도 후보 값 행(`document_values`)이 있다. 서버가 검수 기준이고, 엔진 후보는 업로드 시 함께 보낸 값을 보여 주는 용도다. 서버가 엔진 후보를 쓰지 않고 `fact_key`로 바로 적용해도 된다. 어느 방식으로 쓸지.
4. **서비스 토큰 관리**: `ENGINE_SERVICE_TOKEN`을 어디에 보관하고 어떻게 교체할지(엔진은 토큰 1개만 받는다).
5. **삭제 보관 예외**: 법정 보관 의무가 있는 판정 기록이 있다면 삭제 범위에서 뺄지. 지금은 그 기업의 데이터를 모두 지운다.
6. **R코드(D)**: 분류 엔진 범위를 넓힐지, 경로추천 쪽 보완 단계로 둘지.
7. **서버 → 엔진 타임아웃**: 엔진이 턴당 지연을 실측해 공유한 뒤 정한다.

쉽게 풀어 쓴 팀원용 안내: [guide.md](guide.md)
