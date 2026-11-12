# scrap-server ↔ 진단 엔진 내부 API 규약

scrap-server 담당자가 엔진(waste-diagnosis)을 부를 때 쓰는 규약이다. 필드 단위 정의는 `docs/api/openapi.json`(`/internal/v1` 경로 포함)이 기준이고, 이 문서는 경로·인증·오류 코드·페이징을 정한다. 요청·응답 본문의 의미와 흐름 예시는 `docs/api/api-spec.md`(5절)와 같다. 경로 앞에 `/internal/v1`만 붙는다.

## 1. 기본 규칙

- 기본 경로: `/internal/v1` (예: `POST /internal/v1/cases`). 엔진 포트는 8030.
- 형식: JSON(UTF-8). 서류 업로드만 `multipart/form-data`.
- 엔진은 서버 뒤에 둔다. 브라우저가 직접 부르지 않는다. 엔진의 루트 경로(`/cases` 등)는 참조 화면·개발용이며 운영(`APP_ENV=prod`)에서는 막힌다.
- 시각은 ISO 8601(UTC). 쪽 번호는 1부터.

## 2. 인증

모든 `/internal/v1` 요청에 두 헤더를 보낸다.

| 헤더 | 값 | 설명 |
|---|---|---|
| `Authorization` | `Bearer <ENGINE_SERVICE_TOKEN>` | 서버와 엔진이 공유하는 비밀값. 엔진 설정 `ENGINE_SERVICE_TOKEN`과 같아야 한다. 상수 시간으로 비교한다. |
| `X-Company-Id` | 서버의 기업 ID(문자열, 최대 128자) | **서버가 인증한 기업 ID만 넣는다.** 엔진은 토큰이 맞는 요청에서만 이 값을 믿는다. 사용자 입력을 그대로 전달하면 안 된다. |

- 엔진은 처음 보는 `X-Company-Id`를 최소 기업 레코드(이름 `기업 <id>`, 빈 기업 정보)로 **자동 생성**한다. 별도 기업 등록 호출은 없다. 서버 ID는 엔진 DB의 `companies.external_id`에 저장된다.
- 건은 기업별로 격리된다. 다른 기업의 건 id를 불러도 존재 여부를 알려 주지 않고 `404 CASE_NOT_FOUND`다.
- 환경별 동작

| `APP_ENV` | `ENGINE_SERVICE_TOKEN` | `/internal/v1` | 루트 경로·개발용 API |
|---|---|---|---|
| `dev`(기본) | 설정함 | 토큰 필수 | 열림 |
| `dev` | 미설정 | 토큰 없이 통과(로컬 편의) | 열림 |
| `prod` | 설정함 | 토큰 필수 | 404 `ENDPOINT_DISABLED` |
| `prod` | 미설정 | 모두 401 `AUTH_REQUIRED`(설정 누락으로 열리지 않게) | 404 `ENDPOINT_DISABLED` |

- `prod`에서 막히는 개발용 경로: `POST /companies`, `PUT /companies/me/profile`, 헤더만으로 기업을 고르는 루트의 건·문진 경로 전체. `GET /health`, `GET /catalog/facts`, `GET /companies/profile-options`는 계속 열려 있다.

## 3. 엔드포인트

| 메서드·경로 | 설명 | 성공 | 주요 오류 |
|---|---|---|---|
| `POST /internal/v1/cases` | 건 만들기 + 문진 시작 `{memo?, quantity?, unit?, period?, confirmed_facts?, company_profile_version?}`(3.3절) | 201 `{case, turn}` | 401, 400, 422 |
| `GET /internal/v1/cases?status=&page=&size=` | 내 기업의 건 목록(최근 갱신순, `summary` 포함) | 200 `{items, pagingInfo}` | 401, 400, 422 |
| `GET /internal/v1/cases/{id}` | 건 상세(현재 판정·이력·마지막 턴·서류·인계 객체·대화 기록) | 200 `CaseDetail` | 401, 404 |
| `POST /internal/v1/cases/{id}/diagnosis/messages` | 문진 답변 `{text}` 또는 `{quick_reply}` (둘 중 하나) + 선택 `confirmed_facts`·`company_profile_version`(3.3절) | 200 `TurnResponse` | 404, 409 `CASE_NOT_DIAGNOSABLE`·`KB_CHANGED`·`CONCURRENT_UPDATE`, 422 |
| `POST /internal/v1/cases/{id}/documents` | 서류 업로드(multipart: `file`, 선택 `facts` JSON 문자열). `facts`는 검수 대기 후보(UNVERIFIED)로만 저장하고 판정은 바뀌지 않는다 | 201 `{document, turn, values}` | 404, 409 `CASE_NOT_DIAGNOSABLE`·`KB_CHANGED`, 413, 415, 422 |
| `POST /internal/v1/cases/{id}/documents/{doc}/versions` | 같은 서류의 파일 교체(새 버전, multipart는 업로드와 같음). 이전 버전에서 적용된 값·대기 후보는 자동으로 효력 해제(REVOKED) | 201 `{document, turn, values}` | 404 `DOCUMENT_NOT_FOUND`, 409, 413, 415, 422 |
| `POST /internal/v1/cases/{id}/confirm` | 확정 `{expected_code?}`. 서버가 지금 사실로 다시 평가한다 | 200 `{case, verdict, handoff, frozen_trace_rows}` | 404, 409 `NOT_CONFIRMABLE`·`ALREADY_CONFIRMED`·`CODE_MISMATCH`·`KB_CHANGED` |
| `POST /internal/v1/cases/{id}/reopen` | 확정 건 다시 열기 `{reason?}`. 규칙 버전이 바뀌었으면 지금 규칙으로 맞춘다(Trace `REOPEN` → `REBASE`) | 200 `{case, superseded_verdict, turn}` | 404, 409 `NOT_REOPENABLE` |
| `GET /internal/v1/cases/{id}/trace` | 근거 추적(세션·사실·턴·판정) | 200 `TraceOut` | 404 |
| `GET /internal/v1/catalog/facts` | 사실 카탈로그 요약(라벨·선택지) | 200 `CatalogFact[]` | 401 |
| `POST /internal/v1/cases/{id}/documents/{doc}/values/apply` | 검수 완료된 서류 값 적용 `{values: [...]}`(3.1절). EVIDENCED로 반영하고 다시 평가 | 200 `TurnResponse` | 404 `DOCUMENT_NOT_FOUND`, 409 `DOCUMENT_VERSION_MISMATCH`·`CASE_NOT_DIAGNOSABLE`·`KB_CHANGED`, 422 |
| `POST /internal/v1/cases/{id}/documents/{doc}/revoke` | 서류 효력 해제 `{reason?, document_version?}`. 버전을 빼면 모든 버전 | 200 `TurnResponse` | 404, 409 `DOCUMENT_VERSION_MISMATCH`·`CASE_NOT_DIAGNOSABLE`·`KB_CHANGED` |
| `POST /internal/v1/cases/{id}/rebase` | 저장된 규칙 버전이 바뀐 건을 지금 규칙으로 다시 평가(본문 없음). 확정 건은 409 | 200 `TurnResponse` | 404, 409 `CASE_NOT_DIAGNOSABLE` |
| `POST /internal/v1/cases/{id}/documents/{doc}/extract` | 서류 자동 읽기(OCR·AI, `document-extraction-v1`) | 별도 경로는 미구현 | 시험성적서 표 읽기는 업로드 때 함께 한다(3.1절 1-1) |
| `DELETE /internal/v1/companies/{external_id}/data` | 기업 탈퇴 시 데이터 삭제(멱등, 3.3절). `X-Company-Id` 없이 경로의 서버 기업 ID를 쓴다 | 200 `DeletionOut` | 401, 500 `DELETION_FAILED` |
| `GET /internal/v1/companies/{external_id}/data/deletion` | 가장 최근 삭제 이력 | 200 `DeletionOut` | 401, 404 `DELETION_NOT_FOUND` |

호출 순서: 건 생성 → (메시지·서류 업로드 → 검수 → 적용 반복) → 확정 → 필요하면 reopen → 다시 메시지·확정. 건 상태 전이는 `api-spec.md` 7절. 모든 경로는 루트(참조 화면·개발용)에도 같은 모양으로 있다.

### 3.1 서류 값: 후보 → 검수 → 적용

엔진은 서류 원문과 값을 대조하지 않는다(값이 맞는지 엔진이 판단할 수 없다). **검수가 끝난 값만 판정에 쓴다.** PDF·이미지를 올리면 엔진이 시험성적서 표에서 값을 자동으로 읽어 **후보로만** 넣는다(아래 1-1). 읽은 값이 맞는지는 사람이 원문을 보고 검수한다.

1. **업로드**: `POST …/documents`(multipart `file`, 선택 `facts` = `{"사실 키": 값}` JSON 문자열). 값은 `document_values`에 `UNVERIFIED` 후보로 저장된다. 판정·사실 이력은 바뀌지 않는다(응답 `turn`은 같은 판정). 응답 `values`와 `document.values`에 후보가 있다(`id`, `fact_key`, `value`, `document_version`, `status`).
   - **1-1. 표 자동 읽기**: PDF·이미지면 시험성적서 표에서 납·카드뮴 용출, 기름성분, 수분, pH 등을 읽어 같은 `UNVERIFIED` 후보로 더한다(`note`가 `표 자동 읽기(검수 대기) · 1쪽 표1 3행 3열 · 원문 '0.12 mg/L'`). `facts`로 직접 보낸 키는 자동으로 읽지 않는다(직접 입력이 우선). 불검출은 0이 아니라 구간 `{"hi": 검출한계, "hi_inc": false}`다. 읽은 위치·탈락 사유는 `document.extracted_facts.table_read`(`backend`, `route`, `items[{key, status, value_raw, unit_raw, page, quote, cell_ref, note, guard_reasons?}]`, `not_found`, `warnings`, `errors`)에 있다. 검수 화면은 `cell_ref`(`{page, table_index, row, col}`)로 원문 위치를 보여 줄 수 있다. `extracted_facts.method`는 `none`·`manual`·`table`·`manual+table`.
   - 글자 있는 PDF는 엔진 안에서 읽는다(외부 전송 없음). 스캔본 PDF·이미지는 문서 인식(Azure Document Intelligence, `ALLOW_DOCUMENT_OCR`)이 켜져 있을 때만 읽는다. 꺼져 있으면 스캔본 PDF는 후보 없이 저장되고(`table_read.errors`에 `EMPTY_CONTENT`), **이미지는 415**다. 읽기가 실패해도 업로드는 실패하지 않는다. `DOCUMENT_TABLE_READING=false`면 자동 읽기를 끈다.
2. **형식 검사**(업로드·적용 모두): 카탈로그에 없는 키, 빈 값(`""`, `"-"`, `null`), 숫자 칸의 글자(`"약 2"`, `"5mg"`, `"nan"`), 선택지 밖 값, 카탈로그 단위와 다른 `unit`은 `422 VALIDATION_ERROR`이고 `details.problems[{key, value, reason, index?, value_id?}]`에 항목별로 나온다. 하나라도 틀리면 아무것도 저장하지 않는다.
3. **적용**: 서버가 검수 결과를 보낸다.

```json
POST /internal/v1/cases/C1/documents/D1/values/apply
{"values": [
  {"value_id": "V1", "document_version": 1, "reviewer": "검수자 id", "reviewed_at": "2026-11-09T10:00:00+09:00"},
  {"value_id": "V2", "value": 7, "document_version": 1, "reviewer": "…", "reviewed_at": "…"},
  {"fact_key": "ph", "value": 6.5, "unit": "pH", "document_version": 1, "reviewer": "…", "reviewed_at": "…"},
  {"value_id": "V3", "reject": true, "document_version": 1, "reviewer": "…", "reviewed_at": "…"}
]}
```

- `value_id`(후보 행) 또는 `fact_key` 중 하나는 있어야 한다. `value_id`이면서 `value`를 빼면 후보 값을 그대로 쓰고, 주면 검수에서 고친 값으로 쓴다(행 `note`에 남음). `fact_key`만 주면 새 값 행을 만든다. `reject: true`는 적용하지 않고 후보를 `REJECTED`로 둔다.
- 적용한 값은 사실 이력에 `EVIDENCED`, `source_type: DOCUMENT`, `source_ref: "D1@v1"`(문서 id + 버전)로 append되고 다시 평가한 `TurnResponse`를 돌려준다. 값 행은 `APPLIED`(+`reviewer`, `reviewed_at`), Trace에는 `APPLY` 행이 남는다. 화면용 `document_id`·인계 객체 `evidence[].document_id`는 버전 없는 문서 id다.
- `document_version`이 지금 서류 버전과 다르면(그 사이 파일 교체) `409 DOCUMENT_VERSION_MISMATCH`(`details: {document_id, current_version, sent_versions}`). 최신 버전 기준으로 다시 검수한다.
4. **효력 해제**: `POST …/documents/D1/revoke` `{reason?, document_version?}`. 그 서류(버전을 주면 그 버전)에서 온 증빙을 평가에서 뺀다. 사실 이력은 지우지 않고 키마다 해제 표시 행(`status: UNKNOWN`, `revoked: true`, `source_ref: "D1"` 또는 `"D1@v2"`)을 append한다. 적용된 값 행은 `REVOKED`, Trace는 `REVOKE`. 해제 뒤 같은 값을 다시 적용(apply)하면 다시 유효하다.
5. **파일 교체**: `POST …/documents/D1/versions`(multipart). 서류 버전이 1 오르고 파일 정보가 새 파일로 바뀐다. 이전 버전에서 적용된 값과 대기 후보는 자동으로 `REVOKED`(Trace `DOCUMENT`에 `replaced_version`, `revoked_keys`). 새 파일의 `facts`는 새 버전의 후보다.

값 행 상태: `UNVERIFIED`(검수 대기, 판정에 안 씀) → `APPLIED` | `REJECTED`, `APPLIED` → `REVOKED`(해제·교체). 이 기능 전에 업로드로 바로 EVIDENCED가 된 사실(`source_ref`가 버전 없는 문서 id)도 revoke·교체로 해제된다.

### 3.2 규칙 버전 불일치(KB_CHANGED)와 rebase

건마다 문진을 시작할 때의 규칙 버전(`kb_version`, 규칙 데이터 파일 해시)을 저장한다. 엔진의 규칙이 바뀐 뒤 그 건을 다시 부르면:
- 쓰기(메시지·서류 업로드·교체·적용·해제·확정)는 `409 KB_CHANGED`(`details: {session_kb_version, current_kb_version}`). 조용히 새 규칙으로 이어 가지 않는다.
- 읽기(`GET` 상세·목록·trace)는 그대로 되고 `case.kb_changed: true`가 붙는다.
- `POST …/rebase`(본문 없음): 같은 사실을 지금 규칙으로 다시 평가하고 저장된 규칙 버전을 바꾼다. Trace에 `REBASE`(`from_kb_version`, `to_kb_version`, 테이블 버전 전후) 행이 남는다. 응답은 `TurnResponse`. 그 뒤 평소처럼 이어 간다.
- 확정된 건(`CODE_CONFIRMED`)은 rebase할 수 없다(409 `CASE_NOT_DIAGNOSABLE`). 확정된 판정 버전은 만들 때의 `kb_version` 그대로 보존된다. 확정 건을 `reopen`하면 그 자리에서 지금 규칙으로 맞춘다(Trace `REOPEN` → `REBASE`).

### 3.3 기업 정보(확인된 값)와 기업 데이터 삭제

**확인된 기업 정보.** 건 생성·문진 답변 본문에 선택 필드를 더 보낼 수 있다.
- `confirmed_facts`: `{사실 키: 값}`. **서버에서 사용자가 확인한 값만** 보낸다(확인 전 기본값은 보내지 않는다). 엔진은 `PROFILE_CONFIRMED`(상태 CLAIMED, 보드 표기 "기업 정보(확인됨)")로 사실 이력에 넣는다. 서류 값과 같은 형식 검사를 하고, 틀린 항목이 하나라도 있으면 `422 VALIDATION_ERROR`(`details.problems[{key, value, reason}]`)이며 아무것도 저장하지 않는다. 같은 키·값을 다시 보내면 건너뛴다(그 사이 사용자가 고친 답을 덮어쓰지 않는다). 값이 바뀌었으면 새 값이 들어간다.
- `company_profile_version`: 문자열(최대 64자). 세션에 기록하고 판정 버전(`verdict.company_profile_version`)과 인계 객체 `handoff.inputs`(`{company_profile_version, confirmed_profile_keys}`)에 남긴다. 보내지 않으면 마지막으로 받은 값을 유지한다.
- 엔진이 자기 기업 정보로 사이트 사실을 넣는 경로(PROFILE)는 개발·참조 화면 전용이다. `/internal/v1` 호출은 `APP_ENV`와 관계없이 이 경로를 쓰지 않는다.

**기업 데이터 삭제**(CORP-009, 탈퇴 유예 기간 후 서버가 호출).
- 그 기업의 건·세션·사실 이력·서류(+값)·판정·Trace(확정으로 불변이 된 행 포함)·사용자·기업 행을 모두 지운다. 다른 기업은 건드리지 않는다. 이 경로에서만 Trace 불변 보호를 우회하고 다른 곳은 그대로다.
- 멱등: 이미 지운 기업에 다시 부르면 처음 성공 기록(건수 포함)을 그대로 돌려준다. 엔진이 모르는 ID도 `200`(건수 0)이다.
- 응답 `DeletionOut`: `{company_hash(서버 기업 ID의 SHA-256 hex), status(DONE|FAILED), counts{테이블: 건수}, attempts, error, started_at, finished_at}`. 이력(`deletion_log`)에는 원래 ID가 아니라 해시만 남는다.
- 실패하면 삭제를 모두 되돌리고 `FAILED`로 기록한 뒤 `500 DELETION_FAILED`(`details.attempts`). 같은 호출을 다시 하면 이어서 시도하고 같은 이력 행의 `attempts`가 늘어난다. 성공하면 `DONE`.

### 루트 경로와의 차이

같은 핸들러를 쓰므로 요청·응답 본문은 같다. 다른 점은 둘이다.
- 인증: 루트는 `X-Company-Id`(개발용 기업 id)만 쓴다. 내부는 토큰 + 서버 기업 ID.
- 목록 응답: 루트 `GET /cases`는 참조 화면 호환을 위해 **배열 그대로**다(옵션으로 `page`·`size`를 주면 그 쪽만 자르고 전체 건수는 `X-Total-Count` 헤더). 내부 `GET /internal/v1/cases`는 항상 `{items, pagingInfo}`다.

## 4. 페이징

`GET /internal/v1/cases` 쿼리: `page`(기본 1, 1 이상), `size`(기본 20, 1~100), `status`(선택). 범위를 벗어난 값은 `422 VALIDATION_ERROR`다.

```json
{
  "items": [ { "id": "…", "status": "NEEDS_INFO", "summary": { } } ],
  "pagingInfo": { "currentPageNumber": 1, "pageSize": 20, "totalCount": 45, "totalPages": 3 }
}
```

`totalPages = ceil(totalCount / pageSize)`. 마지막 쪽을 넘기면 `items`가 빈 배열이다(오류 아님). 정렬은 최근 갱신순이고 같으면 id 순이다.

## 5. 오류 형식

모든 오류(404 경로 없음·405 포함)는 같은 형식이다.

```json
{
  "detail": {
    "code": "CASE_NOT_FOUND",
    "message": "건을 찾을 수 없습니다",
    "details": {}
  }
}
```

- `code`: 서버가 분기할 값. 이 표의 코드는 지우거나 뜻을 바꾸지 않고 추가만 한다.
- `message`: 한국어 문장(사용자에게 그대로 보여 줘도 된다). 문구는 바뀔 수 있으니 분기에 쓰지 않는다.
- `details`: 코드별 부가 정보(없으면 `{}`). 기존 참조 화면 호환을 위해 같은 키가 `detail` 바로 아래에도 있다. 서버는 `details`만 읽는다.

| HTTP | `code` | 상황 | `details` |
|---|---|---|---|
| 401 | `AUTH_REQUIRED` | `Authorization` 없음·형식 오류·토큰 불일치, 또는 prod인데 엔진에 토큰 미설정 | - |
| 401 / 400 | `COMPANY_REQUIRED` | `X-Company-Id` 없음. 내부 경로는 400, 루트 경로는 401(모르는 기업도 401) | - |
| 404 | `CASE_NOT_FOUND` | 건이 없거나 다른 기업의 건 | - |
| 404 | `DOCUMENT_NOT_FOUND` | 그 건에 없는 서류 id | - |
| 404 | `ENDPOINT_DISABLED` | prod에서 막힌 개발용 경로 | - |
| 404 / 405 | `NOT_FOUND` | 없는 경로(프레임워크 기본) | - |
| 409 | `CASE_NOT_DIAGNOSABLE` | 문진할 수 없는 상태(확정 건에 메시지·서류·적용·해제·rebase, 세션 없음). reopen 후 진행 | `case_status` |
| 404 | `DELETION_NOT_FOUND` | 삭제 이력이 없는 기업(`GET …/data/deletion`) | - |
| 409 | `ALREADY_CONFIRMED` | 이미 확정된 건을 다시 확정 | `case_status` |
| 409 | `NOT_CONFIRMABLE` | 아직 확정 조건을 채우지 못함 | `branch`, `reason`, `failure_reason` |
| 409 | `NOT_REOPENABLE` | 확정되지 않은 건을 reopen | `case_status` |
| 409 | `CODE_MISMATCH` | `expected_code`가 서버 재평가 결론과 다름 | `server_code`, `server_outcome` |
| 409 | `CONCURRENT_UPDATE` | 같은 건을 다른 요청이 먼저 갱신. 다시 `GET`하고 재시도 | - |
| 409 | `KB_CHANGED` | 저장된 규칙 버전과 현재 규칙이 다름(3.2절). `rebase` 후 진행 | `session_kb_version`, `current_kb_version` |
| 409 | `DOCUMENT_VERSION_MISMATCH` | 적용·해제에 보낸 `document_version`이 지금 서류 버전과 다름(파일 교체됨) 또는 없는 버전 | `document_id`, `current_version`, `sent_versions` |
| 413 | `FILE_TOO_LARGE` | 업로드가 `MAX_UPLOAD_BYTES`(기본 10MB) 초과 | - |
| 415 | `UNSUPPORTED_DOCUMENT` | 지원하지 않는 파일 형식 | - |
| 422 | `VALIDATION_ERROR` | 요청 형식 오류, 또는 서류 값 형식 오류(업로드 `facts`·적용 `values`) | 형식 오류: `errors[{loc,msg,type}]`. 서류 값: `problems[{key, value, reason, index?, value_id?}]` |
| 500 | `DELETION_FAILED` | 기업 데이터 삭제 실패(되돌림, 이력 FAILED). 재시도 | `attempts` |
| 5xx | `INTERNAL_ERROR` | 엔진 내부 오류 | - |

서버는 모르는 `code`를 받으면 HTTP 상태만으로 처리하고 `message`를 그대로 기록한다.

## 6. 설정(엔진 쪽)

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `APP_ENV` | `dev` | `dev` 또는 `prod` |
| `ENGINE_SERVICE_TOKEN` | 없음 | `/internal/v1` Bearer 토큰. prod 필수 |
| `DATABASE_URL` | SQLite | 운영은 PostgreSQL `postgresql+psycopg://…`(`postgresql://`도 psycopg로 바꿔 쓴다) |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` | 10 / 20 / 30초 | DB 연결 풀(PostgreSQL). 턴은 AI를 기다리는 동안 연결을 놓는다 |
| `THREAD_LIMIT` | 40 | 동시에 처리하는 요청(턴) 수 상한. 부하 측정은 `docs/perf/sync-vs-async.md` |
| `LLM_TIMEOUT_SECONDS` | 60 | AI 호출 하나의 제한 시간(재시도 2번). 운영 권장 12 (`docs/perf/turn-latency.md`) |
| `DB_CREATE_ALL` | `true` | 운영은 `false`로 두고 `alembic upgrade head` |
| `MAX_UPLOAD_BYTES` | 10485760 | 서류 업로드 상한 |

이미지는 `Dockerfile`(uvicorn, 포트 8030). 개발용 PostgreSQL과 엔진은 `docker-compose.yml`(`docker compose up -d db`, 엔진까지는 `--profile app`).

**서버 타임아웃:** 실제 Azure로 잰 턴당 지연은 중앙값 4.4초, 최대 8.2초였다(`docs/perf/turn-latency.md`). 이 경로의 서버 타임아웃은 30초를 권한다. 타임아웃 뒤 다시 보내기 전에 `GET /cases/{id}`로 그 턴이 저장됐는지 확인한다.

 기존 개발 DB에는 `alembic upgrade head`(0004: `companies.external_id`, 0005: `document_values`, `documents.version`, `fact_records.revoked`)가 필요하다.
