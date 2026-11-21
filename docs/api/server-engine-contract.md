# scrap-server ↔ 문진 엔진 내부 API (v2)

서버가 엔진을 부를 때의 규약이다. 경로·응답 모양은 v1(기존 엔진)과 맞췄다. 그래서 서버의 중계 코드(`backend/app/domains/diagnosis/`)와 웹의 `normalize.js`는 고치지 않아도 된다. 웹의 재질 필터(`supportedMaterials.js`)는 v2 값(pp·pe·pet·aluminium)으로 바꿨다(scrap-web `feat/diagnosis-v2-materials`). 달라진 점은 6절에 모았다.

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
| `GET /cases/{id}` | | `{case, latest_turn, conversation, verdicts, current_verdict, documents, handoff, recycling}` |
| `POST /cases/{id}/diagnosis/messages` | `{text}` 또는 `{quick_reply}` (+ 선택 `confirmed_facts`, `company_profile_version`) | `TurnResponse` |
| `POST /cases/{id}/documents` | multipart: `file`, 선택 `facts`(JSON 문자열) | 201 `{document, turn, values}` |
| `POST /cases/{id}/documents/{doc}/versions` | multipart(위와 같음) | 201 `{document, turn, values}` |
| `POST /cases/{id}/documents/{doc}/values/apply` | `{values: [{value_id?, fact_key?, value?, unit?, document_version, reviewer, reviewed_at, reject?}]}` | `TurnResponse` |
| `POST /cases/{id}/documents/{doc}/revoke` | `{reason?, document_version?}` | `TurnResponse` |
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
| `retract` | 사실 키 | 답을 지우고 아직 묻지 않은 상태로 되돌린다. 웹 판정 보드는 2026-11-21부터 쓰지 않는다(고치기 하나로 합침, 기본값 사실에서는 기본값이 다시 채워짐). API 호환을 위해 남긴다 |

- 값 형식이 틀리면 422 `VALIDATION_ERROR`이고, `details.problems[{key, value, reason}]`에 이유가 담긴다.
- `text`(자유 문장)는 말 이해 흐름으로 처리한다(LLM이 켜져 있을 때, 4-2절). 꺼져 있으면 대화에 남기고 버튼 답을 안내한다. 서류 요청 단계의 `서류가 없어요`(웹 서류 카드의 버튼)는 AI 없이 요청한 서류 사실을 '모름'으로 둔다.
- 확인 카드(`sub_branch: CONFIRM_GUESS`)의 키는 `confirm:사실`이다. `kind: value`는 그 값으로 기록(예), `expand`는 원래 질문으로(아니요), `unknown`은 모름.
- 묶음 확인(`sub_branch: CONFIRM_GROUP`)은 일반 묶음 카드와 키·선택지가 같고 `text`만 "'말한 문장'라고 하셨어요. 그럼 아래 항목이 모두 해당 없는 게 맞나요?"로 바뀐다. 답도 묶음 질문과 같다(`none_all`·`expand`·`some`).
- 확인 카드(`CONFIRM_GUESS`·`CONFIRM_GROUP`)에 `text`로 짧게 "응·네·맞아요"(묶음 확인은 "없어요"도)라고 하면 AI 없이 '예' 버튼으로, "아니·아뇨"(묶음 확인은 "있어요·모르겠어요"도)라고 하면 '아니요' 버튼으로 처리한다. 긴 문장은 추출 AI로 보내고, 묶음 확인에서 AI가 '모두 해당 없음'을 내면 다시 묻지 않고 그대로 기록한다.
- 서류로만 받는 사실(지금은 `oil_pct_evidenced`)에 `kind: value`를 보내면 422다(`reason: 서류로만 받는 값`). `unknown`은 받는다.

## 4. 턴 응답 (`TurnResponse`)

```json
{
  "turn_id": "…", "case_id": "…", "branch": "ASK_FACT | REQUEST_EVIDENCE | FINAL_REVIEW | UNSUPPORTED",
  "message": "…", "assist": null, "kb_version": "…",
  "verdict": {"outcome", "waste_code", "waste_name", "category", "flags", "blocking_facts", "rule_id", "rationale", "review"},
  "ui": {"question", "board", "result", "can_confirm", "suggested_replies": [], "requested_documents": [], "conflicts": []}
}
```

- `ASK_FACT`: 질문이 남아 있다. `ui.question`에 질문 카드가 온다.
  - `input`은 `choice`·`number`·`group` 중 하나다.
  - `options[]`의 `kind`는 `value`·`unknown`·`none_all`·`expand` 중 하나다.
  - 묶음 질문이면 `items`와 `answered_items`가 함께 온다. 펼친 묶음의 항목에는 `group` 필드가 붙는다.
- `REQUEST_EVIDENCE`: 질문 대신 서류가 필요하다(기름이 묻은 경우의 기름성분 함량). `ui.question`은 null이고 `ui.requested_documents[{evidence_type, label, facts, fact_labels}]`(= `ui.board.documents_needed`)가 온다. 건 상태는 `NEEDS_INFO`다.
- `FINAL_REVIEW`: 결론이 났다. `ui.result`가 오고 `can_confirm`은 true다.
- `UNSUPPORTED`: '모름' 답 때문에 결론을 낼 수 없다. 건 상태는 `NEEDS_INFO`가 되고, `ui.board.pending`에 막힌 사실이 온다. 판정 보드에서 그 답을 고치면 이어서 진행한다.
- 판정 보드 고치기: `ui.board.facts[].edit.options[]`는 `{label, value, kind}`이고 `kind`는 `value` 또는 `unknown`(모름)이다. 고른 선택지의 `kind`·`value`를 그대로 `quick_reply`로 보낸다. 서류로만 받는 사실은 `editable: false`다. 캔 순환자원 묶음 항목을 고치면 같은 묶음에서 '모름'인 항목을 지우고 묶음을 다시 묻는다('아니요' 한 번이 모든 항목을 모름으로 기록하기 때문).
- 판정 보드 `ui.board.facts[].source_type`은 여섯 가지다: `UTTERANCE`(답함), `SCREENING`(묶음 답), `PROFILE`(회사 정보 기억), `PROFILE_CONFIRMED`(서버가 확인해 보낸 값), `DOCUMENT`(검수한 서류 값, `status: EVIDENCED`, 고칠 수 없음), `DERIVED`(자동으로 채움).

## 4-2. 말 이해와 질의응답 (LLM)

판정과 '무엇을 물을지'는 코드가 정한다. LLM은 제안·설명·문장 다듬기만 한다.

1. **가리기**: AI로 보내기 전에 전화·이메일·사업자번호·주소를 토큰으로 바꾼다. 가린 뒤에도 남으면 보내지 않는다.
2. **추출 AI**(한 턴에 1회): 의도(답 / 질문 / 무관 / 서류 없음 / 불명확)와 사실 후보 `[{key, value, certainty, quote}]`를 낸다.
3. **검사기**(코드): 카탈로그 값인지, 근거 문구(`quote`)가 실제 말에 있는지, 서류로만 받는 사실이 아닌지 본다. 통과한 단정 답은 바로 기록한다(`source_type: UTTERANCE`, 보드 `quote`).
4. **확인 카드**: 추측한 답("아마 PP일걸요")은 바로 쓰지 않고 다음 턴에 `[예, 값] [아니요] [모름]` 카드로 묻는다(`sub_branch: CONFIRM_GUESS`). 말로 한 오염 '없음'(지정폐기물 가능성을 지우는 답)이나 오염 묶음의 '모두 해당 없음'은 항목마다 따로 묻지 않는다. 오염 묶음 차례에 남은 항목 전체를 묶음 확인 한 번으로 묻는다(`sub_branch: CONFIRM_GROUP`). 메모에서 미리 말했으면 앞 질문을 막지 않고 그 차례까지 기다린다. Trace `UNDERSTAND`의 `confirm`·`confirm_values`에는 묶음 확인으로 미룬 사실도 들어가고, `group_confirm`에 묶음 id가 남는다.
5. **건 메모**(`POST /cases`의 `memo`)도 같은 흐름으로 읽어, 이미 말한 질문을 건너뛴다.
6. **질의응답 agent**: 문진에 관한 질문이면 LLM이 읽기 전용 도구(`rule_basis`, `search_law`, `lookup_term`, `case_state`)를 골라 최대 3번 쓰고 답한다. 출처는 도구가 돌려준 조문만 남긴다(코드 대조). 응답은 턴의 `assist` `{intent, text, sources[{id, type, ref, excerpt}], terms[{term, plain, example}], review}`이고 대화 기록에도 남는다. 판정·질문 카드는 바뀌지 않는다. 문진과 무관한 요청은 답하지 않고 안내한다.
7. **질문 문장 다듬기**: 턴 `message`만 쉬운 말로 바꾼다. `ui.question.text`(카드 문장)와 선택지는 고정이다. 원문에 없는 숫자가 생기면 버린다.

Trace에는 AI 호출마다 `LLM` 행(모델, 지연, 사용량, 가린 프롬프트의 해시·길이. 원문은 `TRACE_STORE_PROMPTS=true`일 때만)과 `UNDERSTAND`(받은·확인·버린 값과 이유), `ASSIST`(쓴 도구) 행이 남는다.

## 4-1. 서류: 업로드 → 검수 → 적용

엔진은 서류 원문과 값을 대조하지 않는다. **검수가 끝난 값만 판정에 쓴다.** 원문 파일은 저장하지 않는다(이름·형식·크기·SHA-256과 자동 읽기 요약만).

1. **업로드** `POST …/documents`: 받는 형식은 PDF·사진·txt·md다. 사진은 OCR이 켜져 있을 때만 받고, 아니면 415 `UNSUPPORTED_DOCUMENT`다. 크기가 상한(`MAX_UPLOAD_BYTES`, 기본 10MB)을 넘으면 413이다.
   - 값은 모두 `UNVERIFIED` 후보로만 저장한다. 판정은 바뀌지 않는다.
   - `facts`로 직접 적은 값과 표 자동 읽기 값이 후보가 된다. 형식이 틀리면 422 `details.problems[{key, value, reason}]`다. 서류로 받지 않는 사실, 단위 불일치, 숫자 칸의 글자가 여기에 해당한다.
   - 표 자동 읽기:
     - 글자 있는 PDF는 엔진 안(pdfplumber)에서 읽는다.
     - 스캔본·사진은 `ALLOW_DOCUMENT_OCR=true`와 Azure 키가 있을 때만 Azure Document Intelligence로 읽는다.
     - 읽은 위치와 탈락 사유는 `document.extracted_facts.table_read`(`backend, source, route, items[{key, status, value_raw, unit_raw, page, quote, cell_ref, note, guard_reasons?}], not_found, warnings, errors`)에 담긴다. `key`는 엔진 사실 키다.
   - 불검출과 `<0.5` 같은 값은 구간 `{hi, hi_inc}`다. 판정은 구간 전체가 조건을 만족하면 참, 전혀 만족하지 않으면 거짓, 걸치면 모름으로 본다.
2. **적용** `…/values/apply`: 서버가 검수 결과를 보낸다.
   - `value_id`에 `value`를 빼면 후보 값을 그대로 쓰고, `value`를 주면 고친 값으로 쓴다.
   - `fact_key`만 주면 새 값을 만든다. `reject: true`는 `REJECTED`다.
   - 적용한 값은 사실 이력에 `EVIDENCED`, `source_type: DOCUMENT`, `source_ref: "문서id@v버전"`으로 들어가고, 다시 판정한 `TurnResponse`를 돌려준다.
   - `document_version`이 지금 버전과 다르면 409 `DOCUMENT_VERSION_MISMATCH`(`details: {document_id, current_version, sent_versions}`)다.
3. **파일 교체** `…/versions`: 버전이 1 오르고, 이전 버전의 적용 값과 대기 후보는 `REVOKED`가 된다. 그 서류에서 온 사실은 철회돼 다시 서류 요청으로 돌아간다.
4. **효력 해제** `…/revoke`: 그 서류(버전)의 적용 값을 `REVOKED`로 두고, 거기서 온 유효 사실을 철회한다.

값 상태: `UNVERIFIED` → `APPLIED` | `REJECTED`, `APPLIED` → `REVOKED`. 인계 객체의 `evidence[{fact, document_id}]`에 서류로 확인한 사실이 담긴다.

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
- 그 밖의 필드: `basis[{id, type, unit, ref, excerpt, rule_id}]`, `kb`, `inputs`, `flags`, `rule_id`, `evidence: []`, `designated: null`, `recycling`(아래)
- `facts`는 값이 정해진 사실만 담는다. 형식은 `{"material": {"value": "pp", "status": "CLAIMED", "source_type": "UTTERANCE"}}`이고, 묶음 항목은 `can_designation.registered`처럼 점으로 이은 키다.
- **형태(`input_form`)를 문진에서 묻고 인계 객체에 넣는다.** 서버의 `inherited_form()`은 이 값을 바로 쓴다. 그래서 경로 화면에서 형태를 다시 묻지 않는다.
- `physical_state`는 형태에서 자동으로 채운다(`DERIVED`, 값 `solid`).
- `review`는 항상 `UNVERIFIED`다(전문가 검토 전).
- `OUT_OF_SCOPE`는 후보 코드가 있어도 `waste_code`를 null로 둔다.

재활용 유형(`recycling`, `recycling-types-v1`)
- 시행규칙 별표 4의3(폐기물의 종류별 재활용 가능 유형)을 법령 API로 받아 분류번호 행을 읽은 값이다. 분류 판정이나 업체 허가 확인이 아니다(`facility_permit_verified: false`).
- `status`: `table_listed`(표에 있음, `types{free, analysis, unmarked}`·`source`·`notes`·`version`·`checksum`을 채움) / `not_applicable`(업체 추천 대상 결과가 아님) / `not_covered`(표에 행이 없음) / `out_of_date`(문진 기준일이 별표 시행일보다 앞섬)
- `free`는 사전 분석·확인 "해당 없음", `analysis`는 "해당"인 유형이다. `pages`는 API 본문에서 읽어 비어 있다.
- `case_id`·`verdict_version`·`waste_code`·`as_of`로 판정과 묶는다. 건 상세의 최상위 `recycling`은 현재 확정 판정의 값과 같다.

## 6. v1과 달라진 점

- **재질 값이 바뀌었다**: `pp`·`pe`·`pet`·`pvc`·`other_resin`·`synthetic_rubber`·`aluminium`·`steel`·`other`. v1의 `metal_can`·`plastic_packaging` 같은 값은 없다. 포장재 여부는 별도 사실 `packaging_used`로 묻는다.
- **결과 값이 더해졌다**: outcome·category에 `DESIGNATED_POSSIBLE`. v1의 `INTERPRETATION_NEEDED`·`CODE_NEEDS_TEST`·`NO_GENERAL_CODE` 등은 나오지 않는다.
- **서류**: 경로와 응답 모양은 v1과 같다. v2에서 서류로 받는 사실은 기름성분 함량 하나다. 그래서 자동 읽기도 그 항목만 후보로 만든다(다른 시험 항목은 `table_read`에서 빠진다).
- **회사 정보 기억**: 사업장 질문(`emission_facility`, `daily_avg_kg`, `public_facility`, `construction_5t`, `site_emits_designated`)의 답은 기업별로 기억한다. 같은 기업의 다음 건에는 `PROFILE`로 미리 채운다. 회사 정보는 고정값이라, 기억이 없을 때 건의 첫 답만 기억하고 판정 보드의 고치기·되돌리기는 그 건의 판정만 바꾼다(기억을 바꾸거나 지우지 않음). 기업 데이터를 삭제하면 이 기억도 함께 지운다.
- **재활용 유형표**: v1은 별표 PDF에서 손으로 옮긴 표였고, v2는 법령 API에서 받는다. 지금 범위는 51-03-01·51-03-07·51-29-03 세 행이다.
- **DB 스키마가 새로 바뀌었다**: 마이그레이션은 `alembic/versions/0001`부터 다시 시작한다(0002: 서류·서류 값, 0003: 말 답 근거 문구·확인 대기·assist). v1 엔진이 쓰던 DB에는 그대로 올릴 수 없으므로 새 데이터베이스를 쓴다.
