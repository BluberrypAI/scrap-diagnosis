# Codex 작업 지시서 — 폐기물 법령 원문 확보·정리

이 작업은 **법령 원문을 찾아 표로 옮기는 일만** 한다. 코드 작성, 엔진 설계, 다른 저장소 확인은 하지 않는다.

## 절대 규칙

1. **원문에 없는 내용을 쓰지 않는다.** 기억·추측·요약으로 채우지 않는다. 못 찾으면 `NOT_FOUND`로 남긴다.
2. 인용(`source_quote`)은 원문 글자 그대로. 숫자·단위·"이상/이하/초과/미만"을 바꾸지 않는다.
3. 모든 행에 출처 URL, 법령명, 별표/조문 번호, 개정일·시행일, 확인일을 붙인다.
4. 현행판 기준. 구판과 섞지 않는다.
5. 모든 행의 `review_state`는 `UNVERIFIED`.
6. 출처는 국가법령정보센터(law.go.kr)와 법령 Open API만. 원본 PDF는 `sources/raw/`에 받아 SHA-256을 기록한다.

## 이미 확인된 원문 (2026-11-04 기준, 다시 받아 해시 확인)

| 내용 | URL | 판 | SHA-256 |
|---|---|---|---|
| 시행령 별표 1 (지정폐기물) | https://www.law.go.kr/LSW/flDownload.do?flSeq=162468983 | 2025-10-01 개정 / 시행령 시행 2026-03-26 | 5c69411f44f9e01b8db45f7a030dee0ee29463497a2ab61dfae387eda463048c |
| 시행규칙 별표 1 (유해물질 기준) | https://www.law.go.kr/LSW/flDownload.do?flSeq=170401289 | 2025-10-01 개정 / 시행규칙 시행 2026-10-02 | cb4042a306b265f5af924ab001a6b9093eef8b3506de6f0be2b1e4a4070f5c82 |
| 시행규칙 별표 2 (할로겐족 용제) | https://www.law.go.kr/LSW/flDownload.do?flSeq=170401297 | 시행규칙 시행 2026-10-02 | da698093542723b75370239de84e6672b384db2743e7457d2c1cfaa8b4f68ce3 |
| 시행규칙 별표 4 (분류번호) | https://www.law.go.kr/LSW/flDownload.do?flSeq=170401309 | 2025-12-30 개정 / 시행규칙 시행 2026-10-02 | 9ccd6593f4e93a216594b634e204d091d42b174d7cf8d69e4fe502865d492023 |

해시가 다르면 개정된 것이므로 새 판을 쓰고 차이를 보고한다.

## 작업 1 — 위치 확정

아래 내용이 현행 법령의 **실제 몇 번 별표/몇 조**에 있는지 찾는다.

- 재활용 유형(R코드) 정의 — 시행규칙 별표 4의2로 추정, 미확인
- 폐기물별 허용 재활용 유형 — 시행규칙 별표 4의3으로 추정, 미확인
- 폐기물·사업장폐기물·지정폐기물 정의 — 법 제2조
- 사업장폐기물 배출사업장 범위 — 시행령
- 지정폐기물 보관·처리 기준, 처리계획 확인, 위탁 요건 — 시행규칙
- 혼합 폐기물 분류·처리 규정 (없으면 NOT_FOUND)
- 폐기물 공정시험기준 — 환경부 고시 번호·시행일

출력: `data/law_sources.csv`
열: `source_id, law_name, item, title, amended_on, effective_on, url, sha256, checked_on, note`
(위 "이미 확인된 원문" 4개도 포함)

## 작업 2 — 대상 행 원문 추출

대상 분류번호:
- 51-03-01, 51-03-03, 51-03-04, 51-03-06, 51-03-07
- 51-29-01, 51-29-02, 51-29-03, 51-29-04
- 별표 4의 폐산·폐알칼리 분류번호 전체

출력:

1. `data/waste_codes.csv`
   `code, name, major, middle, minor, designated, source_id, source_quote, law_version, review_state`
2. `data/designated_rules.csv` — 시행령 별표 1 중 위 대상에 적용될 수 있는 지정 기준 전부
   (폐산·폐알칼리 pH 기준과 예외, 폐합성수지 지정 항목과 고체 제외, 폐유 관련, 유해물질 함유 관련 등)
   `rule_id, applies_to, condition_text, threshold_value, unit, comparator, exception_text, source_id, source_quote, law_version, review_state`
3. `data/recycling_types.csv` — R코드 정의 전체
   `r_code, definition, source_id, source_quote, law_version, review_state`
4. `data/allowed_recycling.csv` — 대상 분류번호별 허용 R코드
   `code, r_code, condition_text, source_id, source_quote, law_version, review_state`

## 완료 보고

- 작업 1에서 추정 위치와 달랐던 것
- NOT_FOUND 목록
- 원문이 모호해 사람 해석이 필요한 지점
