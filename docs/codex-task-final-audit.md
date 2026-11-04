# Codex 작업 지시서 3 — 최신판 최종 검색과 전체 검수

이 작업은 **이미 모은 자료가 현행판이 맞는지 다시 찾고, 전체를 검수하는 일만** 한다.
코드 작성, 규칙 만들기, 새 해석 추가는 하지 않는다.

## 기존 파일은 고치지 않는다

`data/*.csv`와 `docs/interpretation_report.md`는 **수정하지 않는다.**
고칠 점은 `audit/` 폴더의 새 파일에만 적는다. 사람이 검토한 뒤 반영한다.

## 절대 규칙

1. 원문에 없는 내용을 쓰지 않는다. 못 찾으면 `NOT_FOUND`. "없다"와 "못 찾았다"를 구별한다.
2. 검색했으면 **어디서 무엇으로 검색했는지**를 남긴다. 검색 기록이 없는 `NOT_FOUND`는 인정하지 않는다.
3. 출처는 정부·공공기관 사이트만. 블로그·기사·민간 자료 금지.
4. 새로 받은 파일은 `sources/raw/`에 받고 SHA-256을 기록한다. 기존 파일을 덮어쓰지 않는다. 같은 이름이면 날짜를 붙인다.
5. 판단이 필요한 곳에서는 판단하지 말고 `NEEDS_HUMAN`으로 표시한다.

## 작업 1 — 최신판 재검색

아래 각 자료에 대해 **2026-11-04 현재 가장 최신 판**을 다시 찾는다.

| 자료 | 현재 가진 판 | 찾을 것 |
|---|---|---|
| 폐기물 분류체계 및 분류방법 설명서 | 2023, 국립환경과학원 | 2024·2025·2026년 개정판, 개정 예고, 다른 이름으로 나온 후속 해설서 |
| 폐기물관리법 시행규칙 별표 4 | 2025-12-30 개정 | 이후 개정, 공포됐지만 아직 시행 전인 개정 |
| 시행규칙 별표 4의2, 4의3, 5 | 2025-12-30 / 2026-03-26 개정 | 같음 |
| 폐기물관리법 시행령 별표 1 | 2025-10-01 개정 | 같음 |
| 폐기물관리법, 시행령, 시행규칙 본문 | 법률 제21467호 / 대통령령 제36217호 / 기후에너지환경부령 제60호 | 같음 |
| 자원재활용법, 시행령, 시행규칙 | 법률 제21370호 / 대통령령 제36269호 / 기후에너지환경부령 제42호 | 같음 |
| 폐기물공정시험기준 | 국립환경과학원고시 제2025-21호 | 이후 고시 |
| 지정폐기물 질의·회신 사례집 | 원주지방환경청, 2026-05-11 게시 | 다른 지방(유역)환경청·환경부·한국환경공단의 더 최근 사례집 |

반드시 확인할 곳:
- 국가법령정보센터: 현행 법령, **연혁**, **시행 예정 법령**, 별표 서식 목록
- 국립환경과학원 발간자료, 환경정보도서관
- 기후에너지환경부 정책자료·법령정보, 입법·행정예고
- 한국환경공단, 올바로시스템 공지·자료실
- 각 유역·지방환경청 자료실 (한강·낙동강·금강·영산강·새만금·원주·대구·전북·경인 등)
- 국회도서관(clik.nanet.go.kr), 정책브리핑(korea.kr)

검색어 예: "폐기물 분류체계 및 분류방법 설명서", "폐기물 분류 설명서 개정", "폐기물 세부분류 해설", "지정폐기물 질의회신 사례집", "폐기물 분류번호 안내서".

출력: `audit/version_search.csv`
`material, current_version_held, site, query, searched_on, result(NEWER_FOUND/SAME/NOT_FOUND), newer_version, newer_url, newer_sha256, note`

## 작업 2 — 해설서(2023)와 현행 법령 차이 대조

2023 해설서는 2023-08-11 개정 별표 4를 전제한다. 그 뒤 별표 4가 바뀐 내용을 찾아 해설서 인용 행에 영향이 있는지 대조한다.

- 국가법령정보센터 연혁에서 2023-08-11 이후 별표 4의 모든 개정판을 찾는다
- 대상 분류번호 그룹(51-03, 51-29, 02-01, 02-02)에서 **번호 신설·삭제·명칭 변경**을 표로 만든다
  - 이미 알려진 차이: 02-01-06(폐황산이 포함된 2차폐축전지)이 현행에 없음. 언제 삭제됐는지, 다른 번호로 옮겨졌는지 확인
- `data/code_interpretations.csv`의 GUIDE23 출처 행마다, 해당 번호의 명칭이 현행과 같은지 표시

출력: `audit/annex4_changes.csv`
`code, change_type(ADDED/REMOVED/RENAMED/MOVED/NONE), old_name, new_name, amended_on, effective_on, source_url, source_quote, note`

`audit/guide_rows_currency.csv`
`row_id, code, guide_name, current_name, name_match(Y/N), affected_by_change(Y/N/NEEDS_HUMAN), note`

## 작업 3 — 전체 인용 재검수

기존 CSV 10개의 **모든 인용 행**을 원문과 다시 대조한다.

- 대상: `law_sources, waste_codes, designated_rules, recycling_types, allowed_recycling, interpretation_sources, code_interpretations, related_law_definitions, qa_cases, test_methods`
- 텍스트 대조: 공백·줄바꿈만 무시하고 글자 단위로 비교
- 텍스트 층이 깨진 PDF(2023 해설서 등)는 해당 쪽을 이미지로 렌더링해 **전 행** 육안 대조 (표본 아님)
- 숫자·단위·이상/이하/초과/미만·"제외한다"·"포함한다"는 따로 한 번 더 확인
- `location`(쪽·조문 번호)이 실제 위치와 맞는지 확인
- 인용이 중간에 잘려 뜻이 바뀌는 경우(단서 "다만, ..."이 빠진 경우 등)를 찾는다

출력: `audit/quote_check.csv`
`file, row_id, column, method(TEXT/RENDERED), result(MATCH/MISMATCH/LOCATION_WRONG/TRUNCATED/NUMBER_CHECK_FAIL), detail, suggested_fix`

## 작업 4 — 빠진 것 점검

- `waste_codes.csv`에 없는 같은 그룹 번호가 현행 별표 4에 있는지: 51-03-02, 51-03-05, 51-03-08, 51-03-99, 51-29-99 및 그 밖의 누락
- `allowed_recycling.csv`에 위 번호들의 행이 있는지
- `designated_rules.csv`의 기준값(숫자·단위·비교 표현)이 열로 다 나뉘었는지. 본문에만 있는 수치 목록
- `allowed_recycling.csv`에서 같은 번호에 같은 R코드가 두 번 나오는 행 목록과 그 이유(사전 분석·확인 해당/해당 없음 등)

출력: `audit/gaps.csv`
`file, issue_type(MISSING_CODE/MISSING_ROW/THRESHOLD_NOT_SPLIT/DUPLICATE), target, detail, source_quote, suggested_fix`

## 작업 5 — 최종 보고

`audit/final_audit_report.md`에 다음을 쓴다.

1. **최신판 결론**: 자료별로 "현행판 확인됨 / 더 새 판 있음 / 확인 불가" 표
2. 더 새 판이 있으면 기존 CSV에서 영향받는 행 수와 목록
3. 인용 재검수 결과: 전체 행 수, MATCH 수, 문제 유형별 건수
4. 빠진 것 점검 결과 요약
5. `NEEDS_HUMAN` 목록 — 사람이 판단해야 할 지점
6. 검색했지만 접근하지 못한 곳(로그인·이용약관·비공개)과 이유
