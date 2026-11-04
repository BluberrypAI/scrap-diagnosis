# Codex 작업 지시서 2 — 분류 해석 자료 수집

이 작업은 **분류번호를 고르는 기준이 적힌 자료를 찾아 원문 그대로 표로 옮기는 일만** 한다.
코드 작성, 엔진 설계, 규칙 만들기는 하지 않는다. 기존 `data/*.csv` 파일은 수정하지 않는다.

## 배경 (한 줄)

시행규칙 별표 4에는 번호와 이름만 있고, 어떤 사실이면 어떤 번호인지, 두 번호에 겹치면 무엇이 우선인지가 없다.
그 기준이 적힌 공식 해설·관련 법령 정의·질의회신을 모은다.

## 절대 규칙

1. **원문에 없는 내용을 쓰지 않는다.** 요약·추측 금지. 못 찾으면 `NOT_FOUND`.
2. 인용(`source_quote`)은 원문 글자 그대로. 줄바꿈·들여쓰기 같은 배치용 공백만 정리한다.
3. 모든 행에 출처 URL, 문서명, 쪽 또는 조문 위치, 발행일·시행일, 확인일을 붙인다.
4. 모든 행에 `evidence_level`을 붙인다:
   - `LAW` — 법률·시행령·시행규칙·고시 원문
   - `OFFICIAL_GUIDE` — 환경부·한국환경공단 등 공식 기관의 해설서·안내
   - `QA` — 질의회신·법령해석 사례
5. 해설서·질의회신이 **현행 법령과 다른 판**을 전제하면 `note`에 그 판을 적는다. 현행판인지 확인 못 하면 `version_check=UNKNOWN`.
6. 모든 행의 `review_state`는 `UNVERIFIED`.
7. 출처는 정부·공공기관 사이트만 (law.go.kr, me.go.kr, keco.or.kr, allbaro.or.kr, nier.go.kr, clik.nanet.go.kr 등). 블로그·기사·민간 컨설팅 자료 금지.
8. 원본 파일은 `sources/raw/`에 받아 SHA-256을 기록한다. 받을 수 없는 웹 페이지는 URL과 확인일만 기록한다.
9. 이용약관상 내려받기·수집이 금지된 사이트는 받지 말고 `docs/interpretation_report.md`에 위치만 적는다.

## 대상 분류번호

- 51-03 그룹 전체: 51-03-01, 51-03-02, 51-03-03, 51-03-04, 51-03-05, 51-03-06, 51-03-07, 51-03-08, 51-03-99
- 51-29 그룹 전체: 51-29-01, 51-29-02, 51-29-03, 51-29-04, 51-29-99
- 폐산 02-01 그룹 전체, 폐알칼리 02-02 그룹 전체

## 작업 1 — 공식 분류 해설서

환경부 「폐기물 분류체계 및 분류방법 설명서」를 찾는다.

- 알려진 판: 2023년판 https://clik.nanet.go.kr/clikr-collection/policyinfo/228/1076/2024/CLIKC5377732233452870_attach_1.pdf
  (SHA-256 87dc95a868e1f7f34bdebdc957a5be2dc56abecc7b42379264f588a43122fd48, 346쪽)
- **2023년보다 새 판이 있는지 먼저 찾는다.** 있으면 새 판을 쓰고 2023년판과의 차이를 보고한다.
- 해설서가 전제하는 별표 4의 판(개정일)을 확인한다.

추출할 것 (대상 분류번호마다):
- 번호별 정의·설명
- 포함되는 예시, 제외되는 예시
- 다른 번호와 헷갈릴 때의 구분 기준·우선 적용 설명
- 분류 절차(적용대상 확인 → 종류 확인 → 지정 여부 → 번호 부여 등) 서술
- 혼합 폐기물, 오염된 폐기물(기름·페인트 묻음 등), 중간처리 후 산출물의 분류 설명

## 작업 2 — 번호 이름이 끌어 쓰는 다른 법령의 정의

- 「자원의 절약과 재활용촉진에 관한 법률 시행령」 제18조 (51-29-03 폐금속캔류, 51-28-01 등이 인용)
- 같은 법률·시행령·시행규칙에서 **포장재**, **포장재 재질**, **합성수지 포장재**, **금속캔** 정의 조문
- 「제품의 포장재질·포장방법에 관한 기준 등에 관한 규칙」의 포장·포장재 정의 (있으면)
- 51-03-07 플라스틱폐포장재의 범위를 정하는 다른 법령 조문이 있는지 확인 (없으면 NOT_FOUND)
- 「화학물질관리법」은 이번 범위에서 제외

## 작업 3 — 질의회신·법령해석 사례

다음에서 대상 분류번호 또는 아래 쟁점에 관한 사례를 찾는다.

- 국가법령정보센터 법령해석례 (법제처)
- 환경부·한국환경공단 질의회신 게시판, 민원 사례집, 폐기물 분야 질의회신 사례집(PDF)

찾을 쟁점:
- 플라스틱 포장재를 51-03-01과 51-03-07 중 어디로 분류하는지
- 발포 포장재(스티로폼 등)를 51-03-06과 51-03-07 중 어디로 분류하는지
- 스테인리스·합금강을 고철(51-29-01)과 비철금속(51-29-02) 중 어디로 분류하는지
- 금속캔과 금속용기(51-29-03 / 51-29-04) 구분
- 절삭유·기름이 묻은 금속 절삭칩, 기름 묻은 플라스틱의 분류 (폐유 지정 여부 포함)
- 페인트가 남은 금속·플라스틱 용기
- 제조 공정에서 나온 수지 자투리와 사용 후 포장재의 구분
- 폐산·폐알칼리의 pH 기준 적용, 고상 수산화나트륨·수산화칼륨
- 그 밖의(99) 번호를 언제 쓰는지

사례마다: 질의 요지, 회신 요지(원문 인용), 날짜, 기관, 당시 적용 법령 판, URL.

## 작업 4 — 실무 안내

- 한국환경공단 올바로시스템(allbaro.or.kr)의 폐기물 분류번호 안내·코드 설명 페이지
- 폐기물공정시험기준(국립환경과학원고시 제2025-21호, 2025-08-06 시행)에서
  **pH 측정**, **기름성분 함량** 시험 방법의 위치(장·절 번호)와 시료·단위 원문

## 출력

1. `data/interpretation_sources.csv` — 이번에 쓴 자료 목록
   `source_id, title, publisher, evidence_level, published_on, effective_on, law_version_assumed, version_check, url, sha256, checked_on, note`
2. `data/code_interpretations.csv` — 번호별 정의·포함·제외·구분 기준
   `row_id, code, topic(definition/include/exclude/distinction/procedure/mixed/contaminated), related_codes, text, source_id, location(쪽·조문), source_quote, evidence_level, review_state`
3. `data/related_law_definitions.csv` — 작업 2 결과
   `row_id, term, law_name, article, effective_on, source_quote, used_by_codes, source_id, review_state`
4. `data/qa_cases.csv` — 작업 3 결과
   `case_id, issue, related_codes, question_summary_quote, answer_quote, answered_on, agency, law_version_at_time, url, source_id, review_state`
   - `question_summary_quote`, `answer_quote`도 원문 인용. 요약 금지.
5. `data/test_methods.csv` — 작업 4의 시험 방법 위치
   `test_id, item(pH/oil_content), document, chapter, sample_scope_quote, unit_quote, source_id, review_state`
6. `docs/interpretation_report.md` — 완료 보고

## 완료 보고 (`docs/interpretation_report.md`)

- 해설서 최신판 여부와 그 판이 전제하는 법령 판
- 대상 분류번호 중 정의·구분 기준을 **찾은 것 / 못 찾은 것** 표
- 작업 3의 쟁점별로 사례가 있었는지, 몇 건인지
- 자료끼리 서로 다르게 말하는 지점 (해설서 ↔ 질의회신, 구판 ↔ 현행)
- 수집하지 못한 자료와 이유 (이용약관, 로그인 필요, 비공개 등)
