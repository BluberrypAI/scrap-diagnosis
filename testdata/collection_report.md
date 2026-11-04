# 계산기 평가용 사례 수집 보고서

수집 기준일은 2026-11-05(한국 시간)이다. 기관 문서에 인용된 당시 결론을 전사했다. 현재 법령에 따른 개별 사안의 재판정은 별도다.

총 **178건** 중 하나 이상의 명시적인 단계 결론이 있는 레코드는 **61건**이다. 스펀지 두 분기를 한 건으로 묶고 유사한 폐수처리오니 회신과 하수준설토 예시를 각각 중복 집계에서 빼면 **58건**으로, 지시서의 40건 기준을 충족한다. 조건이 명시된 분류·재활용 결론은 해당 조건에서만 사용한다.
단계 결론이 전부 유보된 레코드는 31건이며, 단계 기대값이 비어 있는 레코드는 86건이다.

## 출처별 건수

| 보유 원본 | 전체 | 결론 있음¹ | DEV | EVAL |
| --- | ---: | ---: | ---: | ---: |
| `sources/raw/add-case-2001도70.html` | 1 | 1 | 0 | 1 |
| `sources/raw/add-case-2002도6081.html` | 1 | 1 | 0 | 1 |
| `sources/raw/add-case-2004도4150.html` | 1 | 0 | 0 | 1 |
| `sources/raw/add-case-2008도3108.html` | 1 | 1 | 0 | 1 |
| `sources/raw/add-case-2009두6681.html` | 1 | 1 | 0 | 1 |
| `sources/raw/add-case-2010도16314.html` | 1 | 1 | 0 | 1 |
| `sources/raw/add-case-2019도1118.html` | 1 | 0 | 0 | 1 |
| `sources/raw/add-case-2023도3914.html` | 1 | 0 | 0 | 1 |
| `sources/raw/add-case-2024도12100.html` | 1 | 1 | 0 | 1 |
| `sources/raw/add-case-95도3130.html` | 1 | 0 | 0 | 1 |
| `sources/raw/add-qa-expc-329297.html` | 1 | 1 | 0 | 1 |
| `sources/raw/classification-guide-2023.pdf` | 15 | 13 | 5 | 10 |
| `sources/raw/tc-moe-qa-casebook-2025-07.pdf` | 43 | 8 | 2 | 41 |
| `sources/raw/wonju-environment-qa-volume2-posted-2026-08-11.hwp` | 30 | 13 | 0 | 30 |
| `sources/raw/wonju-qa-2026.pdf` | 67 | 8 | 6 | 61 |
| `sources/raw/wonju-recycling-qa-posted-2026-08-11.pdf` | 12 | 12 | 0 | 12 |

¹ 한 단계 이상이 `UNDECIDED` 이외의 값인 레코드.

## 답변 유형

| answer_type | 건수 |
| --- | ---: |
| `CODE_GIVEN` | 13 |
| `CODE_CONDITIONAL` | 5 |
| `DESIGNATED_ONLY` | 13 |
| `NOT_WASTE` | 6 |
| `TEST_REQUIRED` | 9 |
| `CASE_BY_CASE` | 23 |
| `OTHER` | 109 |

## 단계별 기대값

| 단계 | 키 있음 | 명시 결론 | UNDECIDED |
| --- | ---: | ---: | ---: |
| `S0` | 23 | 18 | 5 |
| `S1` | 2 | 2 | 0 |
| `S2` | 8 | 3 | 5 |
| `S3` | 35 | 14 | 21 |
| `S4` | 19 | 18 | 1 |
| `S5` | 17 | 17 | 0 |

## DEV와 EVAL

- DEV 13건, EVAL 165건. 지시서의 DEV 대상과 하수준설토 예시(GUIDE23-116-01)는 DEV다. 하수준설토 예시는 MOE25-242의 결론과 실질적으로 겹친다.
- 원주 사례 56의 네 질의 및 설명서 p.118 스펀지 두 분기는 각각 같은 split에 있다. 문서 내 별개의 사례 번호는 서로 다른 split에 들어갈 수 있다.
- 아래 목록은 EVAL 레코드가 있는 보유 문서다. 기대값이 빈 절차 사례와 유보 사례도 문서 목록 집계에 포함된다.

- `sources/raw/add-case-2001도70.html`
- `sources/raw/add-case-2002도6081.html`
- `sources/raw/add-case-2004도4150.html`
- `sources/raw/add-case-2008도3108.html`
- `sources/raw/add-case-2009두6681.html`
- `sources/raw/add-case-2010도16314.html`
- `sources/raw/add-case-2019도1118.html`
- `sources/raw/add-case-2023도3914.html`
- `sources/raw/add-case-2024도12100.html`
- `sources/raw/add-case-95도3130.html`
- `sources/raw/add-qa-expc-329297.html`
- `sources/raw/classification-guide-2023.pdf`
- `sources/raw/tc-moe-qa-casebook-2025-07.pdf`
- `sources/raw/wonju-environment-qa-volume2-posted-2026-08-11.hwp`
- `sources/raw/wonju-qa-2026.pdf`
- `sources/raw/wonju-recycling-qa-posted-2026-08-11.pdf`

## 등록된 사례가 0건인 waste_kind

`synthetic_rubber`, `pesticide`, `foundry_sand`, `refractory`, `stabilized`, `adsorbent`, `paint`, `paint_solvent_mix`, `paint_cleaning_solvent`, `paint_container`, `asbestos_processing`, `asbestos_work_items`, `mercury_product`, `mercury_separated`, `mercury_residue`, `medical`, `norm_product`.

## 구판 분류번호

- `WONJU26-56-Q3` — `02-01-06`. 02-01-06은 기관이 열거한 구판 제외 범위의 끝 번호다. S4에는 기관이 부여한 02-01-99를 그대로 넣었다.

번호 존재 여부는 저장소의 시행규칙 별표 4 스냅샷(`rules/annex4_codes.yaml`, 2025-12-30 개정 표기)과 비교했다. 2023 설명서의 그룹 번호 `51-18`은 사례 원문에 보존했다.

## 기존 사실 목록 밖에서 반복된 표현

아래 집계는 `unmapped_facts`에 남긴 인용을 소재별로 묶은 것이다. 한 레코드가 둘 이상의 소재에 해당할 수 있다.

| 소재 | 레코드 | 원문 표현 예시 |
| --- | ---: | --- |
| 용기 재질·잔류물 및 세척 여부 | 10 | “20L 철재 에탄올 용기” / “소량의 폐유가 남아있는 드럼통” |
| 재활용 목적·방법 및 원료 기준 | 8 | “한번 포설한(사용한) 순환골재” / “무기성오니류를 R-4-2 유형에 따라 골재 제품을 만들어 성토･복토용도로” |
| 발생 공정·오니 세부 종류 및 혼합 여부 | 11 | “그밖에 공정오니(01-02-99)” / “오니류 폐기물” |
| 구간·예상량·별도 단위·시험 방법 | 16 | “연간 총합 100톤 이상” / “폴리에틸렌 40%” |
| 시설·기기 종류와 확인 정보 | 7 | “도장시설의 집진기에 포집된 폐페인트 가루” / “폐수배출시설에서 발생되는” |

## 출처 범위와 판독

- 환경부 2025.7 사례집은 자원순환 분야 인쇄면 232~272의 41건과 화학물질 담당 부서의 폐기물 관련 2건을 수록했다. 원주 지정폐기물 사례집은 번호가 붙은 64개 사례를 모두 수록했다. 56번의 네 질의를 각각 분리했다.
- 대법원 판결 10건은 판시사항과 판결요지 또는 이유를 원문 칸에 넣었다. 법제처는 질의요지·회답·이유를 수록했다. 국립환경과학원 설명서의 서술형 분류 예시는 전제와 결론으로 나누었다.
- 두 HWP 모두 본문을 읽었다. 원본 파일 해시는 다르지만 추출한 제2권 본문이 같아 원주 게시본을 대표로 사용했다. 지정폐기물 분류 장과 의료·건설폐기물 분류 장의 주요 사례를 선별했다.
- 재활용 사례집 117쪽의 한글 OCR로 후보를 탐색했다. 인쇄면 6·7·8·11·39·40·42 중 12건을 페이지 이미지로 대조해 수록했다. 나머지 쪽의 개별 원문 대조는 범위에서 제외했다.
- 보유 우선 자료에서 목표를 채워 다른 연도판이나 다른 기관의 자료는 추가 수집하지 않았다. `unreachable.csv`에 기록할 원본 확보·판독 실패는 0건이다.
- 질의에서 제시한 가정·범위·조성의 단위가 입력 정의와 일치하지 않으면 `unmapped_facts`에 남겼다. 조건이 질의에만 명시된 공식 분류 예시는 해당 위치를 `review_note`에 표시했다.
- S5가 R코드를 명시하면 `{"conclusion":"ALLOWED_TYPES","allowed_types":["R-…"]}`로 보존했다. 허용 목록은 질의한 용도에서 회신이 직접 제시한 코드다.

### 보유 원본 SHA-256

| 원본 | SHA-256 |
| --- | --- |
| `sources/raw/add-case-2001도70.html` | `216470ab0aea65e91991540282d84023b6aa7b839719aca67d740f2dfb273e38` |
| `sources/raw/add-case-2002도6081.html` | `82be591eafea158156c4541b7013e1991fdb221de1f1f7edf72e530daf053cb9` |
| `sources/raw/add-case-2004도4150.html` | `be3e461cf379ef6cb047cdd9338c6fc76e3edfca4bd53068358d4fc95edd4251` |
| `sources/raw/add-case-2008도3108.html` | `a425830dc39ecf3290fc1d11e442dc9f652cce96b1846e64d1fc995f5aad6dab` |
| `sources/raw/add-case-2009두6681.html` | `c13209796e37d8abffc6c7b5f83ca470603e541adbca5eabcdfe09b521a562a6` |
| `sources/raw/add-case-2010도16314.html` | `0d4fb3412ea52dbc6f5d6064f0310791209793793fd859ec51b693795560d84a` |
| `sources/raw/add-case-2019도1118.html` | `9ad62e23cb48c5663d226c309c8d902c858a1264864a45277889821c135435cb` |
| `sources/raw/add-case-2023도3914.html` | `45554afc458b98a4666051561d1cc4a52d392e1ec016de9147c4e016c5f333a2` |
| `sources/raw/add-case-2024도12100.html` | `5e01f84f2c7a666c676e5afa83e43d4ea657b2241ae3005820d2f640714f6674` |
| `sources/raw/add-case-95도3130.html` | `dc2c8faf2e499630c622e2448fcb30e9f90ee2a6386abf347d1c9ea650864544` |
| `sources/raw/add-qa-expc-329297.html` | `bf56f7aacaa262b2a9412155f5f3281b73ed4e44ff278d3e7de66c95a5c93e75` |
| `sources/raw/add-qa-moe-2009.hwp` | `08b4cfdd955c3b89833c9061a2aad291e73b439085575af427486bddb24e185e` |
| `sources/raw/classification-guide-2023.pdf` | `87dc95a868e1f7f34bdebdc957a5be2dc56abecc7b42379264f588a43122fd48` |
| `sources/raw/tc-moe-qa-casebook-2025-07.pdf` | `9cf6b31e8678f9acbcaa7e12d725617c46ff9f22820cc622cebb0ca0970a0cf1` |
| `sources/raw/wonju-environment-qa-volume2-posted-2026-08-11.hwp` | `dd67adbb903583b6135919882691ee4b03fcb77c9c683745d1c3a491e022c8be` |
| `sources/raw/wonju-qa-2026.pdf` | `d74bac265fee126d5124293089e3e178a2a1d5745b6aa30bf9d532c0a1af91f3` |
| `sources/raw/wonju-recycling-qa-posted-2026-08-11.pdf` | `aa9dc9a2182df2644325d23097ed9f9972ce56f3497de7443f65243b230e275f` |

## 검증

- PASS — JSONL 1줄 1객체, 사례 ID, 입력값 형식·허용값, 각 근거 구절의 위치, 분류번호와 레거시 표시, DEV 대상, 사례 쌍의 단일 입력 차이, 보고서 집계를 점검했다.
- SKIPPED — 지시서에 따라 계산기 실행 및 정답 대조는 평가 범위에서 제외했다.
