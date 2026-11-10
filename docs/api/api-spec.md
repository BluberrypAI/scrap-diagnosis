# 폐기물 진단 API 명세

백엔드(FastAPI)와 화면·경로추천·로그인 담당이 함께 보는 단일 기준 문서다. 필드 단위 정의는 자동 생성 명세 `docs/api/openapi.json`(`uv run python scripts/export_openapi.py`로 갱신, 테스트가 최신 여부를 검사)이 기준이고, 이 문서는 흐름·규칙·예시를 설명한다. 화면용 필드의 세부 형식은 `docs/ui/ui-contract.md`다.

## 1. 계약 버전

| 계약 | 버전 | 문서 | 어디에 나오나 |
|---|---|---|---|
| 화면용 보강 | `ui-v1` | `docs/ui/ui-contract.md` | `TurnResponse.ui`(question·board·conflicts·result), `CaseDetail.conversation`, `CaseOut.summary`, 기업 profile, `/catalog/facts` |
| 진단 인계 | `diagnosis-handoff-v1` | `docs/handoff-contract.md` | `POST /cases/{id}/confirm`의 `handoff`, `GET /cases/{id}`의 `handoff`, 판정의 `handoff` |
| 서류 읽기 | `document-extraction-v1` | `docs/document-extraction-contract.md` | 서류에서 뽑은 값 → 사실(`DOCUMENT` 출처), 업로드 응답의 `document.extracted_facts` |

형식을 바꾸면 해당 계약 문서와 이 문서, `openapi.json`을 함께 고친다. 기존 필드는 지우거나 뜻을 바꾸지 않고 추가만 한다.

## 2. 인증

- **scrap-server → 엔진:** `/internal/v1/...` 경로에 `Authorization: Bearer <ENGINE_SERVICE_TOKEN>` + 서버가 인증한 `X-Company-Id`를 보낸다. 경로·인증·오류 코드·페이징은 **`docs/api/server-engine-contract.md`**가 기준이다.
- **참조 화면·개발용(루트 경로, 이 문서의 3절 이하 표기):** `X-Company-Id: <개발용 기업 id>` 헤더만 쓴다. 없거나 모르는 기업이면 401. `APP_ENV=prod`에서는 막힌다.
- 인증 없이 부르는 API: `GET /health`, `POST /companies`(개발용 가입, prod 404), `GET /companies/profile-options`, `GET /catalog/facts`.
- 다른 기업의 건은 404로 보인다(존재 여부를 알려 주지 않는다).

## 3. 엔드포인트

| 메서드·경로 | 인증 | 설명 | 성공 | 주요 오류 |
|---|---|---|---|---|
| `GET /health` | - | 상태·KB 버전 | 200 | - |
| `POST /companies` | - | 기업 만들기(개발용) `{name, profile}` | 201 `CompanyOut` | 422 |
| `GET /companies/me` | O | 내 기업 | 200 `CompanyOut` | 401 |
| `PUT /companies/me/profile` | O | 기업 정보 저장 `{profile}`. 이후 새로 만드는 건부터 적용 | 200 `CompanyOut` | 401, 422 |
| `GET /companies/profile-options` | - | 기업 정보 화면 선택지(배출시설 종류) | 200 | - |
| `GET /catalog/facts` | - | 사실 카탈로그 요약(보드 편집·라벨용, 내부 사실 제외) | 200 `CatalogFact[]` | - |
| `POST /cases` | O | 건 만들기 + 문진 시작 `{memo?, quantity?, unit?, period?}` | 201 `{case, turn}` | 401, 422 |
| `GET /cases` | O | 내 건 목록(`summary` 포함). 배열 그대로, 옵션 `page`·`size`(전체 건수는 `X-Total-Count`). 서버용 `/internal/v1/cases`는 `{items, pagingInfo}` | 200 `CaseOut[]` | 401 |
| `GET /cases/{id}` | O | 건 상세: `case, current_verdict, verdict_history, latest_turn, documents, handoff, conversation` | 200 `CaseDetail` | 401, 404 |
| `POST /cases/{id}/diagnosis/messages` | O | 말(`text`) 또는 버튼(`quick_reply`) 한 턴 | 200 `TurnResponse` | 404, 409, 422 |
| `POST /cases/{id}/documents` | O | 서류 업로드(multipart: `file`, 선택 `facts` JSON). `facts`는 검수 대기 후보로만 저장(판정 불변) | 201 `{document, turn, values}` | 404, 409, 413, 415, 422 |
| `POST /cases/{id}/documents/{doc}/versions` | O | 서류 파일 교체(새 버전). 이전 버전 증빙은 자동 해제 | 201 `{document, turn, values}` | 404, 409, 413, 415, 422 |
| `POST /cases/{id}/documents/{doc}/values/apply` | O | 검수 완료 값 적용 → EVIDENCED, 다시 평가 | 200 `TurnResponse` | 404, 409, 422 |
| `POST /cases/{id}/documents/{doc}/revoke` | O | 서류(버전) 효력 해제 `{reason?, document_version?}` | 200 `TurnResponse` | 404, 409 |
| `POST /cases/{id}/rebase` | O | 규칙 버전이 바뀐 건(`KB_CHANGED`)을 지금 규칙으로 다시 평가 | 200 `TurnResponse` | 404, 409 |
| `POST /cases/{id}/confirm` | O | 확정 `{expected_code?}`. 서버가 다시 평가한다 | 200 `{case, verdict, handoff, frozen_trace_rows}` | 404, 409 |
| `POST /cases/{id}/reopen` | O | 확정 건 다시 열기 `{reason?}` | 200 `{case, superseded_verdict, turn}` | 404, 409 |
| `GET /cases/{id}/trace` | O | 사실 이력·턴 Trace·판정 버전(감사용) | 200 `TraceOut` | 404 |

`quick_reply` 형식: `{"key": "<사실 키 또는 묶음 id>", "kind": "value|unknown|none_all|expand|retract", "value": …}`. `text`와 `quick_reply`는 둘 중 하나만 보낸다(둘 다/둘 다 없음은 422). `retract`는 그 사실을 '모르는 상태'로 되돌린다.

## 4. 기업 정보(profile)

```json
{"basic": {"company_name": "…", "industry": "플라스틱 제품 제조업", "address": "…"},
 "facilities": ["air_emission", "water_emission"],
 "products": ["자동차 내장 부품"],
 "facts": {}}
```

- `facilities`: `air_emission` / `water_emission` / `noise_vibration` / `waste_treatment` / `none`. `none`은 다른 값과 함께 보낼 수 없다(422). 선택지와 라벨은 `GET /companies/profile-options`가 준다.
- 서버가 사이트 사실을 계산해 문진 시작 때 `PROFILE` 출처로 넣는다.
  - 대기·수질·소음진동 중 하나라도 있으면 `emission_facility: true`, `none`이면 false, 그 밖에는 키 없음(문진에서 묻는다).
  - `waste_treatment`이면 `waste_facility: true`, `none`이면 false.
  - `facts`를 직접 보내면 계산값보다 우선한다(고급용). 카탈로그에 없는 키·맞지 않는 값은 건너뛴다.
- 응답의 `profile.facts`는 항상 계산값과 직접 지정값을 합친 값이다(없으면 `{}`).

## 5. 흐름과 예시

공통 헤더 `X-Company-Id`는 생략했다. 응답은 핵심 필드만 보인다.

### 5.1 PP 분류번호 확정(질문 → 서류 → 확정)

```
POST /cases   {"memo": "PP 필름 자투리", "quantity": 1.5, "unit": "t"}
→ 201 {"case": {"id": "C1", "status": "DIAGNOSING",
                "summary": {"title": "새 폐기물", "status_label": "문진 중", "next_action": "질문에 답하기", …}},
       "turn": {"branch": "ASK_FACT", "message": "…", "case_status": "DIAGNOSING",
                "ui": {"question": {"key": "material", "input": "choice", "options": […], …},
                       "board": {…}, "can_confirm": false, "suggested_replies": […]}}}

POST /cases/C1/diagnosis/messages
     {"quick_reply": {"key": "contamination_screen", "kind": "none_all"}}
→ 200 {"branch": "ASK_FACT", "ui": {"question": {"key": "oil_content_pct", "input": "number",
                                                  "allow_free_number": true, …}}}

POST /cases/C1/documents   (multipart) file=시험성적서.pdf, facts={"oil_content_pct": 2}   # facts는 선택, 수동 입력
→ 201 {"document": {"id": "D1", "version": 1, "values": [{"id": "V1", "status": "UNVERIFIED", …}], …},
       "values": [{"id": "V1", "fact_key": "oil_content_pct", "value": 2, "status": "UNVERIFIED", …}],
       "turn": {"branch": "ASK_FACT", …}}      # 후보일 뿐 판정은 그대로

POST /cases/C1/documents/D1/values/apply   # 서버가 검수를 마친 뒤
     {"values": [{"value_id": "V1", "document_version": 1, "reviewer": "…", "reviewed_at": "…"}]}
→ 200 {"branch": "FINAL_REVIEW",
       "verdict": {"status": "CONFIRMABLE", "waste_code": "51-03-01", …},
       "ui": {"can_confirm": true, "result": {"result_type": "WASTE_CODE", "code": "51-03-01",
              "conclusion": "…", "review": "UNVERIFIED"}}}

POST /cases/C1/confirm   {"expected_code": "51-03-01"}
→ 200 {"case": {"status": "CODE_CONFIRMED", "summary": {"status_label": "확정", "code": "51-03-01", …}},
       "verdict": {"version": 1, "result_type": "WASTE_CODE", "code": "51-03-01", …},
       "handoff": {"contract": "diagnosis-handoff-v1", "result_type": "WASTE_CODE",
                   "route_guidance": {"action": "RECOMMEND_ROUTE", …}, …},
       "frozen_trace_rows": 7}
```

`expected_code`는 선택이다. 화면에서 본 결론과 서버가 다시 평가한 결론이 다르면 409이고 `detail`에 `server_code`·`server_outcome`이 들어 있다. 확정은 서버가 규칙 엔진 결과(FINAL_REVIEW, `can_confirm`)일 때만 한다.

### 5.2 서류로 증빙(REQUEST_EVIDENCE)

증빙이 필요한 사실이 말(CLAIMED)뿐이면 확정할 수 없다.

```
→ turn: {"branch": "REQUEST_EVIDENCE", "case_status": "NEEDS_INFO",
         "ui": {"requested_documents": [{"evidence_type": "TEST_REPORT", "label": "시험성적서", …}],
                "board": {"documents_needed": […]}}}

POST /cases/C1/documents   file=report.pdf, facts={"oil_content_pct": 2}
→ 201 {"document": {"id": "D1", "version": 1, …}, "values": [{"id": "V1", "status": "UNVERIFIED", …}],
       "turn": {"branch": "REQUEST_EVIDENCE", …}}         # 검수 대기
POST /cases/C1/documents/D1/values/apply   {"values": [{"value_id": "V1", "document_version": 1, "reviewer": "…", "reviewed_at": "…"}]}
→ 200 {"branch": "FINAL_REVIEW", …}
```

- 업로드 값은 후보일 뿐이다. 검수 완료로 적용(apply)한 값만 `DOCUMENT` 출처의 `EVIDENCED` 사실이 된다(보드에서 "서류로 확인"). 엔진은 원문과 대조하지 않고 형식(빈 값, "-", 숫자 칸의 글자, 선택지 밖 값)만 거른다. 자세한 흐름·해제·교체는 `server-engine-contract.md` 3.1절. 말한 값과 서류 값이 다르면 `RESOLVE_CONFLICT` 턴이 오고 `ui.conflicts`의 `choices`로 해결한다.
- 지원 형식: PDF·텍스트 등. 그 밖은 415, 크기 한도(기본 10MiB) 초과는 413.
- 업로드는 대화 기록에 "서류를 올렸어요: 파일명"으로 남는다.

### 5.3 코드 없는 결론(NOT_WASTE) 확정

분류번호 없이 규칙이 결론(`outcome`)을 낸 경우도 같은 확정 API를 쓴다.

```
→ turn: {"branch": "FINAL_REVIEW", "verdict": {"waste_code": null, "outcome": "NOT_WASTE", …},
         "ui": {"can_confirm": true, "result": {"result_type": "NO_CODE", "code": null,
                "outcome": "NOT_WASTE", "conclusion": "…폐기물이 아닌 것으로 판정됩니다"}}}

POST /cases/C1/confirm   {"expected_code": "NOT_WASTE"}     # 코드 없는 결론은 사유(outcome)로 비교, "@NOT_WASTE"도 받음
→ 200 {"case": {"status": "CODE_CONFIRMED", "summary": {"code": null, "outcome": "NOT_WASTE", "result_label": "폐기물 아님"}},
       "verdict": {"result_type": "NO_CODE", "code": null, "outcome": "NOT_WASTE", …},
       "handoff": {"result_type": "NO_CODE", "route_guidance": {"action": "NO_ROUTE_NEEDED", …}, …}}
```

코드 없는 결론도 건 상태는 `CODE_CONFIRMED`다. 경로추천 AI는 `handoff.result_type`과 `route_guidance.action`을 본다.

### 5.4 사실 고치기·철회

```
POST /cases/C1/diagnosis/messages {"quick_reply": {"key": "material", "kind": "value", "value": "PE"}}   # 값 바꾸기
POST /cases/C1/diagnosis/messages {"quick_reply": {"key": "material", "kind": "retract"}}                # 철회
```

철회한 사실은 보드에서 빠지고 이후 다시 진술하면 그 값이 유효하다. 서류로 확인된 값(EVIDENCED)은 철회로 무시되지 않는다. 확정된 건은 reopen 전에는 둘 다 409다.

### 5.5 용어 설명과 추정 안내 (2026-11-09 추가)

- `ui.question.terms`: 질문 글에 나온 전문용어의 쉬운 설명 `[{term, plain, example}]`(`knowledge/glossary.yaml`, 사람이 쓴 고정 설명).
- `ui.result.assumptions`, `handoff.assumptions`: 시험·서류가 아니라 사용자 답(대리 질문)에서 추정한 사실의 안내 문장 목록. 비었으면 `[]`.
- 추측 답변("아마 ~일걸", "대충 ~ 정도"): 추출 AI가 확신 정도를 함께 표시하고, 추측한 값은 판정 보드 사실에 `hedged: true`·`source_label` "… · 추측"으로, 결과 `assumptions`에 "사용자가 추측으로 답한 값"으로 보인다. 지정폐기물 가능성을 지우는 추측(오염 확인 묶음의 '해당 없음', 말로 답한 수치)은 결론이 나도 확정 전에 한 번 다시 묻는다(`sub_branch: "CONFIRM_GUESS"`, 같은 질문 카드). 버튼으로 다시 답하면 추측 표시가 풀린다.
- `assist`(턴 응답, 추가 필드): 사용자가 "왜?"(`why`), "뭐예요?"(`term`)라고 묻거나 문진 밖 요청(`off_topic`)을 했을 때만 오는 보충 설명 `{intent, text, sources[{id, type, ref, excerpt}], terms[], review}`. 평범한 답변 턴에는 `null`. 사실을 기록하지 않으므로 `branch`·질문 카드·판정이 직전과 같다(답과 질문이 섞이면 답은 평소처럼 기록). 서버는 가공 없이 화면에 넘긴다. 설계: `docs/design/agent-skill-harness.md`.

## 6. 질문 카드 `ui.question.input` 규칙

| `input` | 언제 | 화면이 하는 일 | 보내는 값 |
|---|---|---|---|
| `choice` | enum·bool 사실 | `options` 버튼 | `{key, kind: "value", value: option.value}` (모름은 `kind: "unknown"`) |
| `group` | 묶음 질문(`unit: "group"`) | `options`의 `none_all`("모두 해당 없음") / `expand`(펼치면 `items`를 하나씩) | `{key: <group_id>, kind: "none_all"}` / 펼친 뒤 항목별 `value` |
| `material_group` | 질문 key가 다른 사실의 상위 분류(`parent`)일 때 | 소재 분류 타일 | `{key, kind: "value", value: 분류 값}` |
| `material` | `parent`가 있는 사실(분류 안 소재) | 소재 목록 | `{key, kind: "value", value: 소재 값}` |
| `number` | number 사실 | 구간 버튼(`options`, value는 NumRange) + `allow_free_number`이면 직접 입력칸 | `{key, kind: "value", value: 12.5 또는 {"lo":…, "hi":…, "lo_inc":…, "hi_inc":…}}` |
| `code` | 별표4 번호 선택 | 번호 목록 | `{key, kind: "value", value: 번호}` |

- `value_type`은 `enum|bool|number`(group은 null). `allow_unknown`이 true일 때만 "모름" 버튼을 보인다. `text`는 결정적 질문 문장, `help`는 접어 두는 안내(없으면 null).
- 버튼 답은 서버가 LLM 없이 결정적으로 반영한다. 자유 문장(`text`)만 추출기(LLM)를 거친다.
- 대화 기록에는 버튼 답이 `role: "user"`, `text` = 고른 선택지 라벨, `quick_reply` = 보낸 값으로 남는다.

## 7. 건 상태 전이

```
(생성) ─► DIAGNOSING ◄──────────────┐
            │  ▲                    │ reopen
 증빙·정보 부족 │  │ 질문 가능/FINAL_REVIEW │
            ▼  │                    │
         NEEDS_INFO          confirm  │
            └──────────► CODE_CONFIRMED ─► IN_TRANSIT ─► COMPLETED   (뒤 둘은 경로추천 쪽이 갱신)
```

| 상태 | `summary.status_label` | 문진(메시지·서류) | 비고 |
|---|---|---|---|
| `DIAGNOSING` | 문진 중 | 가능 | `FINAL_REVIEW`(확정 검토)도 확정 전까지 이 상태 |
| `NEEDS_INFO` | 추가 정보 필요 | 가능 | `REQUEST_EVIDENCE`·`UNSUPPORTED`(판정 불가) 턴 뒤 |
| `CODE_CONFIRMED` | 확정 | 불가(409) | 코드 없는 결론 확정 포함. `reopen`으로만 `DIAGNOSING` 복귀 |
| `IN_TRANSIT` | 운반 중 | 불가 | 갱신 주체 미정(범위 밖) |
| `COMPLETED` | 완료 | 불가 | 이력 |

- 턴마다 `TurnResponse.case_status`가 새 상태를 알려 준다.
- `confirm`은 `DIAGNOSING`·`NEEDS_INFO`에서 서버가 다시 평가해 확정 가능할 때만 성공한다. 확정하면 판정 버전이 고정되고 Trace 행이 불변이 된다.
- `reopen`은 `CODE_CONFIRMED`에서만 가능하다. 이전 판정은 `superseded`로 남고(`verdict_history`) 대화 기록은 이어진다.

## 8. 오류 형식

모든 오류는 `{"detail": {"code": "CASE_NOT_FOUND", "message": "…", "details": {…}}}`다. `code`는 기계용(전체 표는 `server-engine-contract.md` 5절), `message`는 화면에 보여 주는 한국어 문장이다. 요청 형식 검증 오류(422)도 같은 형식(`VALIDATION_ERROR`, `details.errors[{loc,msg,type}]`)이다. 기존 호환을 위해 `details`의 키가 `detail` 바로 아래에도 남아 있다.

| 코드 | 상황 | `detail` 추가 필드 |
|---|---|---|
| 401 | `X-Company-Id` 없음·모르는 기업(`COMPANY_REQUIRED`) | - |
| 404 | 건 없음·다른 기업의 건 | - |
| 409 | 문진 불가 상태(확정 건에 메시지·서류·철회), 이미 확정, 확정 불가, 화면 결론과 서버 판정 불일치, 다른 요청이 먼저 갱신, 규칙 버전 바뀜(`KB_CHANGED`), 서류 버전 바뀜(`DOCUMENT_VERSION_MISMATCH`) | `case_status` / `branch`·`reason`·`failure_reason` / `server_code`·`server_outcome` / `session_kb_version`·`current_kb_version` / `current_version`·`sent_versions` |
| 413 | 업로드 파일이 너무 큼 | - |
| 415 | 지원하지 않는 파일 형식 | - |
| 422 | (A) 요청 형식 오류: `details.errors`. (B) 서류 값(업로드 `facts`·적용 `values`) 형식 오류: JSON 객체 아님, 카탈로그에 없는 키, 빈 값·"-", 숫자 칸의 글자, 선택지 밖 값, 다른 단위 | (B) `detail.message` + `details.problems` |

동시에 같은 건을 갱신하면 늦은 요청이 409(`다른 요청이 같은 문진을 먼저 갱신했습니다…`)를 받는다. 다시 `GET /cases/{id}`로 읽고 시도하면 된다.

## 9. 목록·상세의 화면용 필드

- `CaseOut.summary`(목록·상세 공통): `title`(소재 라벨 → 메모 첫 줄 30자 → "새 폐기물"), `code`, `outcome`, `result_label`("51-03-01 이름" 또는 "폐기물 아님" 등, 결론 전이면 null), `status_label`, `next_action`.
- `CaseDetail.conversation[]`: `turn_id, role(user|assistant), text, quick_reply, memo, document_id, branch, question_key, at`. 서버에 저장되어 새로고침·reopen 뒤에도 같다. 마지막 턴의 카드는 `latest_turn`으로 그린다.
- `GET /catalog/facts`: `[{key, label, type, unit, values: [{value, label, parent_value}], parent}]`. 카탈로그 순서, 내부 사실 제외. bool은 예/아니오 두 값, number는 `values` 비움.
