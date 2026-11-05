# 데이터 구조의 DB 이전과 서버·UI 통합 방법

작성 2026-11-05. 대상: 이 엔진(resource_engine), scrap-server(FastAPI·SQLAlchemy·Alembic·PostgreSQL), scrap-web(React).
화면 쪽 대응과 합의 사항은 `docs/scrap-web-integration.md`.

## 1. 지금 데이터는 어디에 있나

| 종류 | 위치 | 성격 |
|---|---|---|
| 판정 규칙·사실 정의 | `rules/facts.yaml`, `rules/rules.yaml`, `rules/rules_s3.yaml` | 정적. 법령 원문을 옮긴 조건 + 인용문 + 판 + 검토 상태 |
| 법령 표 | `rules/annex4_codes*.yaml`(별표 4), `rules/annex43*.yaml`(별표 4의3), `rules/r_codes*.yaml`(별표 4의2), `rules/s5_rules.yaml`, `rules/reporting.yaml` | 정적. 판별 파일, 유효 기간은 `sources.yaml` |
| 연결표·카탈로그 | `rules/s4_map.yaml`(지정 사유→번호 범위), `rules/materials.yaml`(소재 98종), `rules/question_groups.yaml`, `rules/r_code_labels.yaml`, `rules/consult.yaml`, `rules/glossary.yaml` | 정적. 사람이 만든 표(UNVERIFIED) |
| 근거 원문 | `sources/raw/`(PDF·HTML), `rules/sources.yaml`(해시·판·유효 기간) | 정적 |
| 검증 자료 | `testdata/`(질의회신·판례 정답셋), `tests/data/material_tables.json`(소재별 판정표 기대값), `docs/material-tables/` | 정적 |
| 규칙 DB 버전 | 위 파일들의 해시 → `rule_db_version`(예: `rules-dcd311404bae`) | 결과마다 붙음 |
| 문진 상태 | 엔진 SQLite `.wastecalc/sessions.sqlite3` 한 표(`sessions(id, state JSON)`) — `state = {answers, history, needs_review, ui, as_of, rule_db_version, waste_id, …}` | 동적. 개발·시연용 |
| 사업장 공통 정보 | 브라우저 localStorage(`wastecalc:site-profile`) — 시험 화면에서만 | 동적 |
| 판정 기록 | 요청할 때 생성(`record.py`), 저장하지 않음 | 동적 |
| scrap-web 처리경로 상태 | 브라우저 localStorage(`scrap.treatment.v1.*`) | 동적(엔진 밖) |

## 2. DB로 옮길 것과 옮기지 않을 것

### 2.1 규칙·법령 표는 DB로 옮기지 않는다 (권장)

- 규칙은 **코드처럼 버전 관리**해야 한다. 조문 원문 대조 테스트, 소재별 판정표 회귀 테스트, 사람 검토 이력이 모두 파일·Git에 묶여 있다.
- 결과의 재현성은 `rule_db_version`(파일 해시)으로 보장한다. DB에는 이 문자열만 저장한다.
- 나중에 규칙 관리 화면이 필요해지면 그때 "파일 → DB 적재" 단방향 도구를 둔다(편집은 계속 파일에서).

### 2.2 서버 DB로 옮길 것 (scrap-server, Alembic 마이그레이션)

서버 관례(UUID 기본키, `TimestampMixin`, `company_id` 외래키, JSON 컬럼)를 따른다.

**classification_assessments** — 폐기물 하나의 분류 문진

| 컬럼 | 형식 | 내용 |
|---|---|---|
| id | UUID PK | |
| company_id | UUID FK companies | 기업 |
| waste_id | UUID FK(서버의 폐기물 표) 또는 문자열 | 화면의 폐기물 항목 |
| state | JSON | 엔진에 넘기는 그대로: `{answers, ui, needs_review}` |
| status | 문자열 | 엔진 `status`(NEED_INFO·NEED_TEST·NEED_EXPERT·DETERMINED) |
| phase | 문자열 | question / result |
| as_of | date | 판정 기준일 |
| rule_db_version | 문자열 | 마지막 판정에 쓴 규칙 버전 |
| contract | 문자열 | `classification-view-v1` |
| created_by, updated_by | UUID FK users | |

**classification_events** — 답 이력(되돌리기·감사)

| 컬럼 | 내용 |
|---|---|
| id, assessment_id, seq | 순번 |
| patch | JSON — 화면이 보낸 보기의 answers 그대로 |
| state_before | JSON — 되돌리기용 직전 state |
| actor_id, created_at | 누가 언제 |

**classification_records** — 결과 확정 시점의 판정 기록(변경 불가, 새로 판정하면 새 행)

| 컬럼 | 내용 |
|---|---|
| id, assessment_id | |
| record | JSON — `schemas/assessment_record.schema.json` v1 전체 |
| record_hash | 문자열 — 같은 입력·기준일·규칙 버전이면 같은 값 |
| waste_code, designated, provisional, trust_level | 검색·목록용으로 record에서 뽑은 값 |
| as_of, rule_db_version, engine_version | |

**기업 공통 사실** — `companies`에 컬럼 또는 별도 표 `company_site_facts(company_id, fact, value, source, confirmed_at)`
- 대상: `emission_facility`, `public_facility`, `waste_facility`, `designated_waste_emitted`, `reporting_shared`(엔진 `rules/question_groups.yaml`의 `site_facts`).
- 새 문진을 시작할 때 서버가 이 값을 `state.answers`에 넣어 보낸다(이미 확인한 사실은 다시 묻지 않음).

**증빙(다음 단계)** — 서버의 documents 도메인과 연결: 사실마다 `document_id`·문서 종류·날짜를 붙여 `source: DOCUMENT/TEST`로 넘긴다(계획서 5단계).

### 2.3 지금 상태 → 새 표 대응

| 지금 | 옮길 곳 |
|---|---|
| 엔진 SQLite `state.answers`, `ui`, `needs_review` | `classification_assessments.state` |
| `state.history` | `classification_events.state_before` |
| `state.as_of`, `rule_db_version`, `waste_id` | `classification_assessments` 같은 이름 |
| 브라우저 사업장 정보 | `company_site_facts` |
| `/record` 응답 | `classification_records.record` |

엔진 SQLite 세션은 개발·시연용으로 남기고, 운영에서는 쓰지 않는다.

## 3. 서버 통합

### 3.1 호출 구조

```
scrap-web ──/api/v1/…──▶ scrap-server ──HTTP(내부망)──▶ 분류 엔진(resource_engine)
  화면                    인증·기업·DB 저장              상태 없음: /api/classification/evaluate · apply · record
```

- 서버가 지금 scrap-ai를 부르는 방식(`app/domains/runs/engine_client.py`: httpx 클라이언트, 계약 버전, 실패 시 오류 코드)과 같은 모양으로 `ClassificationEngineClient`를 둔다.
- 설정: `CLASSIFICATION_ENGINE_URL`(비어 있으면 503으로 거절 — scrap-ai 설정과 같은 방식).
- 엔진은 외부에 공개하지 않는다(내부망). 인증은 서버가 한다.
- 엔진은 **상태를 갖지 않는다.** 서버가 저장한 `state`를 매번 보내고, 돌려받은 `state`를 저장한다.

### 3.2 서버 API 제안 (화면이 부르는 경로)

| 서버 경로 | 서버가 하는 일 | 엔진 호출 |
|---|---|---|
| `POST /api/v1/wastes/{waste_id}/classification` | assessment 만들기. 기업 공통 사실을 `state.answers`에 채움 | `POST /api/classification/evaluate {answers, ui:{}}` |
| `GET /api/v1/wastes/{waste_id}/classification` | 저장된 state로 다시 그리기(이어서 하기) | `evaluate` |
| `POST /api/v1/wastes/{waste_id}/classification/answer` `{answers}` | 이벤트 저장(직전 state 포함) → 새 state 저장 | `POST /api/classification/apply {state, patch}` |
| `POST /api/v1/wastes/{waste_id}/classification/undo` | 마지막 이벤트의 `state_before`로 되돌리기 | `evaluate` |
| (결과에 도달하면 서버가 자동) | 판정 기록 저장, 폐기물 목록의 상태·분류번호 갱신 | `POST /api/classification/record {state}` |
| `POST /api/v1/classification/extract` `{text}` | 설명 읽기 — scrap-ai(LLM)가 엔진 사실 목록 기준으로 값을 제안 | 엔진은 `GET /api/classification/facts`(목록)만 제공 |

- 서버는 응답 본문(`view`)을 해석하지 않고 화면으로 그대로 넘긴다. 단, 결과 단계에서 `view.result.code`·`provisional`·`treatment`는 폐기물 목록 갱신과 처리경로 연결에 쓴다.
- 기업 공통 사실이 문진 중에 답해지면(`state.answers`에 해당 키), 서버가 `company_site_facts`에도 반영한다.
- 되돌리기에서 화면 상태만 바뀐 경우(묶음 선택)는 엔진 `apply`의 `changed_facts: false` — 이벤트를 남기지 않아도 된다.

### 3.3 규칙이 바뀔 때

- 응답마다 `rule_db_version`이 온다. 저장된 값과 다르면 서버가 새 버전으로 다시 `evaluate`한다(엔진이 상태 없음이라 그대로 가능).
- 진행 중 문진: 다시 계산한 다음 질문으로 이어 간다.
- 저장된 판정 기록: 바꾸지 않는다(그때의 근거). 다시 판정해 결과가 달라지면 새 기록을 만들고 "규칙 개정으로 결과가 바뀌었다"를 알린다.

### 3.4 처리경로(scrap-ai)와의 연결

- 결과의 `view.result.treatment = {waste_code, material, material_label}`을 처리경로 시작 값으로 쓴다(지금 화면의 고정 `'51-03-01'` 대신).
- scrap-ai lot의 `designated_waste`는 판정 기록 `items.designated.value`에서 채운다.
- 잠정 결과(`provisional: true`)를 처리경로로 넘길지는 합의 사항(A7).

## 4. UI 통합

- 화면은 서버 경로(`/api/v1/wastes/{id}/classification…`)만 부른다(팀 규칙: 같은 출처 서버 API만).
- 로컬 개발에서 서버 없이 시험하려면 Vite 프록시로 엔진의 세션 API(`/api/classification/sessions…`)를 직접 써도 된다. 응답 모양은 같다(`session_id` 등 몇 필드만 다름).
- 화면 수정 목록(U1~U6)과 응답 필드 대응표는 `docs/scrap-web-integration.md` 1·2절.

## 5. 진행 순서와 담당

| 순서 | 할 일 | 담당 |
|---|---|---|
| 1 | 엔진 서비스 실행 방법 고정(`uvicorn wastecalc.web.app:app`, Dockerfile) | 엔진 |
| 2 | 서버: `ClassificationEngineClient`, 설정, 위 3개 표 Alembic 마이그레이션, 3.2 경로 | 서버 |
| 3 | 화면: U1(데이터 연결) → U3·U4(처리경로 넘김) → U6(데이터) | 웹 |
| 4 | 화면: U2(번호 없는 결과) 디자인 후 구현, U5 | 디자인·웹 |
| 5 | 기업 공통 사실을 온보딩·기업 정보와 연결(A5) | 서버·웹 |
| 6 | 통합 시험: 대표 소재(PP·고철·폐유·오니·분진)로 화면→서버→엔진→기록 저장 확인 | 전원 |

## 6. 주의할 점

- 엔진의 모든 규칙은 사람 검토 전이다. 결과는 `provisional: true`로 나가며, 판정 기록에는 항목별 신뢰 수준과 그 이유가 있다. 이후 단계는 판정 기록의 `use_rule`("DETERMINED이고 신뢰 기준 이상인 항목만 자동으로 쓴다")을 따른다.
- 숫자 질문은 구간 보기로 답하므로 실제 측정값이 기록되지 않는다(`range_answers`에 구간만). 증빙이 필요한 단계에서는 숫자 입력 UI가 필요하다(A3).
- 응답 형식 버전은 `contract: classification-view-v1`. 필드를 빼거나 뜻을 바꾸면 버전을 올린다(추가는 같은 버전).
