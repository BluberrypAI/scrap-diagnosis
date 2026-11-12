# 시험성적서 표 인식 설계 (제안)

시험성적서를 읽을 때 글자만 뽑지 않고 **표 구조(행·열·병합 칸)까지 인식**해서, 값이 어느 칸에서 왔는지를 검증할 수 있게 하는 설계다.
[서류 읽기 계약](../document-extraction-contract.md)(`document-extraction-v1`)의 "읽기 구성요소"를 어떻게 만들지에 대한 제안이며, 계약은 선택 필드 추가로만 넓힌다.

- 작성: 2026-11-11
- 상태: **시험 구현**(13절). 엔진 선택과 운영 연결은 실제 성적서 샘플로 비교한 뒤 정한다(10절)
- 범위: `TEST_REPORT`의 사실 15개(`sludge_water_pct`, `ph`, `oil_content_pct`, `pcb_mg_l`, `pcb_leach_mg_l`, `leach_*` 10개). MSDS·명판 등은 같은 틀을 나중에 재사용한다

## 1. 왜 표 구조가 필요한가

시험성적서의 결과는 거의 항상 표에 있다. 글자만 이어 붙이면 숫자는 남지만 **숫자와 칸의 관계**가 사라진다.

| 문제 | 예 | 글자만 뽑았을 때 |
|---|---|---|
| 결과 칸과 기준 칸 혼동 | `납 \| ES … \| 0.12 \| mg/L \| 3 이하` | 0.12와 3 중 무엇이 결과인지 모름 |
| 판정 칸 | `… \| 0.12 \| 적합` | "적합"을 사실로 오해할 수 있음 |
| 시료 여럿 | 시료 A·B·C가 열로 나란히 있음 | 어느 열이 이 폐기물인지 모름 |
| 병합된 칸 | "용출시험" 칸이 여러 행에 걸침 | 납이 용출인지 함량인지 모름 |
| 단위가 머리글에만 있음 | 열 제목이 `결과(mg/L)` | 값 칸에는 단위가 없음 |
| 각주 | 결과 칸은 `ND`, 검출한계는 표 아래 `* 검출한계 0.01 mg/L` | 검출한계를 놓쳐 `AMBIGUOUS` |
| 쪽 넘김 | 표가 다음 쪽으로 이어지며 머리글이 반복되지 않음 | 다음 쪽 값의 열 의미를 모름 |

**지금 계약의 빈틈:** §5-4 검증은 "숫자 표기가 `quote` 안에 있나"만 본다. 위 첫 줄에서 결과로 3을 냈다면, 3도 quote 안에 있으므로 통과한다. 기준값과 같은 숫자를 결과로 받는 것은 **지정폐기물 판정을 정반대로 뒤집는 오류**다. 따라서 가장 먼저 막아야 한다.

## 2. 원칙

1. **값은 반드시 표의 한 칸을 가리킨다.** 읽기 구성요소는 값을 쓸 때 근거 칸의 좌표(`cell_ref`)를 함께 낸다. 검증은 문자열 포함 여부가 아니라 표 구조로 한다.
2. **열의 역할(결과·기준·방법·단위 등)은 가능한 한 규칙으로 정한다.** LLM이 정한 열 역할은 "불확실"로 표시한다.
3. **결과로 받을 수 있는 칸은 "결과" 역할 열의 칸뿐이다.** 기준·판정·방법 열의 숫자는 어떤 경우에도 값이 되지 않는다.
4. 계약 원칙을 그대로 따른다. 추측하지 않고, 불검출은 0이 아니며, 서류에서 읽은 값은 검수 전까지 `UNVERIFIED` 후보로 둔다.
5. 데이터 정책을 따른다. 칸의 글자도 LLM에 보내기 전에 `redact.py`로 가린다. 원본 이미지를 외부 OCR로 보내는 일은 9절의 결정이 날 때까지 하지 않는다.

## 3. 전체 흐름

```
업로드(PDF·스캔·사진)
 │
 ├─ ① 표 인식 층 (결정적, LLM 없음)
 │     글자 있는 PDF → 로컬 표 추출
 │     스캔·사진·표 추출 실패 → OCR 표 인식(9절 결정 후)
 │     → TableGrid[] (칸 단위, 병합 펼침, 쪽 넘김 이음, 각주 수집)
 │
 ├─ ② 열 역할 판정 (규칙 우선)
 │     머리글 사전으로 RESULT / LIMIT / METHOD / UNIT / ITEM / JUDGEMENT / SAMPLE …
 │     못 정한 열 → LLM 보조 + COLUMN_ROLE_UNCERTAIN
 │
 ├─ ③ 대응 층 (LLM)
 │     가린 표 + requested_facts → 키마다 cell_ref, value_raw, unit_raw
 │
 ├─ ④ 엔진 검증 (기존 §5 + 6절의 표 규칙)
 │
 └─ ⑤ 검수 대기 후보(UNVERIFIED) → 사람 검수 → EVIDENCED
```

①과 ②는 같은 입력이면 같은 출력이 나와야 한다(계약 §6의 재현성). LLM은 ③에만 쓴다.

## 4. ① 표 인식 층

### 출력 형식: `TableGrid`

```json
{
  "page": 2,
  "table_index": 0,
  "continued_from": null,
  "n_rows": 14,
  "n_cols": 6,
  "cells": [
    {"row": 0, "col": 0, "text": "시험항목", "row_span": 1, "col_span": 1, "is_header": true, "bbox": [72.1, 140.3, 160.0, 155.2]},
    {"row": 5, "col": 0, "text": "용출시험", "row_span": 8, "col_span": 1, "is_header": false, "bbox": [...]},
    {"row": 5, "col": 1, "text": "납(Pb)", "row_span": 1, "col_span": 1, "is_header": false, "bbox": [...]},
    {"row": 5, "col": 3, "text": "ND", "row_span": 1, "col_span": 1, "is_header": false, "bbox": [...], "footnote_marks": ["*"]}
  ],
  "footnotes": [{"mark": "*", "text": "검출한계 0.01 mg/L"}],
  "source": "pdf_text_layer",
  "quality": {"ocr_confidence_min": null}
}
```

- 좌표는 `(page, table_index, row, col)`이다. 병합 칸은 왼쪽 위 칸에 글자를 두고, 대응 층과 검증에는 **펼친 격자**(병합 범위의 모든 칸이 같은 글자를 가짐)를 쓴다.
- `continued_from`: 앞 쪽 표가 이어지는 경우 그 표의 좌표. 판단 기준은 열 개수와 열 위치(bbox x)가 같고, 머리글 행이 없다는 것. 이어진 표는 앞 표의 머리글과 열 역할을 물려받는다.
- `footnotes`: 표 바로 아래의 `*`, `※`, `주)`, `1)` 등으로 시작하는 줄. 칸의 같은 표시와 연결한다.
- `source`: `pdf_text_layer` / `ocr` 중 하나. `ocr`이면 칸마다 `confidence`를 둔다.
- 표 밖의 글자(성적서 번호, 발급일, 시료명, 분석기관)는 지금처럼 `text_pages`로 넘긴다. `attributes`는 여기서 읽는다.

### 입력별 경로

| 입력 | 1차 | 2차(실패 시) | 비고 |
|---|---|---|---|
| 글자 있는 PDF (분석기관 시스템 출력) | 로컬 표 추출: pdfplumber 또는 PyMuPDF의 표 찾기. 괘선 기반, 실패하면 글자 위치로 열을 군집 | OCR 표 인식 | 대부분 여기서 끝날 것으로 **예상**(샘플로 확인 필요) |
| 스캔 PDF (글자 없음) | OCR 표 인식 | - | 지금은 `EMPTY_CONTENT` 오류 |
| 휴대폰 사진 | 기울기·원근 보정 후 OCR 표 인식 | - | 품질이 가장 낮다. `LOW_QUALITY` 경고 기준을 따로 둔다 |

### OCR 표 인식 후보 (비교 대상)

| 후보 | 표 구조 | 실행 위치 | 확인할 것 |
|---|---|---|---|
| Azure AI Document Intelligence (layout 모델) | 행·열·병합 범위 제공 | Azure (지금 LLM과 같은 클라우드) | 한국어 표 품질, 리전, 비용, 데이터 보관 조건 |
| PaddleOCR PP-Structure | 표를 HTML로 출력 | 로컬 | 한국어 인식 품질, 설치·운영 부담(GPU 여부) |
| 국내 상용 문서 인식 API | 표 지원 | 외부 업체 | 새 외부 업체라 데이터 정책 검토가 따로 필요 |

멀티모달 LLM에 이미지를 바로 넣는 방식은 ① 층으로 쓰지 않는다. 칸 좌표가 없어 6절 검증을 할 수 없고, 숫자를 지어낼 위험을 구조로 막을 수 없기 때문이다.

## 5. ② 열 역할 판정

### 역할

| 역할 | 뜻 | 머리글 예 (사전 초안, 샘플로 보완) |
|---|---|---|
| `ITEM` | 시험 항목명 | 시험항목, 분석항목, 항목, 검사항목 |
| `GROUP` | 항목 묶음(용출·함량) | 구분, 시험구분 (또는 병합된 왼쪽 칸) |
| `METHOD` | 시험방법 | 시험방법, 분석방법, 시험기준 |
| `RESULT` | 결과값 | 결과, 시험결과, 분석결과, 측정값, 결과치 |
| `UNIT` | 단위 | 단위 |
| `LIMIT` | 법적 기준·허용 기준 | 기준, 기준치, 기준값, 법적기준, 지정폐기물 기준, 허용기준 |
| `DETECTION_LIMIT` | 검출한계·정량한계 | 검출한계, 정량한계, MDL, LOQ |
| `JUDGEMENT` | 판정 | 판정, 적합여부, 비고 |
| `SAMPLE` | 시료별 결과 열 | 시료명이 머리글인 결과 열(시료 A, 시료 1, 시료 번호) |

- 머리글에 단위가 붙은 경우(`결과(mg/L)`)는 역할 `RESULT`와 열 단위 `mg/L`로 나눈다.
- 결과 열이 시료마다 여럿이면 각각 `RESULT` + `sample_label`이다.
- 규칙으로 정하지 못한 열은 LLM에 역할을 묻는다. 이때 그 열에서 나온 값에는 `COLUMN_ROLE_UNCERTAIN` 경고가 붙고, **값을 `FOUND`로 내지 않고 `AMBIGUOUS`로 낸다.** 사전이 쌓이면 이 경우가 줄어든다.

### 항목명 사전

사실 키와 성적서 항목 표기를 잇는 사전이다. 법 판단을 담지 않으므로 `knowledge/test_items.yaml`(신설 제안)에 두고 빌드로 복사한다.

| 키 | 항목 표기 예 | 묶음(GROUP) 조건 |
|---|---|---|
| `leach_pb` | 납, Pb, 납 및 그 화합물 | 용출 |
| `leach_cu` | 구리, Cu, 구리 및 그 화합물 | 용출 |
| `leach_as` | 비소, As, 비소 및 그 화합물 | 용출 |
| `leach_hg` | 수은, Hg, 수은 및 그 화합물 | 용출 |
| `leach_cd` | 카드뮴, Cd, 카드뮴 및 그 화합물 | 용출 |
| `leach_cr6` | 6가크롬, 육가크롬, Cr6+, Cr(VI) | 용출 |
| `leach_cn` | 시안, CN, 시안화합물 | 용출 |
| `leach_op` | 유기인, 유기인화합물 | 용출 |
| `leach_pce` | 테트라클로로에틸렌, PCE | 용출 |
| `leach_tce` | 트리클로로에틸렌, TCE | 용출 |
| `pcb_leach_mg_l` | PCB, 폴리클로리네이티드비페닐 | 용출 |
| `pcb_mg_l` | PCB, 폴리클로리네이티드비페닐 | 함량(액상) |
| `oil_content_pct` | 기름성분, 노말헥산 추출물질 | 함량 |
| `sludge_water_pct` | 수분, 함수율, 수분함량 | 함량 |
| `ph` | pH, 수소이온농도 | - |

같은 원소가 용출과 함량 두 행에 모두 있으면 `GROUP`(병합 칸이나 묶음 머리글)으로 가른다. `GROUP`을 정하지 못하면 단위로 보조한다(용출은 mg/L, 함량은 mg/kg 또는 %). 그래도 못 가르면 `AMBIGUOUS`다.

## 6. ③ 대응 층과 ④ 검증

### 대응 층(LLM)의 입력과 출력
- 입력: 가린 `TableGrid`(칸 글자만, bbox 제외), 열 역할, 각주, `requested_facts`, `case_context.subject_hint`
- 출력: 기존 `facts[]`에 다음 선택 필드를 더한다(8절)
  - `cell_ref`: 값 칸 `{page, table_index, row, col}`
  - `unit_ref`: 단위를 읽은 칸(단위 열 칸, 머리글 칸, 또는 값 칸 자체)
  - `detection_limit_ref`: 검출한계를 읽은 칸이나 각주
- `quote`는 유지한다. 값 칸이 속한 **행의 칸 글자를 ` | `로 이은 문자열**로 정한다. 검수 화면에 그대로 보여 줄 수 있다.

### 표 검증 규칙 (기존 §5에 더함)

`cell_ref`가 있는 항목에는 아래를 모두 적용한다. 하나라도 실패하면 그 항목을 거부하고 사유를 기록한다.

| 번호 | 규칙 | 막는 오류 |
|---|---|---|
| T1 | `cell_ref`가 실제 표의 칸이다 | 지어낸 좌표 |
| T2 | 그 칸의 글자에 `value_raw`가 있다(쉼표·공백 정리 후, 기존 §5-4 표기 허용 동일) | 지어낸 숫자 |
| T3 | 그 칸의 열 역할이 `RESULT`다. `LIMIT`·`JUDGEMENT`·`METHOD`·`DETECTION_LIMIT` 열이면 거부 | **기준값을 결과로 받음** |
| T4 | 같은 행의 `ITEM` 칸이 그 키의 항목명 사전과 맞는다 | 다른 항목의 값을 받음 |
| T5 | 그 행의 `GROUP`(펼친 병합 칸 포함)이 사전의 묶음 조건과 모순되지 않는다 | 용출과 함량 혼동 |
| T6 | 결과 열이 시료별로 여럿이면 열의 `sample_label`이 하나로 정해져 있다. 아니면 `AMBIGUOUS` + `MULTIPLE_SAMPLES` | 다른 시료의 값 |
| T7 | `unit_raw`가 `unit_ref` 칸에 실제로 있다. 단위 환산은 기존 §5 표대로 | 단위를 지어냄 |
| T8 | 불검출이면 `detection_limit`가 같은 행의 `DETECTION_LIMIT` 칸, 값 칸의 각주, 또는 표 전체 각주 중 하나에 있어야 한다. 없으면 `AMBIGUOUS`(기존 §5-5) | 검출한계를 지어냄 |
| T9 | 같은 키에 T1~T5를 통과하는 칸이 둘 이상이고 값이 다르면 `AMBIGUOUS` | 중복 항목 중 하나를 임의로 고름 |
| T10 | 열 역할이 LLM으로 정해진 열(`COLUMN_ROLE_UNCERTAIN`)에서 온 값은 `AMBIGUOUS` | 열 역할 오판 |

`cell_ref`가 없는 항목(표 밖 본문에 값이 있는 경우)은 기존 §5 규칙만 적용한다. 다만 `TEST_REPORT`에서 표가 하나 이상 인식됐는데도 `cell_ref` 없이 값을 낸 경우에는 경고 `VALUE_OUTSIDE_TABLE`을 붙여 검수 화면에서 눈에 띄게 한다.

## 7. 검수 화면에 주는 것

사람 검수가 최종 관문이므로, 검수자가 원본과 빠르게 대조할 수 있어야 한다.

- 값마다 원본 쪽 이미지에서 `cell_ref` 칸의 `bbox`를 강조
- 같은 행 전체(`quote`), 열 머리글, 검출한계 출처
- 경고(`COLUMN_ROLE_UNCERTAIN`, `MULTIPLE_SAMPLES`, `VALUE_OUTSIDE_TABLE`, `LOW_QUALITY`)

화면은 이 레포 담당이 아니다. 엔진은 `bbox`와 좌표를 응답에 싣기만 하고, 화면 형식은 `docs/ui/ui-contract.md`에 필드를 추가할 때 함께 정한다.

## 8. 계약 확장안 (`document-extraction-v1`, 선택 필드 추가만)

계약 §7에 따라 기존 필드의 뜻은 바꾸지 않고 선택 필드만 더한다.

| 위치 | 추가 필드 | 설명 |
|---|---|---|
| 요청 `content` | `tables[]` | `TableGrid` 목록(4절). 있으면 대응 층이 쓴다 |
| 결과 `facts[]`, `not_requested_but_found[]` | `cell_ref`, `unit_ref`, `detection_limit_ref` | 6절. `{page, table_index, row, col}` 또는 각주 `{page, table_index, footnote_mark}` |
| 경고 코드 | `COLUMN_ROLE_UNCERTAIN`, `VALUE_OUTSIDE_TABLE`, `TABLE_NOT_DETECTED`, `TABLE_CONTINUATION_GUESSED` | 마지막 두 개는 표를 못 찾음, 쪽 넘김 이음을 추정함 |
| 오류 처리 | `EMPTY_CONTENT`의 뜻 | 바꾸지 않는다. OCR이 생기면 스캔본은 `tables[]`로 들어오므로 이 오류에 닿지 않는다 |

바꿔야 할 코드: `app/domain/document.py`(모델), `tests/test_document_contract.py`(예시 검증), 그리고 계약 문서 §2·§3·§5·§9. 계약 문서 경로는 바꾸지 않는다.

## 9. 데이터 정책

| 단계 | 외부로 나가는 것 | 처리 |
|---|---|---|
| ① 로컬 표 추출 | 없음 | - |
| ① OCR 표 인식(Azure) | **원본 쪽 이미지**: 회사명, 사업자번호, 담당자, 직인이 그대로 있음 | 아래 "2026-11-11 판단" 참고 |
| ③ 대응 층(LLM) | 가린 칸 글자 | 기존 `ALLOW_DOCUMENT_LLM`과 `redact.py`를 그대로 적용. 칸마다 가린 뒤 보낸다. T2 검증은 가린 글자 기준이며, 수치는 가리지 않으므로 영향이 없다 |
| Trace | 표 | `trace_store_prompts=false`이면 해시와 길이만 남긴다. `TableGrid` 원문을 Trace에 통째로 넣지 않는다 |

**2026-11-11 판단: Azure OCR로 원본을 보내는 것은 서버에 올리는 것과 같은 수준으로 본다.** 엔진 서버와 업로드 저장소가 이미 Azure에 있으므로, 원본은 업로드 순간부터 Azure에 있다. 로컬 OCR을 써도 그 "로컬"은 Azure 서버다. 따라서 OCR 엔진 선택은 데이터 위치가 아니라 품질과 비용으로 정한다. 다만 다음 조건을 지킨다.

- Document Intelligence 리소스는 엔진 서버와 **같은 구독, 같은 리전**에 둔다(가능하면 Korea Central).
- 설정 `ALLOW_DOCUMENT_OCR`(기본 false)로 켜고 끌 수 있게 한다. 개발·시험 환경에서 실수로 과금되거나 원본이 나가는 일을 막기 위해서다.
- 개인정보 처리방침의 수탁자·처리 목적에 "문서 인식"이 포함되는지 확인한다. 이 레포 범위 밖이므로 담당자에게 전달한다.
- `docs/llm-data-policy.md`에 "LLM에 보내는 글자는 가리고, 같은 리전의 Azure 문서 인식에는 원본을 보낸다"는 구분을 적는다(정책 문서이므로 승인 후 반영).

## 10. 평가 계획

샘플 없이 엔진을 고르지 않는다.

1. **정답셋**: 서로 다른 분석기관 양식의 성적서 10~20장. 글자 있는 PDF, 스캔본, 휴대폰 사진을 모두 포함한다. 회사·담당자 정보를 가린 뒤 레포 밖에 보관하고, 정답(키, 값, 불검출, 검출한계, 칸 좌표)만 `data/golden/`에 둘지 정한다.
2. **측정**

| 지표 | 뜻 | 목표 |
|---|---|---|
| 표 검출률 | 결과 표를 찾은 문서 비율 | 높을수록 |
| 칸 정확도 | 목표 값의 칸을 맞게 찾은 비율 | 높을수록 |
| **오수용률** | 검증을 통과했는데 값이 틀린 비율 | **0** (하나라도 있으면 원인을 막을 규칙을 더함) |
| 보류율 | `AMBIGUOUS`·`NOT_FOUND`로 사람에게 넘어간 비율 | 낮을수록. 다만 오수용률보다 우선하지 않음 |

3. **비교 대상**: 로컬 표 추출, Azure layout, PaddleOCR 중 2~3개. 같은 ②~④를 붙여 끝까지(end-to-end) 잰다.
4. 실제 Azure를 부르는 평가는 비용이 드므로 기존 평가 스크립트처럼 요청할 때만 실행한다.

## 11. 단계

| 단계 | 내용 | 끝났다고 보는 기준 |
|---|---|---|
| P0 | 정답셋 수집·가리기, 항목명·머리글 사전 초안 | 정답셋 10장 이상 |
| P1 | 글자 있는 PDF: 로컬 표 추출 + 열 역할 규칙 + 표 검증(T1~T10) + 계약 확장 | 정답셋 PDF에서 오수용률 0 |
| P2 | 스캔본: OCR 표 인식(9절 결정 후) | 정답셋 스캔본에서 오수용률 0 |
| P3 | 휴대폰 사진: 보정과 품질 기준 | `LOW_QUALITY` 기준 확정 |

P1만으로도 지금의 `extractor.py` 재사용 경로(본문 한 덩어리, 쪽 번호 없음)보다 안전하다. 따라서 P1을 먼저 끝내고 업로드 서비스의 추출기 호출부를 바꾼다(계약 §9).

## 12. 정할 것 / 확인하지 못한 것

- 9절: `docs/llm-data-policy.md`에 문서 인식 구분 추가(승인 필요), 개인정보 처리방침 확인(담당자)
- 정답셋을 어디에 둘지(레포 안 `data/golden/` 또는 레포 밖)
- 항목명 사전을 `knowledge/`에 둘지(빌드 대상으로 할지)
- 실제 성적서에 괘선이 있는지, 시료별 열 배치가 흔한지, 기준 열이 얼마나 자주 붙는지: **샘플 확인 전에는 모두 가정**
- Azure layout 모델의 한국어 표 품질과 비용, 리전

## 13. 구현 상태 (2026-11-11, 브랜치 `feat/test-report-tables`)

| 설계 | 코드 | 메모 |
|---|---|---|
| `TableGrid` 형식(4절) | `app/domain/tables.py` | 계약에 `content.tables[]`, `facts[].cell_ref` 등 선택 필드 추가(`app/domain/document.py`) |
| ① 로컬 표 추출 | `app/reading/pdf_tables.py` | pdfplumber. 선 기준 → 실패한 쪽만 글자 정렬로 추정(경고). 병합 칸 복원, 각주, 쪽 넘김 잇기 |
| ① Azure 표 인식 | `app/reading/azure_tables.py` | `prebuilt-layout`. `ALLOW_DOCUMENT_OCR`와 endpoint·key가 있어야 호출. 칸 신뢰도, 여러 쪽 표 나누기 |
| ② 열 역할 | `app/reading/columns.py` | 머리글 사전(규칙). 못 정한 열은 `UNKNOWN`이고 값으로 쓰지 않음. **LLM 보조는 아직 없음** |
| 항목명 사전 | `app/reading/test_items.py` | 코드에 둠(`knowledge/`로 옮길지는 12절) |
| ③ 대응 층 | `app/reading/mapper.py` | **규칙 기반**(LLM 없음). 열 역할과 사전만으로 값을 칸에 대응. LLM 대응 층은 같은 출력 형식으로 나중에 붙임 |
| ④ 표 검증 T1~T10 | `app/reading/table_guard.py` | 대응 층을 믿지 않고 표에서 다시 계산. 환산값 재계산 포함 |
| 흐름 | `app/reading/pipeline.py` | 글자 있는 PDF → 로컬, 결과 표가 없거나 스캔본·이미지 → Azure(켜져 있을 때) |
| 업로드 연결 | `app/api/document_reading.py`, `CaseService._read_file` | PDF·이미지 업로드 때 읽고, 표 검증을 통과한 FOUND만 `UNVERIFIED` 후보(`note`에 칸 위치). 직접 입력 키는 건너뜀. 결과 요약은 `extracted_facts.table_read`. 읽는 동안 DB 연결을 놓음. `DOCUMENT_TABLE_READING`으로 끔 |
| 시험 도구 | `scripts/read_test_report.py` | 파일 하나를 읽어 표·열 역할·사실·탈락 사유 출력. `--backend local/azure`로 비교 |

아직 하지 않은 것
- 후보 행(`document_values`)에 `cell_ref`를 별도 칸으로 두지 않았다. 위치는 `note` 글자와 `extracted_facts.table_read.items[].cell_ref`에만 있다
- `attributes`(발급일·시료 채취일·분석기관)와 날짜 검사(§5-8)는 읽지 않는다
- 표 밖 본문에서 값 읽기(`VALUE_OUTSIDE_TABLE`)는 하지 않는다
- 실제 성적서는 1건(공공기관 발급, 글자 있는 PDF, 로컬로만 읽음)으로 확인했다(2026-11-12). 이 양식에서 고친 것:
  한 칸에 항목이 여러 줄로 쌓이고 행 사이 선이 없는 표(`pdf_tables._split_stacked_rows`), 항목 이름 안의 단위("납(mg/L)"),
  시료 이름 열(`ColumnRole.SAMPLE`, "검체명"). 숫자 값 5개는 맞게 읽었고 기준 열은 결과로 읽지 않았다.
  불검출 9개는 성적서에 검출한계가 없어, 같은 행 기준값을 상한으로 쓰기로 했다(2026-11-12 결정, 계약 §5-5
  `detection_limit_basis=limit_column`. 0으로 넣지 않는 이유는 계약 "불검출(ND)의 표현"). 8개가 채워지고 단위 오타(mg/mL)인
  카드뮴만 AMBIGUOUS. 정답셋(10절)은 아직 없다
- Azure 표 인식은 만든 샘플 이미지로만 실제 호출을 확인했다. 쌓인 줄 나누기는 pdfplumber에만 있다
- 특허 공보에 실린 성적서 그림(공개 문서)으로 Azure를 시험했다(2026-11-12, 20장 1회 + 3장 재시험). 저해상도·워터마크라
  OCR이 '납'→'밥', '불검출'→'불김출'처럼 읽어 재현율이 낮다(장당 0~3개). 낸 값 중 숫자가 틀린 것은 없었다.
  한 장(시료 4개가 각자 표)은 다른 시료 글자가 깨져 Blank 시료 값이 '납'으로 잡혔다. 그래서 시료별 표(열 구성이 같은
  결과 표 여럿, 또는 한 표 안에서 머리글 반복)에서 다른 묶음에 같은 항목이나 읽지 못한 항목이 있으면 AMBIGUOUS로 한다
  (`mapper._risky_in_sample_tables`, `_risky_in_blocks`). Azure 호출은 `polling_interval=1`.
