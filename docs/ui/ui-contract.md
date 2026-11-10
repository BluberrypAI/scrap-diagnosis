# UI용 API 보강 형식 (ui-v1)

`docs/ui/ui-design.md`의 화면을 그리기 위해 기존 API에 **추가**하는 필드다. 기존 필드는 바꾸거나 지우지 않는다. 백엔드 구현과 참조 프론트(`web/`)는 이 문서를 기준으로 맞춘다. 이름이나 형식을 바꿔야 하면 이 문서부터 고친다.

## 1. `TurnResponse.ui` 추가 필드
모든 턴 응답(`POST /cases`, `…/diagnosis/messages`, `…/documents`, `…/reopen`의 `turn`, `GET /cases/{id}`의 `latest_turn`)에 들어간다.

### 1.1 `ui.question` (기존 key, unit, facts, options에 더함)
```json
{
  "key": "contamination_screen",
  "unit": "group",
  "facts": ["designated_residue", "pcb_possible", "toxic_chemical_discard"],
  "options": [{"label": "모두 해당 없음", "value": {"…": "…"}, "kind": "none_all"},
              {"label": "해당하는 게 있어요 / 잘 모르겠어요", "value": null, "kind": "expand"}],
  "text": "이 폐기물에 해당하는 것이 있나요? (기름·잔류물·PCB·유해화학물질)",
  "help": "대부분의 제조 공정 폐기물은 '모두 해당 없음'입니다. …",
  "input": "group",
  "value_type": null,
  "allow_unknown": false,
  "allow_free_number": false,
  "items": [{"key": "designated_residue", "label": "지정폐기물 잔류물"}, {"key": "pcb_possible", "label": "PCB 사용 기기·절연유 관련"}],
  "answered_items": [{"key": "oil_presence", "label": "기름 묻음·섞임", "value_label": "기름이 묻거나 섞이지 않음"}]
}
```
| 필드 | 뜻 |
|---|---|
| `text` | 화면에 보일 질문 문장(카탈로그 질문·묶음 제목). 응답 `message`는 LLM이 다듬은 말이고, `text`는 결정적이다 |
| `help` | 확인 방법(접어 두는 도움말). 없으면 null |
| `input` | 카드 종류: `choice`(enum·bool) / `group`(묶음) / `material_group`(소재 분류 타일) / `material`(분류 안 소재 목록) / `number`(수치) / `code`(별표4 번호 선택) |
| `value_type` | 사실 타입 `enum`/`bool`/`number`(group은 null) |
| `allow_unknown` | "모름" 버튼을 보일지(`options`에 kind=unknown이 있으면 true) |
| `allow_free_number` | number일 때 직접 입력칸을 보일지(true). 구간 버튼은 `options`(value는 NumRange dict) |
| `items` | group: 이번에 묻는 항목(라벨) |
| `answered_items` | group: 같은 묶음에서 이미 답한 항목. 비었으면 [] |
| `result.assumptions` | 결과 카드: 시험·서류가 아니라 사용자 답에서 추정한 사실의 안내 문장 목록(예: PCB 관련 없음 → 기준 미만 추정). 비었으면 []. 화면은 결론 아래에 눈에 띄게 보여 준다 |
| `terms` | 질문 글에 나온 전문용어의 쉬운 설명 `[{term, plain, example}]`(knowledge/glossary.yaml, 사람이 쓴 고정 설명). 비었으면 []. 화면은 "용어 설명" 접기 등으로 보여 주면 된다 |

`input`이 `material_group`/`material`인 기준: 질문 key가 카탈로그의 상위 분류(다른 사실의 `parent`)면 `material_group`, `parent`가 있는 사실이면 `material`.

### 1.2 `ui.board` (판정 보드)
```json
{
  "facts": [
    {"key": "material", "label": "소재", "value": "pp", "value_label": "PP(폴리프로필렌)",
     "status": "CLAIMED", "source_type": "UTTERANCE", "source_label": "말함",
     "quote": "PP 사출 스크랩", "recorded_at": "2026-11-08T21:59:32+09:00",
     "editable": true, "edit": {"input": "choice", "value_type": "enum", "unit": null,
       "options": [{"label": "PP(폴리프로필렌)", "value": "pp"}]}}
  ],
  "pending": [{"key": "toxic_chemical_discard", "label": "유해화학물질 폐기", "reason": "MISSING"}],
  "progress": {"questions_asked": 2, "max_questions": 12},
  "candidates_count": 22,
  "top_candidates": [{"code": "51-03-01", "name": "…", "outcome": null}],
  "documents_needed": [{"evidence_type": "TEST_REPORT", "label": "시험성적서", "facts": ["ph"], "fact_labels": ["pH"]}]
}
```
- `facts`: 값이 알려진 유효 사실만 넣는다. 내부 사실(`internal`)과 테이블 선택용 상위 분류도 넣는다(사용자가 고를 수 있으므로).
- `source_label`: UTTERANCE=말함, DOCUMENT=서류, PROFILE=기업 정보, SCREENING=묶음 답, DERIVED=자동, SIMULATION=시험
- `status` EVIDENCED이면 배지를 "서류로 확인"으로 한다.
- `editable`: 사용자가 고칠 수 있는지. DOCUMENT·DERIVED는 false다(서류 값은 서류로만 바꾼다).
- `edit`: 고칠 때 보여 줄 입력 형식. 선택지는 카탈로그 전체(enum), bool은 예/아니오, number는 직접 입력.
- `pending`: 확정을 막고 있는 미확인 사실(blocking_facts). `reason`은 MISSING/NEEDS_EVIDENCE/DECLARED_UNKNOWN.
- `top_candidates`: live 후보 상위 5개.
- `documents_needed`: REQUEST_EVIDENCE가 아니어도 증빙이 필요한 사실이 있으면 채운다.

### 1.3 `ui.conflicts` (RESOLVE_CONFLICT일 때)
```json
[{"kind": "CLAIM_VS_EVIDENCE", "fact": "oil_content_pct", "label": "기름성분 함량",
  "claimed": 8, "claimed_label": "8%", "evidenced": 2.0, "evidenced_label": "2%",
  "document_id": "…",
  "choices": [{"label": "서류 값(2%)이 맞아요", "quick_reply": {"key": "oil_content_pct", "kind": "value", "value": 2.0}},
              {"label": "서류가 잘못됐어요(새 서류 올리기)", "action": "UPLOAD"}]}]
```
NO_CANDIDATE 충돌은 `fact`에 원인 사실 목록의 첫 키, `facts`에 전체를 넣고, `choices`는 각 사실 "다시 답하기"(`action: "EDIT_FACT"`, `key`)로 둔다.

### 1.4 `ui.result` (FINAL_REVIEW일 때)
```json
{"result_type": "WASTE_CODE", "code": "51-03-01", "name": "…", "category": "GENERAL",
 "outcome": null, "conclusion": "분류번호 51-03-01 …로 판정됩니다", "next_step": "확정하면 경로 추천으로 넘어갑니다",
 "review": "UNVERIFIED"}
```
코드 없는 결론은 `result_type: "NO_CODE"`, `code: null`, `outcome`, `conclusion`(OUTCOME_TEXT)을 채운다.

## 1.6 추측 답변 (2026-11-11 추가)
추측 답변("아마 ~일걸", "대충 ~ 정도"): 추출 AI가 확신 정도를 함께 표시하고, 추측한 값은 판정 보드 사실에 `hedged: true`·`source_label` "… · 추측"으로, 결과 `assumptions`에 "사용자가 추측으로 답한 값"으로 보인다. 지정폐기물 가능성을 지우는 추측(오염 확인 묶음의 '해당 없음', 말로 답한 수치)은 결론이 나도 확정 전에 한 번 다시 묻는다(`sub_branch: "CONFIRM_GUESS"`, 같은 질문 카드). 버튼으로 다시 답하면 추측 표시가 풀린다. 화면은 보드에서 추측 값을 구분해 보여 주고, `CONFIRM_GUESS` 질문은 평소 질문 카드처럼 그린다.

## 1.5 보충 설명: 턴 응답의 `assist` (2026-11-11 추가)
사용자가 "왜 물어봐요?", "용출이 뭐예요?"처럼 묻거나 문진 밖 요청을 하면 온다. 평범한 턴에는 `null`이다.
```json
"assist": {"intent": "why", "text": "이 답에 따라 적용되는 법 규칙이 달라져서 여쭤봐요. …",
           "sources": [{"id": "S1", "type": "LAW", "ref": "폐기물관리법 시행령 별표 1 …", "excerpt": "…"}],
           "terms": [{"term": "용출", "plain": "…", "example": null}], "review": "UNVERIFIED"}
```
- 화면: `text`는 AI 말풍선(질문 말풍선 앞), `sources`는 "근거 보기" 접기, `terms`는 "용어 설명" 접기. `review`가 `UNVERIFIED`면 "검토 전 규칙 · 참고용"을 붙인다.
- 판정에 쓰지 않는다. 질문 카드·판정 보드는 직전과 같다(참조 화면 `web/src/components/AssistBubble.jsx`).

## 2. 대화 기록: `GET /cases/{id}` 의 `conversation`
`CaseDetail`에 `conversation[]`을 추가한다. 새로고침하거나 다시 들어왔을 때 대화를 다시 그리기 위해서다.
```json
[{"turn_id": "…", "role": "user", "text": "PP 사출 스크랩이에요", "quick_reply": null, "at": "…+09:00"},
 {"turn_id": "…", "role": "assistant", "text": "…", "branch": "ASK_FACT", "question_key": "contamination_screen", "at": "…"}]
```
버튼 답은 `role: "user"`, `text`는 고른 선택지 라벨, `quick_reply`는 보낸 값으로 기록한다. 보충 설명이 있던 AI 말에는 `assist`(턴 응답의 `assist`와 같은 모양)가 붙는다. 마지막 턴의 카드는 `latest_turn`으로 그린다(과거 카드는 다시 그리지 않고 읽기 전용 요약만).

## 3. 건 목록 카드: `CaseOut.summary`
```json
{"title": "PP(폴리프로필렌)", "code": "51-03-01", "outcome": null, "result_label": "51-03-01 폐합성수지류",
 "status_label": "확정", "next_action": "경로 추천 대기"}
```
`title`은 소재 라벨이 있으면 그것을, 없으면 메모 첫 줄(30자)을, 그것도 없으면 "새 폐기물"을 쓴다. `status_label`은 DIAGNOSING=문진 중, NEEDS_INFO=추가 정보 필요, CODE_CONFIRMED=확정, IN_TRANSIT=운반 중, COMPLETED=완료다.

## 4. 사실 고치기와 철회: `quick_reply`
- **값 바꾸기:** `{"key": "<fact>", "kind": "value", "value": …}`(기존과 같음). 보드에서 고칠 때도 이것을 쓴다.
- **철회(새로 추가):** `{"key": "<fact>", "kind": "retract"}`. 그 사실을 '모르는 상태'로 되돌린다.
  - 사실 이력에 `status: "UNKNOWN"`, `note: "사용자가 철회"`, `retracted: true`인 행을 남긴다.
  - 평가에서는 같은 키의 이전 진술(CLAIMED)을 무시한다(EVIDENCED는 무시하지 않는다).
  - 이후 다시 진술하면 그 값이 유효하다.
- 확정된 건(CODE_CONFIRMED)은 reopen 전에는 고칠 수 없다(409).

## 5. 기업 정보: `profile` 형식
```json
{"basic": {"company_name": "…", "industry": "플라스틱 제품 제조업", "address": "…"},
 "facilities": ["air_emission", "water_emission"],
 "products": ["자동차 내장 부품"],
 "facts": {"emission_facility": true}}
```
- `facilities` 값: `air_emission`(대기 배출시설) / `water_emission`(수질 배출시설) / `noise_vibration`(소음·진동 배출시설) / `waste_treatment`(폐기물 처리시설) / `none`(해당 없음)
- **서버가 `facts`를 계산한다:** 대기·수질·소음진동 중 하나라도 있으면 `emission_facility: true`, `none`이면 false, 그 밖에는 키를 넣지 않는다. `waste_treatment`이면 `waste_facility: true`.
  - 사용자가 `facts`를 직접 보내면 계산값보다 우선한다(고급용).
- `GET /companies/me`의 응답에 계산된 `facts`가 들어 있다.
- 선택지 목록은 `GET /companies/profile-options`(새로 추가)로 내려준다: `{"facilities": [{"value": "air_emission", "label": "대기 배출시설"}, …]}`.

## 6. 기타
- `GET /catalog/facts`(새로 추가): 보드 편집·라벨용 카탈로그 요약(key, label, type, unit, values[{value,label}], parent). 내부 사실은 제외한다.
- 오류 응답 형식: `{"detail": {"message": "…", …}}`. 화면은 `detail.message`를 보여 준다. 지금은 415 등 일부 오류의 `detail`이 문자열이라, 모두 이 형식으로 맞춘다(422 검증 오류는 FastAPI 기본 형식을 유지하고, 화면은 "입력값을 확인해 주세요"로 처리).

## 구현 메모
- `profile.facts` 응답은 항상 낸다(계산값 + 직접 지정값, 없으면 `{}`). 저장은 보낸 그대로다. `facilities`는 5개 값만 받고(그 밖은 422), `none`은 다른 값과 함께 보낼 수 없다(422). 5절 밖의 키(예: 예전 `site`)는 그대로 저장한다.
- 오류 형식 통일은 `app/api/errors.py`의 `api_error`로 한다. 문서 업로드·적용의 서류 값 형식 오류(422)는 `detail.message` + `details.problems`(같은 값이 `detail.problems`에도 있음)다. FastAPI 요청 검증 422는 기본 형식을 유지한다.
- 대화 기록(`conversation`)은 세션 state의 messages에서 만든다. 서류 업로드는 `role: "user"`, `text: "서류를 올렸어요: 파일명"`, `document_id`로 나온다. 이 기능 전에 쌓인 기록은 `at`이 null일 수 있다. 확정 건에 철회 `quick_reply`를 보내면 409(`case_status` 포함)다.
- 서류 값 흐름(docs/api/server-engine-contract.md 3.1절): 업로드의 `facts`는 **검수 대기 후보**(`document.values[].status: UNVERIFIED`)로만 저장되고 판정은 바뀌지 않는다. 화면은 서류 카드에 후보를 "검수 대기"로 보여 준다. 검수는 서버(scrap-server)가 하고, 검수가 끝난 값만 `…/documents/{doc}/values/apply`로 적용돼 EVIDENCED("서류로 확인")가 된다. 참조 화면의 "검수 완료로 적용" 버튼은 개발용이다(운영 화면은 서버의 검수 흐름을 쓴다). 형식 오류(빈 값, "-", 숫자 칸의 글자, 선택지 밖 값)는 업로드에서 422(`details.problems`)다. 서류 교체(`…/versions`)·해제(`…/revoke`) 뒤에는 그 서류의 증빙이 보드에서 빠진다.
- 규칙이 바뀐 건은 `case.kb_changed: true`이고 쓰기 요청이 409 `KB_CHANGED`다. 화면은 "규칙이 갱신됐어요" 안내와 함께 `POST /cases/{id}/rebase`를 부르면 된다(확정 건은 reopen).
- `CaseOut.summary.title`의 소재 라벨은 마지막 턴 Trace의 유효 사실(CLAIMED/EVIDENCED)에서 읽는다. `result_label`은 확정 전 FINAL_REVIEW 턴에서도 채운다(확정 검토 중).
- 전체 API 설명과 예시는 `docs/api/api-spec.md`, 자동 명세는 `docs/api/openapi.json`이다.
