# Codex 작업 지시서 4 (개정) — 계산기 평가용 정답 사례 수집

권장 실행 설정: **추론 수준 high** (원문을 읽고 사실을 정해진 값으로 옮기는 판단이 많음)

이 작업은 **공식 기관이 실제로 답한 사례를 모아, 계산기 입력 형식(사실 값)과 기관의 결론으로 옮기는 일만** 한다.
코드·규칙(`src/`, `rules/`, `tests/`)은 고치지 않는다. 계산기를 실행해 답을 맞춰 보지도 않는다(평가는 사람이 따로 한다).

## 폴더·git 규칙

- 결과는 **`testdata/` 폴더에만** 쓴다. 그 밖의 폴더는 읽기만 한다.
- 새로 받은 원본은 `sources/raw/` 아래 **`tc-`로 시작하는 이름**으로 저장하고 SHA-256을 기록한다. 기존 파일은 덮어쓰지 않는다.
- **git 커밋·브랜치 생성은 하지 않는다.** 사람이 검토 후 커밋한다.

## 계산기가 하는 일 (사례를 옮길 기준)

대상은 **사업장폐기물(산업폐기물)** 이다. 계산기는 사실을 받아 단계별로 결론을 낸다.

| 단계 | 결론 값 |
|---|---|
| S0 폐기물 해당 여부 | `WASTE` / `NOT_WASTE` / `CIRCULAR_RESOURCE` |
| S1 폐기물관리법 적용 | `APPLIES` / `EXCLUDED` |
| S2 사업장폐기물 여부 | `BUSINESS` / `HOUSEHOLD` |
| S3 지정폐기물 여부 | `DESIGNATED` / `NOT_DESIGNATED` / `NEEDS_INTERPRETATION` |
| S4 분류번호 | 시행규칙 별표 4의 6자리 번호 (예: `02-01-02`) |
| S5 재활용 | `PROHIBITED` / `RESTRICTED` / `ALLOWED_TYPES`(R코드 목록) / `NOT_LISTED` |

## 절대 규칙

1. **원문에 없는 사실을 만들지 않는다.** 질의·회신에 글로 적힌 사실만 옮긴다. 업종·상식·물질명으로 추론해 채우지 않는다.
   예: "폐황산"이라고만 적혀 있으면 `waste_kind=acid`는 옮기되, pH가 적혀 있지 않으면 `ph`는 비워 둔다.
2. 사실을 옮길 때마다 **그 근거 구절을 원문 그대로** 함께 적는다. 근거 구절이 없는 사실은 넣지 않는다.
3. **기관의 결론만** 기대값으로 옮긴다. 기관이 말하지 않은 단계는 비워 둔다. 번호 없이 이름만 말했으면 번호로 바꾸지 않는다.
4. 회신이 **구판 번호**(예: 현행 별표 4에 없는 `02-01-06`)를 쓰면 그대로 적고, 현행 번호로 옮기지 않는다(`legacy_code: true`).
5. 질의와 회신은 **요약하지 않고 원문 그대로** 인용한다. 공백·줄바꿈 정리만 허용.
6. 회사명·사업장명·주소·사람 이름은 `[업체]`처럼 가린다.
7. 출처는 정부·공공기관·법원 공개 자료만.
8. 판단이 애매한 사례는 버리지 말고 `review_note`에 이유를 적는다.

## 사실 값 (이 이름과 값만 사용)

계산기의 `rules/facts.yaml`과 같다. 목록에 없는 값이 필요하면 넣지 말고 `unmapped_facts`에 원문 표현을 적는다.

| 사실 | 형식 | 값 |
|---|---|---|
| no_longer_needed | 참/거짓 | 사업활동에 필요 없게 되어 내보내는가 |
| direct_reinput | 참/거짓 | 별도 처리 없이 같은 사업장 같은 공정에 원료로 바로 재투입 |
| circular_resource_recognized | 참/거짓 | 순환자원 인정서 있음 |
| law_exclusion | 선택 | none, radioactive, uncontained_gas, wastewater, livestock_manure, sewage_nightsoil, livestock_disease, aquatic_disease, military_ammo, pet_funeral, fisheries_byproduct_unmixed |
| emission_facility | 참/거짓 | 대기·수질·소음진동 배출시설 허가·신고 사업장 |
| public_facility | 선택 | none, public_wastewater, public_sewage, nightsoil, livestock_public |
| waste_facility | 참/거짓 | 폐기물처리시설 설치·운영 사업장 |
| designated_waste_emitted | 참/거짓 | 사업장에서 지정폐기물 배출 |
| daily_avg_kg | 숫자(kg/일) | 하루 평균 배출량 |
| work_type | 선택 | none, construction(건설산업기본법 건설공사), series(그 밖의 일련의 공사·작업) |
| work_total_ton | 숫자(톤) | 공사·작업 전체 배출량 |
| waste_kind | 선택 | synthetic_resin, synthetic_rubber, sludge_wastewater, sludge_process, pesticide, acid, alkali, slag, dust, foundry_sand, refractory, incineration_ash, stabilized, catalyst, adsorbent, organic_solvent, paint, paint_solvent_mix, paint_cleaning_solvent, paint_container, waste_oil, edible_oil, asbestos_demolition, asbestos_processing, asbestos_work_items, mercury_product, mercury_separated, mercury_residue, medical, norm_product, battery, other |
| physical_state | 선택 | solid, liquid, semisolid |
| sludge_water_pct | 숫자(%) | 오니 수분함량 |
| sludge_facility_notified | 참/거짓 | 고시된 오니 발생시설 |
| pesticide_from_maker_seller | 참/거짓 | 농약 제조·판매업소에서 발생 |
| ph | 숫자 | pH |
| alkali_solid_naoh_koh | 참/거짓 | 고상 수산화나트륨·수산화칼륨 |
| blast_furnace_iron_slag | 참/거짓 | 철광 원석 고로슬래그 |
| dust_from_apc / dust_from_incinerator | 참/거짓 | 대기오염 방지시설 포집 / 소각시설 발생 |
| paint_mixed_source | 선택 | maker, coating_large, recycling, other |
| paint_dried / paint_residue_mm | 참/거짓 / 숫자(mm) | 페인트 용기 잔존물 |
| oil_presence | 선택 | none, present |
| oil_content_pct | 숫자(%) | 기름성분 |
| asbestos_pct | 숫자(%) | 석면 함량 |
| pcb_possible / pcb_mg_l / pcb_leach_mg_l | 참/거짓 / 숫자 | PCB |
| toxic_chemical_discard | 참/거짓 | 화학물질관리법상 유해화학물질 폐기 |
| norm_bq_g | 숫자(Bq/g) | 천연방사성 농도 |
| leach_pb, leach_cu, leach_as, leach_hg, leach_cd, leach_cr6, leach_cn, leach_op, leach_pce, leach_tce | 숫자(mg/L) | 용출시험 결과 |
| battery_damaged | 참/거짓 | 폐이차전지 침수·화재·변형·파손 등 |

## 모을 곳 (우선순위 순)

1. 이미 보유한 자료 (다시 받지 않는다)
   - `sources/raw/tc-moe-qa-casebook-2025-07.pdf` 환경부 질의회신 사례집 2025.7 — 자원순환 분야(인쇄면 약 p.232~268)와 화학물질 분야의 폐기물 사례 전부
   - `sources/raw/wonju-qa-2026.pdf` 원주지방환경청 지정폐기물 질의·회신 사례집 — 전체
   - `sources/raw/add-case-*.html` 대법원 판결 10건 — 폐기물 해당 여부 쟁점
   - `sources/raw/add-qa-expc-329297.html` 법제처 해석례
   - `sources/raw/add-qa-moe-2009.hwp`, `sources/raw/wonju-environment-qa-volume2-posted-2026-08-11.hwp` (HWP: 열 수 없으면 실패 목록에)
   - `sources/raw/wonju-recycling-qa-posted-2026-08-11.pdf` 재활용 사례집(이미지 PDF: 글자를 읽을 수 없으면 실패 목록에. 추측해서 옮기지 않는다)
   - `sources/raw/classification-guide-2023.pdf` 2023 분류 설명서의 사례 상자 (텍스트가 깨지면 쪽 이미지로 읽는다)
2. 환경부 「질의회신 사례집」 다른 연도판(2022·2023·2024·2026), 다른 유역·지방환경청 사례집
3. 법제처 법령해석례 중 폐기물관리법 관련, 대법원 판례 중 폐기물 분류·지정폐기물·재활용 유형 쟁점

이미 규칙 근거로 쓴 사례(아래)는 모으되 반드시 `split=DEV`:
2023 설명서 p.117 사례 1·2, p.118 스펀지 사례, 원주 사례 52·56·63, 2025 사례집 p.242·p.245.

목표: 기관이 단계 결론을 분명히 말한 사례 **40건 이상**. 못 채우면 채운 만큼만 하고 이유를 보고한다.

## 출력

### 1. `testdata/cases.jsonl` — 사례 한 건에 한 줄(JSON)

```json
{
  "case_id": "MOE25-245",
  "source": {"file": "sources/raw/tc-moe-qa-casebook-2025-07.pdf", "page": "인쇄면 245", "issuer": "환경부",
             "answered_on": "NOT_FOUND", "law_version_note": "2023~2025 질의, 개별 회신일 미표기"},
  "question_quote": "…원문…",
  "answer_quote": "…원문…",
  "facts": {"waste_kind": "paint_container", "paint_dried": false},
  "fact_quotes": {"waste_kind": "…근거 구절…", "paint_dried": "…근거 구절…"},
  "unmapped_facts": ["원문에 있으나 사실 목록에 없는 표현"],
  "expected": {"S3": "DESIGNATED", "S4": null},
  "expected_quotes": {"S3": "…회신 중 결론 구절…"},
  "answer_type": "CODE_GIVEN | CODE_CONDITIONAL | DESIGNATED_ONLY | NOT_WASTE | TEST_REQUIRED | CASE_BY_CASE | OTHER",
  "conditions_quote": "조건부 회신이면 그 조건 구절, 아니면 null",
  "legacy_code": false,
  "split": "DEV | EVAL",
  "review_note": null
}
```

- `expected`에는 기관이 결론을 말한 단계만 넣는다. 말하지 않은 단계는 키를 넣지 않는다.
- 회신이 "시험 결과에 따라 다르다"면 `answer_type=TEST_REQUIRED`, 해당 단계 기대값은 `"UNDECIDED"`.
- 회신이 "사안별·관할 기관 판단"이면 `answer_type=CASE_BY_CASE`, 기대값 `"UNDECIDED"`.

### 2. `testdata/case_pairs.csv`
사실 하나 차이로 결론이 갈리는 사례 쌍: `pair_id, case_id_a, case_id_b, differing_fact, note`

### 3. `testdata/unreachable.csv`
받거나 읽지 못한 모든 자료: `url_or_file, attempted_at, failure_type, error_detail, manual_steps`

### 4. `testdata/collection_report.md`
- 출처별 건수, `answer_type`별 건수, 단계별 기대값이 있는 사례 수
- `split`별 건수와 EVAL에 들어간 문서 목록 (같은 문서·같은 사례 번호의 질의는 같은 쪽에)
- 사례가 0건인 `waste_kind` 값 목록
- `legacy_code=true` 사례 목록 (사람이 현행 번호로 옮길지 결정)
- `unmapped_facts`에 자주 나온 표현 (계산기에 사실을 추가할 후보)
- 읽지 못한 자료와 이유
