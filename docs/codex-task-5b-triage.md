# Codex 작업 지시서 5B — 수집 자료의 관련성·판 상태 판정 (2차)

권장 실행 설정: **추론 수준 high**
전제: 지시서 5A가 끝나 `inventory/` 폴더에 결과가 있다. 없으면 시작하지 말고 그렇게 보고한다.

이 작업은 **5A가 모은 자료를 읽고, 계산기와 관련 있는 것과 없는 것을 정밀하게 나누고, 판 상태를 확정하는 일만** 한다.
- 새 자료를 찾으러 다니지 않는다. 판정 중 빠진 자료를 발견하면 받지 말고 `inventory/missing_found_in_triage.csv`에 적는다.
- 표로 옮기기(조문 추출, 기준값 정리)는 하지 않는다.
- 5A가 만든 파일은 수정하지 않는다. 판정 결과는 새 파일에 쓴다.

## 계산기

대상은 **대한민국의 모든 폐기물**이다.
판단 순서: 법 적용 대상인지(다른 법 적용인지) → 폐기물인지 → 어느 종류인지(생활/사업장일반/지정/의료/건설) → 지정폐기물인지 → 분류번호 → 재활용 가능 유형과 금지·제한 → 배출자 의무.

## 관련성 태그

자료마다 해당하는 태그를 **모두** 붙인다.

| 태그 | 뜻 | 예 |
|---|---|---|
| `A_SCOPE` | 법 적용 대상·제외, 폐기물 해당 여부 | 폐기물관리법 제2조·제3조, 다른 법 적용 대상의 정의 조문, 부산물, 순환자원 인정 |
| `B_TYPE` | 폐기물 종류 구분 | 생활/사업장/지정/의료/건설폐기물 정의, 사업장 범위, 의료폐기물 종류, 건설폐기물 종류 |
| `C_DESIGNATED` | 지정폐기물 판단 | 시행령 별표 1, 유해물질 기준, 할로겐족 목록, 오니 발생시설 고시 |
| `D_CODE` | 분류번호 결정 | 시행규칙 별표 4, 건설폐기물 분류, 분류 해설서, 분류 질의회신 |
| `E_RECYCLING` | 재활용 유형·금지·제한·기준 | 시행규칙 별표 4의2·4의3·5의3, 시행령 별표 4의2·4의3, 법 제13조의2·제13조의3 |
| `F_DUTIES` | 배출자 의무·처리·보관·위탁 | 시행규칙 별표 5, 배출자 신고, 처리계획 확인, 위탁 기준, 전자인계 |
| `G_TEST` | 시험 방법 | 폐기물공정시험기준, 시료 채취 |
| `H_FACILITY` | 처리업체·수요처 (다음 단계용) | 처리업 허가 종류, 허가 데이터 |
| `I_CASES` | 정답셋 후보 사례 | 질의회신, 법령해석례, 판례 |
| `X_UNRELATED` | 계산기와 관련 없음 | 처리시설 설치·구조·검사 기준, 처리업 장비·인력 기준, 수수료·부담금 금액, 과태료 금액표, 지자체 계획, 공공시설 운영, 기관 조직, 다른 매체 규제 |

규칙:
- 판단이 애매하면 `MAYBE`와 이유. **애매한 것을 X로 버리지 않는다.**
- 범위 밖 분야라도 **범위 밖임을 판정하는 근거**(정의 조문)는 `A_SCOPE`나 `B_TYPE`.
- `X_UNRELATED`를 붙일 때는 이유를 한 줄 적는다.

## 할 일

### 1. 조문 단위로 나누기

`unit=DOC`인 법령 중 `tags_guess`에 `A`~`G`가 하나라도 있는 것은 **조문·별표 단위**로 나눠 각각 판정한다.
조문이 많으면 장·절 단위로 먼저 판정하고, `A`~`G` 태그가 붙은 장만 조문 단위로 다시 나눈다.

### 2. 사례집을 사례 단위로 나누기

`doc_type=QA`인 사례집은 **사례 하나당 한 행**으로 나눈다 (사례 번호, 쪽, 제목, 태그). 내용은 옮기지 않는다.
제목만으로 애매하면 본문 첫 단락까지 읽고 판정한다.

### 3. 판 상태 확정

모든 행의 `version_status`를 확정한다.

| version_status | 뜻 | 계산기 판정에 사용 |
|---|---|---|
| `CURRENT` | 2026-11-04 현재 시행 중 | 사용 |
| `PENDING` | 공포됐지만 아직 시행 전 | 시행일 이후 사용 |
| `SUPERSEDED` | 개정·폐지로 효력 상실 | **사용 안 함** (파일은 지우지 않음) |
| `NOT_APPLICABLE` | 해설서·사례처럼 효력 개념이 없는 자료 | 아래 `assumed_version`으로 관리 |

- `SUPERSEDED`면 대체한 현행판 `doc_id`를 `superseded_by`에 적는다.
- 해설서·사례는 **전제하는 법령 판**을 `assumed_version`에 적고, 그 판이 현행과 다르면 `assumes_superseded=Y`.

### 4. 기존 data/ 와 대조

기존 `data/*.csv`가 인용하는 출처(`source_id`, `local_path`) 가운데:
- `SUPERSEDED` 판을 인용하는 행 수
- 이번 수집에서 새로 확인된 `C_DESIGNATED`·`D_CODE`·`E_RECYCLING` 자료 중 기존 `data/`에 없는 것

## 출력

1. `inventory/triage.csv`
   `item_id, doc_id, parent_item_id, unit(DOC/CHAPTER/ARTICLE/ANNEX/CASE), location, title, tags, maybe_reason, x_reason, version_status, superseded_by, assumed_version, assumes_superseded(Y/N), relevance_note, local_path`
   - `relevance_note`: 왜 이 태그인지 한 줄. 원문 인용은 30자 이내로만.
2. `inventory/missing_found_in_triage.csv` — `title, why_needed, where_referenced, suggested_source`
3. `inventory/triage_report.md`
   - 태그별 건수, `MAYBE` 건수와 목록
   - `version_status`별 건수, `SUPERSEDED` 보유 파일 목록과 그것을 인용하는 기존 `data/` 행 수
   - `assumes_superseded=Y`인 해설서·사례 목록
   - `X_UNRELATED`로 뺀 자료의 분야별 건수와 대표 예
   - 기존 `data/`에 아직 없는 핵심 자료 목록
   - 5A의 `unreachable.csv` 가운데 계산기에 꼭 필요해 보이는 것 (사람이 우선 받아야 할 순서)
   - 사람이 결정해야 할 것
