# scrap-server ↔ 진단 엔진 내부 API 규약

scrap-server 담당자가 엔진(waste-diagnosis)을 부를 때 쓰는 규약이다. 필드 단위 정의는 `docs/api/openapi.json`(`/internal/v1` 경로 포함)이 기준이고, 이 문서는 경로·인증·오류 코드·페이징을 정한다. 요청·응답 본문의 의미와 흐름 예시는 `docs/api/api-spec.md`(5절)와 같다. 경로 앞에 `/internal/v1`만 붙는다.

> 표시: 본문에 "예정"이라 적은 항목은 이후 단계에서 추가한다. 지금은 호출할 수 없다.

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
| `POST /internal/v1/cases` | 건 만들기 + 문진 시작 `{memo?, quantity?, unit?, period?}` | 201 `{case, turn}` | 401, 400, 422 |
| `GET /internal/v1/cases?status=&page=&size=` | 내 기업의 건 목록(최근 갱신순, `summary` 포함) | 200 `{items, pagingInfo}` | 401, 400, 422 |
| `GET /internal/v1/cases/{id}` | 건 상세(현재 판정·이력·마지막 턴·서류·인계 객체·대화 기록) | 200 `CaseDetail` | 401, 404 |
| `POST /internal/v1/cases/{id}/diagnosis/messages` | 문진 답변 `{text}` 또는 `{quick_reply}` (둘 중 하나) | 200 `TurnResponse` | 404, 409 `CASE_NOT_DIAGNOSABLE`, 409 `CONCURRENT_UPDATE`, 422 |
| `POST /internal/v1/cases/{id}/documents` | 서류 업로드(multipart: `file`, 선택 `facts` JSON 문자열) | 201 `{document, turn}` | 404, 409, 413, 415, 422 |
| `POST /internal/v1/cases/{id}/confirm` | 확정 `{expected_code?}`. 서버가 지금 사실로 다시 평가한다 | 200 `{case, verdict, handoff, frozen_trace_rows}` | 404, 409 `NOT_CONFIRMABLE`·`ALREADY_CONFIRMED`·`CODE_MISMATCH` |
| `POST /internal/v1/cases/{id}/reopen` | 확정 건 다시 열기 `{reason?}` | 200 `{case, superseded_verdict, turn}` | 404, 409 `NOT_REOPENABLE` |
| `GET /internal/v1/cases/{id}/trace` | 근거 추적(세션·사실·턴·판정) | 200 `TraceOut` | 404 |
| `GET /internal/v1/catalog/facts` | 사실 카탈로그 요약(라벨·선택지) | 200 `CatalogFact[]` | 401 |
| `POST /internal/v1/cases/{id}/documents/{doc}/values/apply` | 검수 완료된 서류 값 적용 | (예정) | |
| `POST /internal/v1/cases/{id}/documents/{doc}/revoke` | 서류 효력 해제 | (예정) | |
| `POST /internal/v1/cases/{id}/rebase` | 현재 규칙 버전에 맞춰 다시 평가 | (예정) | `KB_CHANGED`와 한 쌍 |
| `DELETE /internal/v1/companies/{id}/data` | 기업 탈퇴 시 데이터 삭제(멱등) | (예정) | |

호출 순서: 건 생성 → (메시지·서류 반복) → 확정 → 필요하면 reopen → 다시 메시지·확정. 건 상태 전이는 `api-spec.md` 7절.

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
| 404 | `ENDPOINT_DISABLED` | prod에서 막힌 개발용 경로 | - |
| 404 / 405 | `NOT_FOUND` | 없는 경로(프레임워크 기본) | - |
| 409 | `CASE_NOT_DIAGNOSABLE` | 문진할 수 없는 상태(확정 건에 메시지·서류, 세션 없음). reopen 후 진행 | `case_status` |
| 409 | `ALREADY_CONFIRMED` | 이미 확정된 건을 다시 확정 | `case_status` |
| 409 | `NOT_CONFIRMABLE` | 아직 확정 조건을 채우지 못함 | `branch`, `reason`, `failure_reason` |
| 409 | `NOT_REOPENABLE` | 확정되지 않은 건을 reopen | `case_status` |
| 409 | `CODE_MISMATCH` | `expected_code`가 서버 재평가 결론과 다름 | `server_code`, `server_outcome` |
| 409 | `CONCURRENT_UPDATE` | 같은 건을 다른 요청이 먼저 갱신. 다시 `GET`하고 재시도 | - |
| 409 | `KB_CHANGED` | (예정) 저장된 규칙 버전과 현재 규칙이 다름. `rebase` 후 진행 | `session_kb_version`, `current_kb_version` |
| 413 | `FILE_TOO_LARGE` | 업로드가 `MAX_UPLOAD_BYTES`(기본 10MB) 초과 | - |
| 415 | `UNSUPPORTED_DOCUMENT` | 지원하지 않는 파일 형식 | - |
| 422 | `VALIDATION_ERROR` | 요청 형식 오류, 또는 서류 `facts` 값 오류 | 형식 오류: `errors[{loc,msg,type}]`. 서류 값: `problems[{key,…}]` |
| 5xx | `INTERNAL_ERROR` | 엔진 내부 오류 | - |

서버는 모르는 `code`를 받으면 HTTP 상태만으로 처리하고 `message`를 그대로 기록한다.

## 6. 설정(엔진 쪽)

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `APP_ENV` | `dev` | `dev` 또는 `prod` |
| `ENGINE_SERVICE_TOKEN` | 없음 | `/internal/v1` Bearer 토큰. prod 필수 |
| `DATABASE_URL` | SQLite | 운영은 PostgreSQL |
| `DB_CREATE_ALL` | `true` | 운영은 `false`로 두고 `alembic upgrade head` |
| `MAX_UPLOAD_BYTES` | 10485760 | 서류 업로드 상한 |

이미지는 `Dockerfile`(uvicorn, 포트 8030). 기존 개발 DB에는 `alembic upgrade head`(0004: `companies.external_id`)가 필요하다.
