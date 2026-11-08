# M4 결과 보고: API·영속화·상태 전이·문서·confirm/reopen·Trace

측정일 2026-11-08. 완료 조건(md 14절): 응답 스키마 계약 테스트 통과 — `tests/test_api.py`.

## 구성
- `app/main.py`: `create_app(settings, kb=, kb_dir=, extractor_llm=, responder_llm=, engine=, today=)`. 모듈의 `app`은 KB·DB를 처음 쓸 때(또는 시작 시) 한 번 만든다. 실행 `uv run uvicorn app.main:app --port 8030`.
- `app/api/deps.py`: 앱 상태(KB 1회 로드, KB 지문 `kb_version`, LLM, DB 엔진)와 의존성. 테스트는 인자나 `dependency_overrides`로 SAMPLE KB·FakeLLM·임시 SQLite를 넣는다.
- `app/api/service.py`: 상태 전이·영속화. `routes.py`는 HTTP만. `documents.py`: .txt/.md(UTF-8/CP949), PDF(pypdf 텍스트 층).
- `app/persistence/`: SQLAlchemy 2.x 모델, 저장소(요청마다 DB 행에서 `DiagnosisSession`을 다시 만든다 — 서버는 상태를 들고 있지 않음), 불변 Trace 보호.
- `app/agent/orchestrator.py`: `export_state()`/`to_state()`/`from_state()`(직렬화), `peek()`(사실을 바꾸지 않는 재평가). 기존 동작은 그대로다.
- `alembic/`: 초기 마이그레이션 `0001`. 테스트에서 모델과 차이가 없음을 확인한다(`compare_metadata`).

## 엔드포인트
md 11절 8개 + 개발용 기업 API(`POST /companies`, `GET /companies/me`, `PUT /companies/me/profile`), `GET /health`. 표는 README의 M4 절.
- 오류: 다른 기업의 건 404, 헤더 없음·모르는 기업 401, 확정 불가·상태 위반 409, 잘못된 문서 사실 422, 지원하지 않는 형식 415, 10MB 초과 413, 같은 세션에 동시 쓰기 409(낙관적 잠금).

## 테이블
| 테이블 | 내용 |
|---|---|
| `companies` / `users` | 기업(profile JSON, `facts`는 PROFILE 사실로 들어감) / 계정(최소) |
| `waste_cases` | memo·quantity·unit·period·status |
| `diagnosis_sessions` | as_of, kb_dir, kb_version(규칙 파일 해시), table_versions, state JSON(SessionState·last_question·messages), fact_count·trace_count, revision(낙관적 잠금) |
| `fact_records` | 사실 이력(append-only, `(session_id, seq)` 유일). 키·값만 저장하고 특정 키에 의존하지 않는다 |
| `documents` | filename, content_type, size, sha256, extracted_text, extracted_facts(method·accepted·rejected) |
| `verdicts` | 판정 버전(code·name·category·rule_ids·table_id/version·kb_version·as_of·facts_snapshot·verdict JSON, confirmed_at, superseded_at) |
| `trace_turns` | kind(TURN/DOCUMENT/CONFIRM/REOPEN), payload JSON, immutable |

## 상태 전이
- 문진 턴: 라우터 `next_status` 그대로. ASK_FACT·RESOLVE_CONFLICT·FINAL_REVIEW → `DIAGNOSING`, REQUEST_EVIDENCE·UNSUPPORTED → `NEEDS_INFO`. `NEEDS_INFO` 건도 메시지·문서를 받아 다시 `DIAGNOSING`이 될 수 있다.
- confirm: 서버가 `peek()`로 다시 평가해 `can_confirm`이고 FINAL_REVIEW일 때만. 선택 `expected_code`가 서버 판정과 다르면 409. 판정 버전 +1, 그 세션의 Trace 행을 모두 immutable로(ORM 수정·삭제 시 `ImmutableTraceError`) → `CODE_CONFIRMED`. 확정 뒤 메시지·업로드는 409.
- reopen: `CODE_CONFIRMED`에서만. 현재 판정에 superseded_at을 채우고(지우지 않음) REOPEN Trace를 남긴 뒤, 같은 사실로 한 턴을 돌려 응답한다 → `DIAGNOSING`.
- 문서: LLM이 있으면 extractor + guard → 값이 있는 CLAIMED만 EVIDENCED(source DOCUMENT, ref=문서 id, quote 유지)로. LLM이 없으면 폼 필드 `facts`(JSON) 사용. DOCUMENT Trace에 원본 LLM 호출·버린 사실을 남긴다.

## 테스트
- `uv run pytest`: **274 passed** (기존 252 + M4 22). `ruff check`·`ruff format --check` 통과.
- 주요 항목: md 10절 응답 계약, 메모 추출·프로필 시드, 상태 전이·목록 필터, UNSUPPORTED→NEEDS_INFO→복귀, 문서 LLM 추출→EVIDENCED→FINAL_REVIEW(txt·PDF), 문서 오류(422/415), confirm 409·성공(버전·스냅샷·Trace 불변·ORM 변경 차단), reopen(409·버전 보존·재확정 v2), 기업 격리, 앱을 새로 띄운 뒤 이어서 진행해도 메모리 세션과 응답이 같음(last_question 복원 포함), 동시 쓰기 충돌, Alembic upgrade/downgrade·모델 일치, 실제 KB 기동(질문 키는 고정하지 않음).
- 스모크: `uvicorn app.main:app --port 8030`(data/real 97개 테이블, LLM off) — health, 건 생성, 선택지 6턴 → FINAL_REVIEW, 목록·상세, confirm 200, 확정 후 업로드 409, trace 8행, 격리 401, reopen 200.

## TODO·결정 필요
- 인증·권한: `X-Company-Id`는 임시다. 로그인 토큰·계정 역할로 바꿔야 한다. `/companies`는 지금 열려 있다.
- `as_of`: 세션을 만든 날로 고정한다(재현성). 오래 이어지는 세션이나 reopen 때 오늘 날짜로 바꿀지 정해야 한다.
- 문서 추출은 대화용 extractor 프롬프트를 그대로 쓴다. 성적서 전용 프롬프트·표 파싱·스캔 PDF OCR은 아직 없다. 원본 파일 바이트는 저장하지 않는다(해시·텍스트만).
- `IN_TRANSIT`·`COMPLETED` 전이는 범위 밖이다(갱신 주체 미정).
- 확정은 FINAL_REVIEW(코드가 있는 결론)일 때만 된다. 코드 없는 결론(폐기물 아님 등)을 '확정'할지 정해야 한다.
- 메시지는 세션 state JSON에 쌓인다. 길어지면 별도 테이블로 뺀다.
