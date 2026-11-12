# 서류 읽기 입출력 계약 (document-extraction-v1)

**이 문서는 계약만 정한다.** 서류에서 값을 읽어내는 구성요소(텍스트 해석, OCR, 프롬프트)는 구현하지 않고 나중으로 넘긴다. 지금의 업로드 흐름도 바꾸지 않는다. 계약 모델은 `app/domain/document.py`, 실행 가능한 검증은 `tests/test_document_contract.py`에 있다(이 문서의 JSON 예시를 테스트가 그대로 읽어 검증한다).

> 0005부터: 서류에서 온 값은 바로 EVIDENCED가 되지 않는다. 읽은 값도 사람이 입력한 값과 같이 **검수 대기 후보**(`document_values`, UNVERIFIED)로 저장하고, 서버가 검수 완료로 적용(`…/values/apply`)한 값만 EVIDENCED가 된다(`docs/api/server-engine-contract.md` 3.1절). 아래 흐름의 "Fact(EVIDENCED) 적재"는 "후보 저장 → 검수 → 적용"으로 읽는다. 자동 읽기 엔드포인트는 미구현이다.

## 1. 목적과 위치

```
업로드(POST /cases/{id}/documents)
  → 본문 추출(텍스트 층, 나중에 OCR)
  → [서류 읽기]  ← 이 계약: DocumentExtractionRequest → DocumentExtractionResult
  → 엔진 쪽 검증(§5, guard.py와 같은 원칙)
  → Fact(EVIDENCED, source_type=DOCUMENT) 적재
  → 규칙 엔진 재평가
```

서류 읽기는 **서류에 적힌 것을 구조화해 돌려주는 일**만 한다. 판정·추측·보정은 하지 않고, 어떤 값을 사실로 받을지는 엔진 쪽 검증이 정한다.

### 현재 Fact로의 대응
| 계약 | Fact |
|---|---|
| `facts[].key` | `key` |
| 정규화된 `value`(불검출·부등호는 `NumRange`) | `value` |
| 고정 | `status = EVIDENCED`, `source_type = "DOCUMENT"` |
| 요청의 `document.document_id` | `source_ref` |
| `facts[].quote` | `quote` |
| 불검출 설명, `note` | `note` |

FOUND가 아닌 항목(NOT_FOUND 등)은 Fact를 만들지 않는다. 이미 있던 사실을 지우거나 약화하지 않는다.

## 2. 입력: `DocumentExtractionRequest`

| 필드 | 설명 |
|---|---|
| `contract` | `"document-extraction-v1"` 고정 |
| `document.case_id`, `document_id`, `filename`, `content_type`, `sha256`(소문자 hex 64자), `size`(바이트), `uploaded_at`(시간대 포함 ISO 8601) | 업로드 메타데이터 |
| `content.text_pages[]` | `{page(1부터), text}`. 쪽 번호 단위로 나눈 추출 텍스트. 기본 입력 |
| `content.page_images[]` | **[미래·OCR]** `{page, content_type, ref}`. 텍스트 층이 없는 스캔본용. v1 구현은 쓰지 않아도 되며, 있으면 `text_pages`를 보완하는 용도다. 바이트를 싣지 않고 저장소 참조만 싣는다 |
| `content.tables[]` | (선택) 표 인식 층의 칸 단위 표(`TableGrid`, `app/domain/tables.py`). 형식은 `docs/design/test-report-table-extraction.md` 4절 |
| `content.page_count` | 원본 쪽 수(알면) |
| `doc_type_hint` | 카탈로그 `evidence_type` 중 하나(`TEST_REPORT`, `MSDS`, `EQUIPMENT_NAMEPLATE`, `EMISSION_FACILITY_PERMIT`, `CIRCULAR_RESOURCE_CERTIFICATE`, `WASTE_DISCHARGE_REPORT`, `CONSTRUCTION_CONTRACT`, `FACILITY_NOTIFICATION`, `DOCUMENT`) 또는 null. REQUEST_EVIDENCE가 요청한 유형이며 **힌트일 뿐**이다 |
| `requested_facts[]` | REQUEST_EVIDENCE의 `RequestedDocument.facts`를 카탈로그로 풀어 쓴 목록. 각 항목: `key`, `label`, `type`(`bool`/`enum`/`number`), `unit`, `allowed_values`(enum), `note`(기준값 등 판정 관련 힌트), `help`(카탈로그 help: 시험방법·확인할 값) |
| `catalog_subset[]` | 요청 외에도 읽어도 되는 사실(같은 서류 유형에서 얻을 수 있는 카탈로그 사실). 형식은 `requested_facts`와 같음. 비우면 덤으로 찾기를 하지 않는다 |
| `as_of` | 법 기준일(날짜). 날짜 상식 검사의 기준 |
| `case_context` | `material`(알면), `subject_hint`(대상 폐기물·시료 이름), `company_hint`. 다른 시료·회사 서류 판별에만 쓴다. 값을 채우는 근거로 쓰지 않는다 |

`requested_facts`의 `note`는 예를 들어 "0.3 mg/L 초과 여부로 갈림"처럼 **어느 값이 중요한지** 알려 주는 용도다. 읽기 구성요소는 이를 이유로 값을 기준 쪽으로 기울이면 안 된다.

## 3. 출력: `DocumentExtractionResult`

| 필드 | 설명 |
|---|---|
| `contract`, `document_id` | 계약 이름, 요청의 문서 id |
| `detected_doc_type` | 서류 종류 판별(위 9개 + `OTHER`) |
| `doc_type_confidence` | 0~1 |
| `attributes` | 서류 속성(아래) |
| `facts[]` | `requested_facts`의 **각 키마다 정확히 하나** |
| `not_requested_but_found[]` | `catalog_subset` 안에서 요청하지 않았지만 찾은 사실(FOUND만) |
| `warnings[]` | `{code, message, key?, page?}` |
| `errors[]` | `{code, message}`. 비어 있지 않으면 `facts`는 모두 비어 있어도 된다 |

### 서류 속성 `attributes`
`issuer`(발급·분석기관), `document_number`, `issued_on`(발급일), `sample_taken_on`(시료 채취일), `analysis_method`(예: `ES 06304.1`), `subject_name`(시료·품목명), `has_signature_or_seal`(서명·직인 유무, 모르면 null). 모두 서류에 없으면 null이다.

### 사실 항목 `facts[]` / `not_requested_but_found[]`
| 필드 | 설명 |
|---|---|
| `key` | 카탈로그 키 |
| `status` | `FOUND` 찾음 / `NOT_FOUND` 서류에 항목 없음 / `UNREADABLE` 있으나 글자를 읽을 수 없음 / `AMBIGUOUS` 후보 여럿·해석 갈림 |
| `value` | 카탈로그 타입·단위로 **정규화한 값**(bool, enum 값 문자열, 숫자). FOUND에서만. 불검출이면 null |
| `comparator` | `EQ`(기본) `LT` `LTE` `GT` `GTE`. `<0.1`이면 `LT` + `value 0.1` |
| `value_raw`, `unit_raw` | 서류에 적힌 그대로의 값·단위 |
| `page` | 근거가 있는 쪽(1부터). FOUND에서 필수 |
| `quote` | 서류 원문 발췌. FOUND에서 필수 |
| `method` | 서류에 적힌 시험방법 표기 |
| `sample_label` | 시료가 여럿일 때 어느 시료인지 |
| `below_detection_limit`, `detection_limit` | 불검출 여부, 정규화 단위의 검출한계. 불검출이면 `detection_limit` 필수, `value`는 null |
| `detection_limit_basis` | (선택) 검출한계의 출처. `stated`(서류에 적힌 검출한계, 기본) / `limit_column`(검출한계가 서류에 없어 같은 행 **기준 칸**의 값을 상한으로 씀, §5-5) |
| `note` | 읽기 구성요소의 짧은 메모 |
| `cell_ref`, `unit_ref`, `detection_limit_ref` | (선택) 값·단위·검출한계를 읽은 표 칸 `{page, table_index, row, col}`(검출한계는 각주 `{page, table_index, footnote_mark}`도 가능). 있으면 엔진이 표 구조로 다시 검증한다(설계 문서 6절 T1~T10) |

규칙
- FOUND가 아닌 항목에는 `value`·불검출을 넣지 않는다.
- 값을 서류에서 찾지 못했을 때 **추측해서 채우지 않는다.** `NOT_FOUND`로 낸다.
- `AMBIGUOUS`는 후보를 `note`에 적을 수 있지만 값을 고르지 않는다. 사용자에게 되묻는 것은 엔진 몫이다.

### 경고 코드
`SAMPLE_DATE_OLD` 시료 채취일이 오래됨 / `UNIT_CONVERSION_FAILED` 단위 환산 불가 / `UNIT_ASSUMED` 단위를 가정해 환산 / `DOC_TYPE_MISMATCH` 힌트와 판별 종류 불일치 / `DIFFERENT_SUBJECT` 다른 시료·회사로 보임 / `MULTIPLE_SAMPLES` 한 서류에 시료 여럿 / `NO_SIGNATURE_OR_SEAL` 서명·직인 없음 / `LOW_QUALITY` 읽기 품질 낮음 / `PARTIAL_DOCUMENT` 일부 쪽만 있는 듯함 / `METHOD_MISMATCH` 시험방법이 카탈로그 기준과 다름 / `COLUMN_ROLE_UNCERTAIN` 열 역할을 규칙으로 정하지 못함 / `VALUE_OUTSIDE_TABLE` 표가 있는데 표 밖에서 값을 읽음 / `TABLE_NOT_DETECTED` 표를 찾지 못함 / `TABLE_CONTINUATION_GUESSED` 쪽 넘김 표 잇기를 추정함

경고가 있어도 FOUND 값은 그대로 낸다. 받을지 말지는 엔진이 정한다(§5). 경고는 사용자 응답에 사실 그대로 전달할 수 있게 한국어 문장으로 쓴다.

### 오류 코드
`UNSUPPORTED_FORMAT`, `EMPTY_CONTENT`(본문이 비어 있음, OCR이 필요한 스캔본 포함), `DOCUMENT_UNREADABLE`, `SAMPLE_DATE_IN_FUTURE`, `ISSUED_BEFORE_SAMPLE`, `READER_FAILED`(내부 오류·시간 초과), `CONTRACT_VIOLATION`(출력이 계약 형식을 어김)

## 4. 서류 종류별로 돌려줄 수 있는 사실

현재 카탈로그 기준이다. 표에 없는 조합의 사실은 엔진이 버린다.

| doc_type | 돌려줄 수 있는 사실 키 | 비고 |
|---|---|---|
| `TEST_REPORT` | `sludge_water_pct`, `ph`, `oil_content_pct`, `pcb_mg_l`, `pcb_leach_mg_l`, `leach_pb`, `leach_cu`, `leach_as`, `leach_hg`, `leach_cd`, `leach_cr6`, `leach_cn`, `leach_op`, `leach_pce`, `leach_tce` | 카탈로그에서 `evidence_type: TEST_REPORT`인 사실. 모두 number |
| `MSDS` | `toxic_chemical_discard` | bool |
| `EQUIPMENT_NAMEPLATE` | `pcb_possible` | bool |
| `EMISSION_FACILITY_PERMIT` | `emission_facility` | bool |
| `CIRCULAR_RESOURCE_CERTIFICATE` | `circular_resource_recognized` | bool |
| `WASTE_DISCHARGE_REPORT` | `designated_waste_emitted`, `daily_avg_kg` | bool, number(kg/일) |
| `CONSTRUCTION_CONTRACT` | `work_total_ton` | number(톤) |
| `FACILITY_NOTIFICATION` | `sludge_facility_notified` | bool |
| `DOCUMENT` | 카탈로그 `evidence_type: DOCUMENT`인 사실 | 일반 증빙 |
| `OTHER` | 없음 | `facts`는 모두 NOT_FOUND |

표는 코드에 하드코딩하지 않고 카탈로그의 `evidence_type`에서 계산한다(§7). 위 목록은 현재 카탈로그를 읽은 결과다.

## 5. 엔진 쪽 검증 규칙

읽기 구성요소의 출력은 **엔진이 아래를 통과시킨 것만** Fact가 된다. 대화 추출 검증(`app/agent/guard.py`)과 같은 원칙이다. 실패한 항목은 버리고 사유를 기록(rejected)한다.

1. **카탈로그**: `key`가 카탈로그에 있고 `requested_facts` 또는 `catalog_subset`에 있어야 한다. 같은 키를 두 번 내면 거부. 서류 종류 표(§4)에 없는 조합은 거부.
2. **타입·값 영역**: `coerce_value`와 같은 기준. bool은 true/false, enum은 `allowed_values` 안, number는 숫자 또는 구간.
3. **quote**: FOUND는 `quote`가 비어 있지 않고, 공백을 무시하고 비교했을 때 **`page`로 지정한 쪽의 본문에 실제로 있어야** 한다.
4. **수치**: 숫자는 `value_raw`(없으면 `value`)의 숫자 표기가 `quote` 안에 있어야 한다(쉼표 제거, `1.50`/`1.5` 표기 차이 허용). 환산한 `value`는 `value_raw`·`unit_raw`와 단위 정규화 표로 다시 계산해 일치해야 한다(상대오차 1e-6). 지어낸 숫자는 거부.
5. **불검출**: `quote`에 `불검출`, `ND`, `N.D.`, `검출되지 않음`, `불검출(<0.01)` 중 하나가 있어야 한다. `detection_limit`는 quote에 숫자로 나오면 그 값과 같아야 하고, 나오지 않으면 같은 행 **기준 칸**에 "이 값 이상이면 해당"인 숫자가 하나 있을 때(`3.0 이상`, `3`, `5% 초과`) 그 값을 `detection_limit`로 쓰고 `detection_limit_basis = "limit_column"`, `detection_limit_ref`는 그 기준 칸으로 낸다(불검출은 "기준보다 낮다"는 뜻으로만 쓴다). 기준 칸도 없거나 `2.0 이하`처럼 낮을수록 해당하는 기준, 숫자가 여럿인 기준이면 **FOUND가 아니라 `AMBIGUOUS`로 낸다**. 어떤 경우에도 불검출을 `0`으로 내지 않는다.
6. **부등호·구간**: `<0.1`, `0.1 미만` 같은 표기는 `comparator`로 낸다. 값을 `0.1`로 뭉개거나 `0`으로 바꾸지 않는다.
7. **시료가 여럿**: 한 서류에 시료가 여럿이고 `case_context.subject_hint`로 하나를 고를 수 없으면 해당 항목은 `AMBIGUOUS`, `MULTIPLE_SAMPLES` 경고. 하나로 좁혀지면 `sample_label`을 채운다.
8. **날짜 상식**(`as_of` 기준):
   - `sample_taken_on > as_of` → 오류 `SAMPLE_DATE_IN_FUTURE`, 모든 항목 거부
   - `issued_on < sample_taken_on` → 오류 `ISSUED_BEFORE_SAMPLE`, 모든 항목 거부
   - 시료 채취일이 `as_of`보다 365일 넘게 앞섬 → 경고 `SAMPLE_DATE_OLD`(값은 받는다. 기간 기준은 설정으로 둔다)
9. **다른 대상**: `DIFFERENT_SUBJECT` 경고가 있으면 엔진은 **값을 EVIDENCED로 올리지 않고** 사용자에게 서류가 이 건의 것인지 확인한다(미정: §8).
10. **서류 종류**: `detected_doc_type`이 `doc_type_hint`와 다르면 `DOC_TYPE_MISMATCH` 경고. 항목은 *판별된* 종류의 허용 표(§4)로 검사한다.
11. **서명·직인 없음**은 경고만 하고 값은 받는다.

### 단위 정규화
`value`는 카탈로그 `unit`으로 환산해 낸다. 환산은 아래 표에 있는 것만 허용한다.

| 서류 표기 | 카탈로그 단위 | 환산 |
|---|---|---|
| `mg/L`, `mg/l`, `㎎/L`, `mg/ℓ` | mg/L | ×1 |
| `μg/L`, `µg/L`, `ug/L`, `ppb`(액상) | mg/L | ×0.001 |
| `g/L` | mg/L | ×1000 |
| `ppm` | mg/L | ×1, 용출액·액상 시료일 때만. 경고 `UNIT_ASSUMED` |
| `%`, `wt%`, `중량%`, `% (w/w)` | % | ×1 |
| `mg/kg` | % | ÷10000 |
| `ppm`(고상) | % | ÷10000. 경고 `UNIT_ASSUMED` |
| `kg/일`, `kg/day` | kg/일 | ×1 |
| `톤/일`, `t/day` | kg/일 | ×1000 |
| `톤`, `t`, `ton` | 톤 | ×1 |
| `kg` | 톤 | ÷1000 |
| (pH는 단위 없음) | — | — |

표에 없는 단위, 부피↔질량 환산이 필요한 경우(밀도가 필요), 기간이 다른 경우(`톤/년` → `kg/일`은 가동일수를 모른다)는 환산하지 않는다. 항목은 `UNREADABLE`이 아니라 **`AMBIGUOUS`**, `value`는 null, `value_raw`·`unit_raw`는 남기고 경고 `UNIT_CONVERSION_FAILED`를 낸다. 값을 지어내서 맞추지 않는다.

### 불검출(ND)의 표현
불검출은 **0이 아니다.** `below_detection_limit = true` + `detection_limit`로 내고, 엔진은 `NumRange(hi=detection_limit, hi_inc=False)`(검출한계 미만)로 저장한다. `note`에는 `불검출(검출한계 0.01)`이 붙는다. 같은 규칙이 기존 구간 평가(`range_satisfies`)에 그대로 올라타므로, 기준값이 검출한계보다 크면 "기준 미만"이 참으로, 작으면 판단 보류로 평가된다. 검출한계가 서류에 없으면 같은 행 기준값을 상한으로 쓴다(§5-5, `note` `불검출. 검출한계가 없어 같은 행 기준 3.0 미만으로 봄`). 엔진 규칙의 기준선이 그 값 이상이면 "기준 미만"이 참이고, 더 낮으면 판단 보류라 다시 묻는다. 그래서 0으로 넣을 때와 달리 서류에 없는 값을 만들지 않고, 판정을 잘못 내리지도 않는다. 기준값도 쓸 수 없는 ND는 `AMBIGUOUS`다.

## 6. 오류·경계 사례

| 상황 | 처리 |
|---|---|
| 본문이 비어 있음(스캔본) | `errors: EMPTY_CONTENT`, facts 비움. 나중에 OCR이 생기면 이 경우만 이미지를 쓴다 |
| 암호화·손상 PDF | `errors: DOCUMENT_UNREADABLE` |
| 요청한 값이 서류에 없음 | 해당 키 `NOT_FOUND` |
| 값은 보이는데 글자가 깨짐 | `UNREADABLE` (+ `LOW_QUALITY` 경고) |
| 같은 항목이 서로 다른 값으로 두 번 | `AMBIGUOUS`, 후보를 `note`에 |
| 일부 쪽만 있는 듯함(쪽 번호 `3/5` 등) | `PARTIAL_DOCUMENT` 경고 |
| 힌트와 다른 종류의 서류 | `DOC_TYPE_MISMATCH`, 판별 종류 기준으로 읽는다 |
| 출력이 모델을 어김 | 엔진은 전체를 `CONTRACT_VIOLATION`으로 처리하고 Fact를 만들지 않는다 |
| 읽기 구성요소 실패·시간 초과 | `errors: READER_FAILED`. 업로드 자체는 성공으로 두고 사실은 만들지 않는다 |

같은 서류를 다시 읽으면(`sha256` 동일) 결과를 재사용할 수 있다. 읽기는 입력이 같으면 같은 구조의 결과를 내야 하며, 엔진의 평가는 결과에만 의존한다.

## 7. 버전
- 계약 이름 `document-extraction-v1`을 요청·결과 모두 `contract`에 싣는다. 모르는 필드가 오면 거부한다(`extra=forbid`).
- 필드·코드 **추가**는 같은 버전에서 선택 필드로만 한다. 기존 필드의 뜻 변경·삭제·필수화는 `v2`다.
- §4의 허용 표는 계약이 아니라 카탈로그의 파생물이다. 카탈로그가 바뀌면 표도 따라 바뀐다.

## 8. 예시

### 8-1. 요청 (TEST_REPORT)
```json
{
  "contract": "document-extraction-v1",
  "document": {
    "case_id": "case-1",
    "document_id": "doc-1",
    "filename": "시험성적서_2026-0412.pdf",
    "content_type": "application/pdf",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size": 184320,
    "uploaded_at": "2026-11-08T09:15:00+09:00"
  },
  "content": {
    "text_pages": [
      {
        "page": 1,
        "text": "시험성적서 성적서번호 2026-0412 분석기관 (주)한국환경분석 시료명 폐유 슬러지 시료채취일 2026-10-20 발급일 2026-10-27"
      },
      {
        "page": 2,
        "text": "수소이온농도(pH) ES 06304.1 7.2 기름성분 ES 06302.1b 3.5 % 납 용출 불검출 (검출한계 0.01 mg/L) 직인"
      }
    ],
    "page_count": 2
  },
  "doc_type_hint": "TEST_REPORT",
  "requested_facts": [
    {"key": "ph", "label": "pH", "type": "number", "note": "수소이온농도(pH) ES 06304.1"},
    {"key": "oil_content_pct", "label": "기름성분 함량", "type": "number", "unit": "%"},
    {"key": "leach_pb", "label": "납 용출 농도", "type": "number", "unit": "mg/L"}
  ],
  "catalog_subset": [
    {"key": "leach_cu", "label": "구리 용출 농도", "type": "number", "unit": "mg/L"}
  ],
  "as_of": "2026-11-08",
  "case_context": {"material": "sludge", "subject_hint": "폐유 슬러지"}
}
```

### 8-2. 결과 (TEST_REPORT: pH, 기름성분, 납 용출 불검출)
```json
{
  "contract": "document-extraction-v1",
  "document_id": "doc-1",
  "detected_doc_type": "TEST_REPORT",
  "doc_type_confidence": 0.97,
  "attributes": {
    "issuer": "(주)한국환경분석",
    "document_number": "2026-0412",
    "issued_on": "2026-10-27",
    "sample_taken_on": "2026-10-20",
    "analysis_method": "ES 06304.1",
    "subject_name": "폐유 슬러지",
    "has_signature_or_seal": true
  },
  "facts": [
    {
      "key": "ph",
      "status": "FOUND",
      "value": 7.2,
      "value_raw": "7.2",
      "page": 2,
      "quote": "수소이온농도(pH) ES 06304.1 7.2",
      "method": "ES 06304.1"
    },
    {
      "key": "oil_content_pct",
      "status": "FOUND",
      "value": 3.5,
      "value_raw": "3.5",
      "unit_raw": "%",
      "page": 2,
      "quote": "기름성분 ES 06302.1b 3.5 %",
      "method": "ES 06302.1b"
    },
    {
      "key": "leach_pb",
      "status": "FOUND",
      "value": null,
      "value_raw": "불검출",
      "unit_raw": "mg/L",
      "page": 2,
      "quote": "납 용출 불검출 (검출한계 0.01 mg/L)",
      "below_detection_limit": true,
      "detection_limit": 0.01
    }
  ],
  "not_requested_but_found": [],
  "warnings": [],
  "errors": []
}
```
엔진 변환 결과: `ph=7.2`, `oil_content_pct=3.5`, `leach_pb=NumRange(hi=0.01, hi_inc=False)`(note `불검출(검출한계 0.01)`). 모두 EVIDENCED·DOCUMENT·`source_ref=doc-1`.

### 8-3. 결과 (MSDS)
```json
{
  "contract": "document-extraction-v1",
  "document_id": "doc-2",
  "detected_doc_type": "MSDS",
  "doc_type_confidence": 0.9,
  "attributes": {
    "issuer": "(주)예시화학",
    "issued_on": "2025-03-02",
    "subject_name": "세정제 A",
    "has_signature_or_seal": null
  },
  "facts": [
    {
      "key": "toxic_chemical_discard",
      "status": "FOUND",
      "value": true,
      "value_raw": "해당",
      "page": 3,
      "quote": "유독물질 해당 여부: 해당",
      "note": "15. 법적 규제 현황 항목"
    }
  ],
  "not_requested_but_found": [],
  "warnings": [
    {"code": "NO_SIGNATURE_OR_SEAL", "message": "서명이나 직인을 확인할 수 없습니다."}
  ],
  "errors": []
}
```

## 9. 현재 구현과의 차이 / 나중에 구현할 것

| 항목 | 지금 | 나중에 |
|---|---|---|
| 읽기 방식 | 대화 추출기(`extractor.py`)를 재사용. 본문 한 덩어리, 쪽 번호 없음 | 이 계약의 요청·결과로 별도 구성요소 |
| 쪽 번호 | 없음(텍스트를 `\n\n`으로 이어 붙임) | `text_pages`로 쪽 단위 유지. 기존 `_pdf_text`가 쪽별 목록을 돌려주도록 바꿔야 함 |
| 불검출·부등호 | 대화의 구간 표현(`range`)만 | `comparator`·`below_detection_limit` |
| 단위 환산 | 없음. LLM이 값을 알아서 맞춤 | §5 표 기준 환산 + 재계산 검증 |
| 서류 속성·날짜 검사·경고 | 없음 | `attributes`, §5-8, 경고 코드 |
| 항목별 NOT_FOUND/AMBIGUOUS | 못 찾은 키는 그냥 빠짐 | 요청한 키마다 상태를 반환 |
| 서류 종류 판별 | 없음(요청 유형을 믿음) | `detected_doc_type` + 불일치 경고 |
| OCR | 시험성적서 시험 구현: `app/reading/`(pdfplumber 로컬 + Azure layout, `ALLOW_DOCUMENT_OCR`). 업로드 흐름에는 아직 연결하지 않음 | `page_images` 또는 `tables` |
| `facts` 폼 필드(LLM 끔) | 사람이 값을 넣음 | 유지 가능: 같은 검증기를 통과시키는 대체 입력 경로 |
| 엔진 쪽 검증기 | 없음(`guard.validate_extraction`을 공유) | §5를 구현한 `validate_document_extraction` |
| 요청 만들기 | 없음 | `RequestedDocument` → `RequestedFact` 변환(카탈로그 + 규칙의 기준값 note) |
| `DIFFERENT_SUBJECT` 처리 | 없음 | 사용자 확인 질문 흐름(결정 필요) |

이 계약은 `to_fact_records`로 현재 `Fact` 모델에 바로 옮겨지므로, 위 구성요소가 준비되면 업로드 서비스는 추출기 호출부만 갈아끼우면 된다.
