# scrap-server ↔ 문진 엔진 내부 API (v2)

서버가 엔진을 부를 때의 규약이다. 경로·응답 모양은 v1(기존 엔진)과 맞췄다. 그래서 서버의 중계 코드(`backend/app/domains/diagnosis/`)와 웹의 `normalize.js`는 고치지 않아도 된다. 다만 웹의 재질 필터(`supportedMaterials.js`)는 v1 재질 값만 남기기 때문에, 새 값에 맞춰 고쳐야 한다(6절). 달라진 점은 6절에 모았다.

## 1. 기본

- 경로 앞에 `/internal/v1`를 붙인다. 엔진 포트는 8030이다. 브라우저는 엔진을 직접 부르지 않는다.
- 인증 헤더는 두 개다.
  - `Authorization: Bearer <ENGINE_SERVICE_TOKEN>`
  - `X-Company-Id: <서버가 인증한 기업 ID>`
- 처음 보는 기업 ID는 엔진이 자동으로 만든다. 다른 기업의 건을 부르면 404 `CASE_NOT_FOUND`다.
- 토큰을 정하지 않은 경우: `APP_ENV=dev`면 토큰 없이 통과하고, `prod`면 모든 요청이 401 `AUTH_REQUIRED`다.
- 오류 형식은 `{"detail": {"code", "message", "details"}}`다. 분기는 `code`로 한다.

## 2. 엔드포인트

| 메서드·경로 | 본문 | 성공 |
|---|---|---|
| `POST /cases` | `{memo?, quantity?, unit?, period?, confirmed_facts?, company_profile_version?}` | 201 `{case, turn}` |
| `GET /cases?status=&page=&size=` | | `{items, pagingInfo}` (최근 갱신순) |
| `GET /cases/{id}` | | `{case, latest_turn, conversation, verdicts, current_verdict, documents: [], handoff, recycling: null}` |
| `POST /cases/{id}/diagnosis/messages` | `{text}` 또는 `{quick_reply}` (+ 선택 `confirmed_facts`, `company_profile_version`) | `TurnResponse` |
| `POST /cases/{id}/confirm` | `{expected_code?}` | `{case, verdict, handoff, frozen_trace_rows}` |
| `POST /cases/{id}/reopen` | `{reason?}` | `{case, superseded_verdict, turn}` |
| `POST /cases/{id}/rebase` | 없음 | `TurnResponse` |
| `GET /cases/{id}/trace` | | `{case_id, kb_version, facts, events, verdicts}` |
| `GET /catalog/facts` | | `[{key, label, type, unit, values, parent}]` |
| `DELETE /companies/{external_id}/data` | | `{company_hash, status, counts, attempts, error, started_at, finished_at}` (멱등) |
| `GET /companies/{external_id}/data/deletion` | | 위와 같음, 이력이 없으면 404 `DELETION_NOT_FOUND` |
| `GET /health` (접두어 없음) | | `{status, kb_version}` |

## 3. 답 보내기: `quick_reply`

| `kind` | `key` | 뜻 |
|---|---|---|
| `value` | 사실 키(예: `material`) | `value`로 답한다. 판정 보드에서 고칠 때도 같다 |
| `unknown` | 사실 키 | 모른다고 답한다 |
| `none_all` | 묶음 질문 키(예: `Q-CONTAMINATION`) | 묶음의 모든 항목이 해당 없음. 캔 순환자원 묶음(`Q-CAN-CIRCULAR`)에서는 "모두 마쳤어요"다 |
| `expand` | 묶음 질문 키 | 해당하는 것이 있거나 모른다. 다음 턴부터 항목을 하나씩 단일 질문으로 묻는다. 캔 순환자원 묶음에서는 "하나라도 안 했거나 모름"으로 끝나고 항목별로 묻지 않는다 |
| `retract` | 사실 키 | 답을 지우고 아직 묻지 않은 상태로 되돌린다 |

- 값 형식이 틀리면 422 `VALIDATION_ERROR`이고, `details.problems[{key, value, reason}]`에 이유가 담긴다.
- `text`(자유 문장)는 아직 이해하지 못한다. 대화에 남기고, 같은 질문을 버튼으로 답해 달라고 안내한다.

## 4. 턴 응답 (`TurnResponse`)

```json
{
  "turn_id": "…", "case_id": "…", "branch": "ASK_FACT | FINAL_REVIEW | UNSUPPORTED",
  "message": "…", "assist": null, "kb_version": "…",
  "verdict": {"outcome", "waste_code", "waste_name", "category", "flags", "blocking_facts", "rule_id", "rationale", "review"},
  "ui": {"question", "board", "result", "can_confirm", "suggested_replies": [], "requested_documents": [], "conflicts": []}
}
```

- `ASK_FACT`: 질문이 남아 있다. `ui.question`에 질문 카드가 온다.
  - `input`은 `choice`·`number`·`group` 중 하나다.
  - `options[]`의 `kind`는 `value`·`unknown`·`none_all`·`expand` 중 하나다.
  - 묶음 질문이면 `items`와 `answered_items`가 함께 온다. 펼친 묶음의 항목에는 `group` 필드가 붙는다.
- `FINAL_REVIEW`: 결론이 났다. `ui.result`가 오고 `can_confirm`은 true다.
- `UNSUPPORTED`: '모름' 답 때문에 결론을 낼 수 없다. 건 상태는 `NEEDS_INFO`가 되고, `ui.board.pending`에 막힌 사실이 온다. 판정 보드에서 그 답을 고치면 이어서 진행한다.
- 판정 보드 `ui.board.facts[].source_type`은 다섯 가지다: `UTTERANCE`(답함), `SCREENING`(묶음 답), `PROFILE`(회사 정보 기억), `PROFILE_CONFIRMED`(서버가 확인해 보낸 값), `DERIVED`(자동으로 채움).

## 5. 확정과 인계 객체 (`diagnosis-handoff-v1`)

확정할 때 서버가 지금 사실로 판정을 다시 계산한다. 결론이 나지 않았으면 409 `NOT_CONFIRMABLE`이다. `expected_code`가 다시 계산한 결론과 다르면 409 `CODE_MISMATCH`다. 비교 대상은 분류번호가 있으면 번호, 없으면 outcome이다.

| outcome | result_type | category | route_guidance.action |
|---|---|---|---|
| `GENERAL` (분류번호 있음) | WASTE_CODE | GENERAL | RECOMMEND_ROUTE |
| `NOT_WASTE` | NO_CODE | null | NO_ROUTE_NEEDED |
| `CIRCULAR_RESOURCE` | NO_CODE | null | NO_ROUTE_NEEDED |
| `EXCLUDED` | NO_CODE | null | REFER_OTHER_LAW |
| `HOUSEHOLD` | NO_CODE | null | REFER_MUNICIPALITY |
| `DESIGNATED_POSSIBLE` (새 값) | NO_CODE | DESIGNATED_POSSIBLE (새 값) | NEEDS_TEST |
| `OUT_OF_SCOPE` | NO_CODE | OUT_OF_SCOPE | MANUAL_CLASSIFICATION |

인계 객체 필드
- 서버가 읽는 필드: `contract`, `case_id`, `verdict_version`, `result_type`, `waste_code`, `waste_name`, `category`, `outcome`, `route_guidance{action, summary, notes}`, `facts`, `review`, `timestamps{diagnosis_started_at, confirmed_at, as_of}`, `assumptions`
- 그 밖의 필드: `basis[{id, type, unit, ref, excerpt, rule_id}]`, `kb`, `inputs`, `flags`, `rule_id`, `evidence: []`, `designated: null`
- `facts`는 값이 정해진 사실만 담는다. 형식은 `{"material": {"value": "pp", "status": "CLAIMED", "source_type": "UTTERANCE"}}`이고, 묶음 항목은 `can_designation.registered`처럼 점으로 이은 키다.
- **형태(`input_form`)를 문진에서 묻고 인계 객체에 넣는다.** 서버의 `inherited_form()`은 이 값을 바로 쓴다. 그래서 경로 화면에서 형태를 다시 묻지 않는다.
- `physical_state`는 형태에서 자동으로 채운다(`DERIVED`, 값 `solid`).
- `review`는 항상 `UNVERIFIED`다(전문가 검토 전).
- `OUT_OF_SCOPE`는 후보 코드가 있어도 `waste_code`를 null로 둔다.

## 6. v1과 달라진 점

- **재질 값이 바뀌었다**: `pp`·`pe`·`pet`·`pvc`·`other_resin`·`synthetic_rubber`·`aluminium`·`steel`·`other`. v1의 `metal_can`·`plastic_packaging` 같은 값은 없다. 포장재 여부는 별도 사실 `packaging_used`로 묻는다.
- **결과 값이 더해졌다**: outcome·category에 `DESIGNATED_POSSIBLE`. v1의 `INTERPRETATION_NEEDED`·`CODE_NEEDS_TEST`·`NO_GENERAL_CODE` 등은 나오지 않는다.
- **없는 경로**: 서류 업로드·교체·값 적용·효력 해제(`/documents/...`)는 404 `NOT_FOUND`다. 기름 함량은 질문(`oil_pct_evidenced`, 분석성적서 수치)으로 받는다.
- **회사 정보 기억**: 사업장 질문(`emission_facility`, `daily_avg_kg`, `public_facility`, `construction_5t`, `site_emits_designated`)의 답은 기업별로 기억한다. 같은 기업의 다음 건에는 `PROFILE`로 미리 채운다. 기업 데이터를 삭제하면 이 기억도 함께 지운다.
- **재활용 유형표**: `recycling`은 아직 null이다. 서버는 이 값이 없으면 "R코드 미확인" 경고만 붙이고 계속 진행한다.
- **DB 스키마가 새로 바뀌었다**: 마이그레이션은 `alembic/versions/0001`부터 다시 시작한다. v1 엔진이 쓰던 DB에는 그대로 올릴 수 없으므로 새 데이터베이스를 쓴다.
