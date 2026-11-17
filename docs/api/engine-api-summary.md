# 폐기물 진단 엔진 API 요약 (명세서 반영용)

> 대상: scrap-server 담당자(명세서 작성). 2026-11-09 기준.
> 필드 단위 정의는 [openapi.json](openapi.json), 인증·오류·페이징 규칙은 [server-engine-contract.md](server-engine-contract.md)가 기준입니다. 이 문서는 "무엇을 넣으면 무엇이 나오는지"만 짧게 정리했습니다.

## 한눈에 보기

- **입력:** 폐기물에 대한 사용자의 말(또는 버튼 답), 시험성적서 같은 서류 값(검수 후), 서버가 확인한 기업 정보
- **출력:** 다음에 물을 질문, 또는 최종 판정(폐기물 분류번호 예 `51-03-01`, 또는 "폐기물 아님" 같은 코드 없는 결론). 확정하면 경로추천 AI에 넘길 **인계 객체(`handoff`)**
- **호출 순서:** 건 만들기 → 문진 답변 반복(필요하면 서류 업로드 → 검수 → 적용) → 확정 → (필요하면 다시 열기)

## 공통

| 항목 | 값 |
|---|---|
| 기본 주소 | `http://<엔진 호스트>:8030/internal/v1` (서버만 호출, 브라우저 직접 호출 금지) |
| 헤더 | `Authorization: Bearer <ENGINE_SERVICE_TOKEN>`, `X-Company-Id: <서버가 인증한 기업 ID>` |
| 형식 | JSON(UTF-8). 서류 업로드만 `multipart/form-data` |
| 오류 | `{"detail": {"code": "…", "message": "…", "details": {…}}}`. 코드 목록은 server-engine-contract.md 5절 |
| 기업 | 처음 보는 `X-Company-Id`는 엔진이 자동 등록(별도 등록 API 없음) |

### 매 턴 응답 `TurnResponse` (문진·서류 적용·rebase가 공통으로 돌려줌)

```json
{
  "branch": "ASK_FACT | REQUEST_EVIDENCE | RESOLVE_CONFLICT | FINAL_REVIEW | UNSUPPORTED",
  "message": "사용자에게 보여 줄 문장",
  "case_status": "DIAGNOSING | NEEDS_INFO | CODE_CONFIRMED",
  "verdict": {"status": "…", "waste_code": "51-03-01 | null", "outcome": "NOT_WASTE | … | null"},
  "ui": {
    "question": {"key": "material", "text": "질문 제목", "input": "choice | number | group | …",
                 "options": [{"label": "PP", "value": "pp", "kind": "value"}],
                 "help": "확인 방법", "terms": [{"term": "용출", "plain": "쉬운 설명", "example": null}]},
    "board": {"facts": ["지금까지 확인된 사실"], "pending": ["남은 확인 항목"], "progress": "…"},
    "requested_documents": [{"evidence_type": "TEST_REPORT", "label": "시험성적서"}],
    "can_confirm": false,
    "result": {"result_type": "WASTE_CODE | NO_CODE", "code": "51-03-01", "conclusion": "…",
               "reason": "코드 없는 결론의 이유(없으면 null)", "next_step": "…", "assumptions": []}
  },
  "assist": null
}
```

`assist`는 사용자가 "왜?", "뭐예요?"라고 묻거나 문진 밖 요청을 했을 때만 오는 보충 설명입니다(`{intent, text, sources, terms, review}`). 판정은 바뀌지 않고, 서버는 그대로 화면에 넘기면 됩니다.

`branch`가 화면을 정합니다: `ASK_FACT` 질문 카드, `REQUEST_EVIDENCE` 서류 요청, `RESOLVE_CONFLICT` 말과 서류 값이 다름, `FINAL_REVIEW` 결과 + 확정 버튼, `UNSUPPORTED` 판정 불가.

---

## 1. 건 만들기 + 문진 시작

- **API:** `POST /internal/v1/cases`
- **Request**
  ```json
  {"memo": "PP 필름 자투리", "quantity": 1.5, "unit": "t", "period": "2026-11",
   "confirmed_facts": {"emission_facility": true}, "company_profile_version": "p7"}
  ```
  모두 선택. `confirmed_facts`는 **사용자가 확인한 기업 정보만**(사실 키 → 값).
- **Response (201)** `{"case": {"id": "C1", "status": "DIAGNOSING", "summary": {…}}, "turn": TurnResponse}`
- **설명:** 진단 건 하나를 만들고 첫 질문을 돌려줍니다.

## 2. 문진 답변 (한 턴)

- **API:** `POST /internal/v1/cases/{id}/diagnosis/messages`
- **Request** (`text`와 `quick_reply` 중 하나만)
  ```json
  {"text": "폐수처리장에서 나온 무기성 오니예요"}
  {"quick_reply": {"key": "material", "kind": "value", "value": "pp"}}
  ```
  `kind`: `value`(값 선택), `unknown`(모름), `none_all`(묶음 질문 "모두 해당 없음"), `expand`, `retract`(답 취소). 선택 `confirmed_facts`, `company_profile_version`도 보낼 수 있음.
- **Response (200)** `TurnResponse`
- **설명:** 자유 문장은 AI가 사실을 뽑고(검증 후) 규칙 엔진이 판정합니다. 분류번호는 규칙 엔진만 정합니다.

## 3. 건 조회

| API | Response | 설명 |
|---|---|---|
| `GET /internal/v1/cases/{id}` | `{case, current_verdict, verdict_history, latest_turn, documents, handoff, conversation}` | 건 상세(대화 기록·서류·확정 결과 포함) |
| `GET /internal/v1/cases?status=&page=1&size=20` | `{items: [case…], pagingInfo}` | 내 기업의 건 목록(최근 갱신순) |
| `GET /internal/v1/cases/{id}/trace` | `TraceOut` | 사실 이력·판정 근거(감사용) |
| `GET /internal/v1/catalog/facts` | `[{key, label, type, values…}]` | 사실 목록·선택지(라벨 표시용) |

## 4. 서류: 업로드 → 검수 → 적용

엔진은 서류 원문을 읽거나 대조하지 않습니다. **서버의 검수 화면에서 사람이 확인한 값만** 판정에 씁니다.

### 4-1. 업로드
- **API:** `POST /internal/v1/cases/{id}/documents` (multipart)
- **Request:** `file`=파일, 선택 `facts`=`{"oil_content_pct": 2}`(JSON 문자열, 사람이 입력한 값)
- **Response (201)** `{"document": {"id": "D1", "version": 1, …}, "values": [{"id": "V1", "fact_key": "oil_content_pct", "value": 2, "status": "UNVERIFIED"}], "turn": TurnResponse}`
- **설명:** 값은 검수 대기 후보로만 저장되고 판정은 아직 바뀌지 않습니다.

### 4-2. 검수 완료 값 적용
- **API:** `POST /internal/v1/cases/{id}/documents/{doc}/values/apply`
- **Request**
  ```json
  {"values": [
    {"value_id": "V1", "document_version": 1, "reviewer": "검수자 id", "reviewed_at": "2026-11-09T10:00:00+09:00"},
    {"value_id": "V2", "value": 7, "document_version": 1, "reviewer": "…", "reviewed_at": "…"},
    {"value_id": "V3", "reject": true, "document_version": 1, "reviewer": "…", "reviewed_at": "…"}
  ]}
  ```
- **Response (200)** `TurnResponse` (값을 "서류로 확인됨"으로 반영하고 다시 판정)

### 4-3. 기타
| API | Request | 설명 |
|---|---|---|
| `POST …/documents/{doc}/versions` | multipart(업로드와 같음) | 파일 교체. 이전 버전 값은 자동 무효 |
| `POST …/documents/{doc}/revoke` | `{reason?, document_version?}` | 서류 효력 해제 → `TurnResponse` |

## 5. 확정

- **API:** `POST /internal/v1/cases/{id}/confirm`
- **Request** `{"expected_code": "51-03-01"}` (선택. 화면에서 본 결론과 다르면 409)
- **Response (200)**
  ```json
  {"case": {"status": "CODE_CONFIRMED", …},
   "verdict": {"version": 1, "result_type": "WASTE_CODE", "code": "51-03-01", …},
   "handoff": {
     "contract": "diagnosis-handoff-v1",
     "result_type": "WASTE_CODE | NO_CODE",
     "waste_code": "51-03-01", "waste_name": "폐합성수지류(…)",
     "category": "GENERAL | DESIGNATED | …",
     "outcome": "NOT_WASTE | EXCLUDED | INTERPRETATION_NEEDED | … | null",
     "route_guidance": {"action": "RECOMMEND_ROUTE | NO_ROUTE_NEEDED | REFER_AUTHORITY | …",
                        "summary": "안내 요지", "notes": ["참고"]},
     "facts": {"material": {"value": "pp", "status": "CLAIMED", "source_type": "UTTERANCE"}},
     "evidence": [{"fact": "oil_content_pct", "document_id": "D1"}],
     "basis": [{"type": "LAW", "ref": "폐기물관리법 시행령 별표 1", "excerpt": "…"}],
     "review": "UNVERIFIED",
     "assumptions": ["'PCB 사용 기기·절연유 관련' 답을 근거로 PCB 용출 농도·PCB 함량(액체)은 시험 없이 기준 미만으로 추정했습니다. …"],
     "timestamps": {"diagnosis_started_at": "…", "confirmed_at": "…", "as_of": "2026-11-09"}
   },
   "frozen_trace_rows": 7}
  ```
- **설명:** 서버가 지금 사실로 다시 평가해 확정합니다. **`handoff`가 경로추천 AI의 입력**입니다(형식: [handoff-contract.md](../handoff-contract.md)). 경로추천 AI는 `result_type`과 `route_guidance.action`을 보고 다음 일을 정합니다.

## 6. 다시 열기·규칙 갱신

| API | Request | Response | 설명 |
|---|---|---|---|
| `POST …/cases/{id}/reopen` | `{reason?}` | `{case, superseded_verdict, turn}` | 확정 건을 다시 열어 이어서 문진 |
| `POST …/cases/{id}/rebase` | 없음 | `TurnResponse` | `409 KB_CHANGED`(규칙표 업데이트)를 받으면 호출 후 같은 요청을 다시 보냄 |

## 7. 기업 데이터 삭제 (탈퇴)

| API | Response | 설명 |
|---|---|---|
| `DELETE /internal/v1/companies/{external_id}/data` | `{company_hash, status, counts, attempts, …}` | 그 기업의 모든 데이터 삭제. 여러 번 불러도 결과 같음. `X-Company-Id` 불필요 |
| `GET /internal/v1/companies/{external_id}/data/deletion` | 같음 | 마지막 삭제 이력 |

## 서버가 꼭 처리할 오류

| code | 뜻 | 할 일 |
|---|---|---|
| `KB_CHANGED` (409) | 규칙표가 업데이트됨 | `rebase` 호출 후 재요청 |
| `CONCURRENT_UPDATE` (409) | 같은 건을 다른 요청이 먼저 고침 | 다시 조회 후 재시도 |
| `CASE_NOT_DIAGNOSABLE` (409) | 이미 확정된 건 | "다시 열기" 안내 |
| `DOCUMENT_VERSION_MISMATCH` (409) | 검수 중 파일이 교체됨 | 최신 파일로 다시 검수 |
| `VALIDATION_ERROR` (422) | 값 형식 오류 | `details.problems`를 화면에 표시 |
| `CASE_NOT_FOUND` (404) | 없거나 다른 기업의 건 | 404 그대로 |

타임아웃은 **30초**를 권장합니다(한 턴에 AI를 최대 2번 불러 보통 4~8초).
