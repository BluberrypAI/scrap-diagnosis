# 규칙 빌드 보고서

- 원본: `knowledge/` (3fbc9eae). 기존 엔진 resource_engine `2f1355a`의 rules/에서 옮겨 왔다.
- 소재 테이블: 97개, 시행일 2026-10-02
- 전문가 검토(`knowledge/reviews.yaml`): 생성 규칙 0개가 `VERIFIED`, 나머지는 `UNVERIFIED`다.

## 우선순위 대역
| 대역 | priority | 내용 |
|---|---|---|
| SCOPE_S0 | 1100 | 순환자원·폐기물 아님 (법령 아닌 근거는 해석 필요) |
| SCOPE_S1 | 1000 | 폐기물관리법 적용 제외 |
| DESIGNATED | 500 | 법령 근거 지정폐기물 → 별표 4 지정 코드 |
| HOUSEHOLD | 400 | 사업장 조건 모두 거짓 → 생활폐기물 |
| INTERPRET | 300 | 해석 필요, 질의회신 근거 규칙 |
| GENERAL | 100 | 사업장일반폐기물 코드 |

## 소재 2단계 질문
- 소재 분류(material_group, 기존 materials.yaml groups) → 그 분류의 소재(material).
- 규칙은 소재만 참조한다. 분류는 소재 선택지를 줄이고, 소재가 하나면 자동으로 정한다.
- plastic 플라스틱·고무: 소재 14개
- metal 금속: 소재 4개
- slag 광재(슬래그): 소재 6개
- dust_ash 분진·소각재: 소재 8개
- sand 주물사·폐사·내화물: 소재 5개
- sludge 오니(슬러지): 소재 11개
- oil 기름: 소재 7개
- acid_alkali 산·알칼리: 소재 11개
- solvent_paint 용제·페인트: 소재 5개
- wood_paper_fiber 목재·종이·섬유·유리: 소재 9개
- catalyst_adsorbent 촉매·흡착제: 소재 6개
- product 제품·복합물: 소재 10개
- special 여러 소재가 섞여 나누기 어려운 것: 소재 1개

## 변환하지 않은 기능
- 결정 카드(해석 선택, residue_choice 등): 해석 필요 규칙은 판정 불가로 안내한다.
- S5 재활용 유형(별표 4의3), S6 배출자신고·처리계획: 이번 범위 밖.
- '그 밖의' 번호를 고를 때의 no_specific_code_applies 확인: 선택지로만 제시한다.
- 일반 코드를 정할 수 없는 소재(general_group 경로)는 NO_GENERAL_CODE로 안내한다.

## 의도한 차이
- 지정 사유가 여럿일 때 기존 엔진은 사유별 번호 범위를 합친 뒤, 모든 사유가 소재 자체에서 나온 경우에만 소재 번호로 좁혔다. 새 테이블은 사유마다 따로 좁힌 뒤 합친다. 그래서 선택지가 기존보다 적거나 같다(예: 액상 PP + 유해화학물질 → 01-01-02와 09번대).
- 산·알칼리 + 유해화학물질: 법이 제9호를 제외하므로 제외를 먼저 적용해 산·알칼리 번호 하나로 정한다(기존은 선택지 여러 개).
- 지정 기준 미만 산·알칼리: 기존은 일반 그룹·번호를 물었지만 NO_GENERAL_CODE로 안내한다.
- pH가 2.0 이하가 아닌 산은 먼저 유기용제 혼합 여부를 묻고, 섞였으면 폐유기용제일 수 있어 해석 필요로 안내한다(S3-4-ACID_SOLVENT_MIX, 원주청 질의회신 사례 56). 기존 판정표에는 이 사실이 없다.
- 회귀 비교 결과는 regression/summary.md, 허용 기준은 tests/test_legacy_regression.py.
- 시험 수치 조건은 `min_status: EVIDENCED`다. 지정 판정에는 성적서가 필요하고, 기준 미만 진술로는 지정 후보를 지울 수 있다.

## 일반 코드 대신 안내로 끝나는 소재 (26)
- sludge_ww_unknown: CODE_NEEDS_TEST
- sludge_proc_unknown: CODE_NEEDS_TEST
- lube_oil: NO_GENERAL_CODE
- cutting_oil_insoluble: NO_GENERAL_CODE
- machine_oil: NO_GENERAL_CODE
- fuel_oil: NO_GENERAL_CODE
- oil_filter: NO_GENERAL_CODE
- insulating_oil: NO_GENERAL_CODE
- cutting_oil_soluble: NO_GENERAL_CODE
- hcl: NO_GENERAL_CODE
- h2so4: NO_GENERAL_CODE
- hno3: NO_GENERAL_CODE
- hf: NO_GENERAL_CODE
- acid_lcd_semi: NO_GENERAL_CODE
- acid_other: NO_GENERAL_CODE
- caustic_solution: NO_GENERAL_CODE
- ammonia_solution: NO_GENERAL_CODE
- naoh_solid: NO_GENERAL_CODE
- koh_solid: NO_GENERAL_CODE
- alkali_other: NO_GENERAL_CODE
- solvent_halogen: NO_GENERAL_CODE
- solvent_other: NO_GENERAL_CODE
- paint_oil: NO_GENERAL_CODE
- paint_water: NO_GENERAL_CODE
- lacquer: NO_GENERAL_CODE
- mixed_inseparable: NO_MIXTURE_RULE

## 번호 범위 대응이 없는 지정 규칙 (0)
- 없음

## 변환하지 않은 소재 (1)
- unlisted: 목록에 없는 소재(unlisted)

## 소재별 규칙 수
- pp: 지정 5규칙/17코드, 해석 6, 일반 1
- pe: 지정 5규칙/17코드, 해석 6, 일반 1
- pet: 지정 5규칙/17코드, 해석 6, 일반 1
- ps: 지정 5규칙/17코드, 해석 6, 일반 1
- abs: 지정 5규칙/17코드, 해석 6, 일반 1
- phenol_resin: 지정 5규칙/17코드, 해석 6, 일반 1
- other_resin: 지정 5규칙/17코드, 해석 6, 일반 1
- pvc: 지정 5규칙/17코드, 해석 6, 일반 1
- pu_foam: 지정 3규칙/15코드, 해석 6, 일반 1
- eps: 지정 3규칙/15코드, 해석 6, 일반 1
- plastic_packaging: 지정 3규칙/15코드, 해석 6, 일반 1
- fishing_net: 지정 3규칙/15코드, 해석 6, 일반 1
- aqua_buoy: 지정 3규칙/15코드, 해석 6, 일반 1
- rubber: 지정 5규칙/17코드, 해석 6, 일반 1
- ferrous_scrap: 지정 4규칙/16코드, 해석 6, 일반 1
- nonferrous_scrap: 지정 4규칙/16코드, 해석 6, 일반 1
- metal_can: 지정 4규칙/16코드, 해석 6, 일반 1
- metal_container: 지정 4규칙/16코드, 해석 6, 일반 1
- bf_slag: 지정 4규칙/16코드, 해석 0, 일반 1
- steel_slag: 지정 12규칙/17코드, 해석 0, 일반 1
- slag_aluminum: 지정 12규칙/17코드, 해석 0, 일반 1
- slag_lead: 지정 12규칙/17코드, 해석 0, 일반 1
- slag_zinc: 지정 12규칙/17코드, 해석 0, 일반 1
- slag_nonferrous_other: 지정 12규칙/17코드, 해석 0, 일반 1
- dust_steel: 지정 11규칙/17코드, 해석 0, 일반 1
- dust_cement: 지정 11규칙/17코드, 해석 0, 일반 1
- dust_power: 지정 11규칙/17코드, 해석 0, 일반 1
- silica_fume: 지정 11규칙/17코드, 해석 0, 일반 1
- dust_other: 지정 11규칙/17코드, 해석 0, 일반 1
- fly_ash_business: 지정 11규칙/17코드, 해석 0, 일반 1
- bottom_ash_business: 지정 11규칙/17코드, 해석 0, 일반 1
- mixed_ash_business: 지정 11규칙/17코드, 해석 0, 일반 1
- foundry_clay: 지정 12규칙/17코드, 해석 0, 일반 1
- foundry_chemical: 지정 12규칙/17코드, 해석 0, 일반 1
- sandblast: 지정 12규칙/17코드, 해석 0, 일반 1
- filter_sand: 지정 12규칙/17코드, 해석 0, 일반 1
- refractory: 지정 12규칙/17코드, 해석 0, 일반 1
- sludge_ww_pulp_paper: 지정 15규칙/17코드, 해석 0, 일반 1
- sludge_ww_stone: 지정 15규칙/17코드, 해석 0, 일반 1
- sludge_ww_organic: 지정 15규칙/17코드, 해석 0, 일반 1
- sludge_ww_inorganic: 지정 15규칙/17코드, 해석 0, 일반 1
- sludge_ww_unknown: 지정 15규칙/17코드, 해석 0, 일반 CODE_NEEDS_TEST
- sludge_proc_pulp_paper: 지정 15규칙/17코드, 해석 0, 일반 1
- sludge_proc_glass_etching: 지정 15규칙/17코드, 해석 0, 일반 1
- sludge_proc_silicon: 지정 15규칙/17코드, 해석 0, 일반 1
- sludge_proc_organic: 지정 15규칙/17코드, 해석 0, 일반 1
- sludge_proc_inorganic: 지정 15규칙/17코드, 해석 0, 일반 1
- sludge_proc_unknown: 지정 15규칙/17코드, 해석 0, 일반 CODE_NEEDS_TEST
- lube_oil: 지정 3규칙/6코드, 해석 0, 일반 NO_GENERAL_CODE
- cutting_oil_insoluble: 지정 3규칙/6코드, 해석 0, 일반 NO_GENERAL_CODE
- machine_oil: 지정 3규칙/6코드, 해석 0, 일반 NO_GENERAL_CODE
- fuel_oil: 지정 3규칙/6코드, 해석 0, 일반 NO_GENERAL_CODE
- oil_filter: 지정 4규칙/6코드, 해석 0, 일반 NO_GENERAL_CODE
- insulating_oil: 지정 3규칙/6코드, 해석 0, 일반 NO_GENERAL_CODE
- cutting_oil_soluble: 지정 3규칙/6코드, 해석 0, 일반 NO_GENERAL_CODE
- hcl: 지정 4규칙/16코드, 해석 1, 일반 NO_GENERAL_CODE
- h2so4: 지정 4규칙/16코드, 해석 1, 일반 NO_GENERAL_CODE
- hno3: 지정 4규칙/16코드, 해석 1, 일반 NO_GENERAL_CODE
- hf: 지정 4규칙/16코드, 해석 1, 일반 NO_GENERAL_CODE
- acid_lcd_semi: 지정 4규칙/16코드, 해석 1, 일반 NO_GENERAL_CODE
- acid_other: 지정 4규칙/16코드, 해석 1, 일반 NO_GENERAL_CODE
- caustic_solution: 지정 4규칙/16코드, 해석 0, 일반 NO_GENERAL_CODE
- ammonia_solution: 지정 4규칙/16코드, 해석 0, 일반 NO_GENERAL_CODE
- naoh_solid: 지정 4규칙/16코드, 해석 0, 일반 NO_GENERAL_CODE
- koh_solid: 지정 4규칙/16코드, 해석 0, 일반 NO_GENERAL_CODE
- alkali_other: 지정 4규칙/16코드, 해석 0, 일반 NO_GENERAL_CODE
- solvent_halogen: 지정 5규칙/16코드, 해석 0, 일반 NO_GENERAL_CODE
- solvent_other: 지정 5규칙/16코드, 해석 0, 일반 NO_GENERAL_CODE
- paint_oil: 지정 5규칙/17코드, 해석 0, 일반 NO_GENERAL_CODE
- paint_water: 지정 5규칙/17코드, 해석 0, 일반 NO_GENERAL_CODE
- lacquer: 지정 5규칙/17코드, 해석 0, 일반 NO_GENERAL_CODE
- wood_clean: 지정 4규칙/16코드, 해석 6, 일반 1
- wood_treated: 지정 4규칙/16코드, 해석 6, 일반 1
- wood_preservative: 지정 4규칙/16코드, 해석 6, 일반 1
- wood_byproduct: 지정 4규칙/16코드, 해석 6, 일반 1
- paper: 지정 4규칙/16코드, 해석 6, 일반 1
- fiber_natural: 지정 4규칙/16코드, 해석 6, 일반 1
- fiber_synthetic: 지정 4규칙/16코드, 해석 6, 일반 1
- glass: 지정 4규칙/16코드, 해석 6, 일반 1
- glass_fiber: 지정 4규칙/16코드, 해석 6, 일반 1
- catalyst_metal: 지정 12규칙/17코드, 해석 0, 일반 1
- catalyst_nonmetal: 지정 12규칙/17코드, 해석 0, 일반 1
- ion_exchange_resin: 지정 12규칙/18코드, 해석 0, 일반 1
- activated_carbon: 지정 14규칙/7코드, 해석 0, 일반 1
- adsorbent: 지정 14규칙/7코드, 해석 0, 일반 1
- absorbent: 지정 14규칙/7코드, 해석 0, 일반 1
- coated_wire: 지정 3규칙/15코드, 해석 6, 일반 1
- eee_industrial: 지정 4규칙/16코드, 해석 6, 일반 1
- tire_auto: 지정 5규칙/17코드, 해석 6, 일반 1
- solar_panel: 지정 4규칙/16코드, 해석 6, 일반 1
- battery_primary: 지정 4규칙/16코드, 해석 1, 일반 1
- battery_ev: 지정 4규칙/16코드, 해석 1, 일반 1
- battery_drive: 지정 4규칙/16코드, 해석 1, 일반 1
- battery_cathode: 지정 4규칙/16코드, 해석 1, 일반 1
- battery_fuel_cell: 지정 4규칙/16코드, 해석 1, 일반 1
- battery_secondary_other: 지정 4규칙/16코드, 해석 1, 일반 1
- mixed_inseparable: 지정 4규칙/16코드, 해석 6, 일반 NO_MIXTURE_RULE
