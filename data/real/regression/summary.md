# 기존 엔진 판정표 회귀 결과

`uv run python tools/legacy_regression.py --write`로 생성. 허용 기준은 tests/test_legacy_regression.py.

```json
{
  "rows": 4281,
  "verdicts": {
    "MATCH": 2884,
    "FEWER_CHOICES": 1361,
    "DIFF": 36
  },
  "by_kind": {
    "CODE/MATCH": 2332,
    "CODE_CHOICE/DIFF": 36,
    "CODE_CHOICE/FEWER_CHOICES": 1361,
    "CODE_CHOICE/MATCH": 319,
    "STOP/MATCH": 233
  },
  "extra_questions": {
    "0": 4083,
    "1": 198
  }
}
```

## 다른 행 (36)
- hcl#2 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 2.04} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- hcl#5 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": true, "ph": 2.04, "pcb_mg_l": 1.96} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- hcl#7 {"oil_presence": "none", "toxic_chemical_discard": true, "pcb_possible": false, "ph": 1.96} → 기대 번호 선택(6) / 결과 FINAL_REVIEW 02-01-01
- hcl#11 {"oil_presence": "present", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 2.04, "oil_content_pct": 4.9} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- h2so4#2 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 2.04} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- h2so4#5 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": true, "ph": 2.04, "pcb_mg_l": 1.96} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- h2so4#7 {"oil_presence": "none", "toxic_chemical_discard": true, "pcb_possible": false, "ph": 1.96} → 기대 번호 선택(6) / 결과 FINAL_REVIEW 02-01-02
- h2so4#11 {"oil_presence": "present", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 2.04, "oil_content_pct": 4.9} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- hno3#2 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 2.04} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- hno3#5 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": true, "ph": 2.04, "pcb_mg_l": 1.96} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- hno3#7 {"oil_presence": "none", "toxic_chemical_discard": true, "pcb_possible": false, "ph": 1.96} → 기대 번호 선택(6) / 결과 FINAL_REVIEW 02-01-03
- hno3#11 {"oil_presence": "present", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 2.04, "oil_content_pct": 4.9} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- hf#2 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 2.04} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- hf#5 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": true, "ph": 2.04, "pcb_mg_l": 1.96} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- hf#7 {"oil_presence": "none", "toxic_chemical_discard": true, "pcb_possible": false, "ph": 1.96} → 기대 번호 선택(6) / 결과 FINAL_REVIEW 02-01-04
- hf#11 {"oil_presence": "present", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 2.04, "oil_content_pct": 4.9} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- acid_lcd_semi#2 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 2.04} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- acid_lcd_semi#5 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": true, "ph": 2.04, "pcb_mg_l": 1.96} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- acid_lcd_semi#7 {"oil_presence": "none", "toxic_chemical_discard": true, "pcb_possible": false, "ph": 1.96} → 기대 번호 선택(6) / 결과 FINAL_REVIEW 02-01-05
- acid_lcd_semi#11 {"oil_presence": "present", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 2.04, "oil_content_pct": 4.9} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- acid_other#2 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 2.04} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- acid_other#5 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": true, "ph": 2.04, "pcb_mg_l": 1.96} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- acid_other#7 {"oil_presence": "none", "toxic_chemical_discard": true, "pcb_possible": false, "ph": 1.96} → 기대 번호 선택(6) / 결과 FINAL_REVIEW 02-01-99
- acid_other#11 {"oil_presence": "present", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 2.04, "oil_content_pct": 4.9} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- caustic_solution#1 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 12.25} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- caustic_solution#3 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": true, "ph": 12.25, "pcb_mg_l": 1.96} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- caustic_solution#8 {"oil_presence": "none", "toxic_chemical_discard": true, "pcb_possible": false, "ph": 12.75} → 기대 번호 선택(5) / 결과 FINAL_REVIEW 02-02-01
- caustic_solution#9 {"oil_presence": "present", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 12.25, "oil_content_pct": 4.9} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- ammonia_solution#1 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 12.25} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- ammonia_solution#3 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": true, "ph": 12.25, "pcb_mg_l": 1.96} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- ammonia_solution#8 {"oil_presence": "none", "toxic_chemical_discard": true, "pcb_possible": false, "ph": 12.75} → 기대 번호 선택(5) / 결과 FINAL_REVIEW 02-02-02
- ammonia_solution#9 {"oil_presence": "present", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 12.25, "oil_content_pct": 4.9} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- alkali_other#1 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 12.25} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- alkali_other#3 {"oil_presence": "none", "toxic_chemical_discard": false, "pcb_possible": true, "ph": 12.25, "pcb_mg_l": 1.96} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE
- alkali_other#8 {"oil_presence": "none", "toxic_chemical_discard": true, "pcb_possible": false, "ph": 12.75} → 기대 번호 선택(5) / 결과 FINAL_REVIEW 02-02-99
- alkali_other#9 {"oil_presence": "present", "toxic_chemical_discard": false, "pcb_possible": false, "ph": 12.25, "oil_content_pct": 4.9} → 기대 번호 선택(47) / 결과 UNSUPPORTED NO_GENERAL_CODE

## 선택지가 기존보다 적은 행 (1361) — 앞 30개
- pp#14 {"physical_state": "liquid", "oil_presence": "none", "pcb_possible": false, "toxic_chemical_discard": true} → 기대 선택지 14개 / 결과 5개
- pp#16 {"physical_state": "liquid", "oil_presence": "none", "pcb_possible": true, "toxic_chemical_discard": false, "pcb_mg_l": 2.04} → 기대 선택지 14개 / 결과 2개
- pp#18 {"physical_state": "liquid", "oil_presence": "present", "pcb_possible": false, "toxic_chemical_discard": false, "oil_content_pct": 5.1} → 기대 선택지 20개 / 결과 11개
- pp#20 {"physical_state": "semisolid", "oil_presence": "none", "pcb_possible": false, "toxic_chemical_discard": true} → 기대 선택지 14개 / 결과 5개
- pp#22 {"physical_state": "semisolid", "oil_presence": "none", "pcb_possible": true, "toxic_chemical_discard": false, "pcb_leach_mg_l": 0.004} → 기대 선택지 14개 / 결과 2개
- pp#24 {"physical_state": "semisolid", "oil_presence": "present", "pcb_possible": false, "toxic_chemical_discard": false, "oil_content_pct": 5.1} → 기대 선택지 20개 / 결과 11개
- pe#14 {"physical_state": "liquid", "oil_presence": "none", "pcb_possible": false, "toxic_chemical_discard": true} → 기대 선택지 14개 / 결과 5개
- pe#16 {"physical_state": "liquid", "oil_presence": "none", "pcb_possible": true, "toxic_chemical_discard": false, "pcb_mg_l": 2.04} → 기대 선택지 14개 / 결과 2개
- pe#18 {"physical_state": "liquid", "oil_presence": "present", "pcb_possible": false, "toxic_chemical_discard": false, "oil_content_pct": 5.1} → 기대 선택지 20개 / 결과 11개
- pe#20 {"physical_state": "semisolid", "oil_presence": "none", "pcb_possible": false, "toxic_chemical_discard": true} → 기대 선택지 14개 / 결과 5개
- pe#22 {"physical_state": "semisolid", "oil_presence": "none", "pcb_possible": true, "toxic_chemical_discard": false, "pcb_leach_mg_l": 0.004} → 기대 선택지 14개 / 결과 2개
- pe#24 {"physical_state": "semisolid", "oil_presence": "present", "pcb_possible": false, "toxic_chemical_discard": false, "oil_content_pct": 5.1} → 기대 선택지 20개 / 결과 11개
- pet#14 {"physical_state": "liquid", "oil_presence": "none", "pcb_possible": false, "toxic_chemical_discard": true} → 기대 선택지 14개 / 결과 5개
- pet#16 {"physical_state": "liquid", "oil_presence": "none", "pcb_possible": true, "toxic_chemical_discard": false, "pcb_mg_l": 2.04} → 기대 선택지 14개 / 결과 2개
- pet#18 {"physical_state": "liquid", "oil_presence": "present", "pcb_possible": false, "toxic_chemical_discard": false, "oil_content_pct": 5.1} → 기대 선택지 20개 / 결과 11개
- pet#20 {"physical_state": "semisolid", "oil_presence": "none", "pcb_possible": false, "toxic_chemical_discard": true} → 기대 선택지 14개 / 결과 5개
- pet#22 {"physical_state": "semisolid", "oil_presence": "none", "pcb_possible": true, "toxic_chemical_discard": false, "pcb_leach_mg_l": 0.004} → 기대 선택지 14개 / 결과 2개
- pet#24 {"physical_state": "semisolid", "oil_presence": "present", "pcb_possible": false, "toxic_chemical_discard": false, "oil_content_pct": 5.1} → 기대 선택지 20개 / 결과 11개
- ps#14 {"physical_state": "liquid", "oil_presence": "none", "pcb_possible": false, "toxic_chemical_discard": true} → 기대 선택지 14개 / 결과 5개
- ps#16 {"physical_state": "liquid", "oil_presence": "none", "pcb_possible": true, "toxic_chemical_discard": false, "pcb_mg_l": 2.04} → 기대 선택지 14개 / 결과 2개
- ps#18 {"physical_state": "liquid", "oil_presence": "present", "pcb_possible": false, "toxic_chemical_discard": false, "oil_content_pct": 5.1} → 기대 선택지 20개 / 결과 11개
- ps#20 {"physical_state": "semisolid", "oil_presence": "none", "pcb_possible": false, "toxic_chemical_discard": true} → 기대 선택지 14개 / 결과 5개
- ps#22 {"physical_state": "semisolid", "oil_presence": "none", "pcb_possible": true, "toxic_chemical_discard": false, "pcb_leach_mg_l": 0.004} → 기대 선택지 14개 / 결과 2개
- ps#24 {"physical_state": "semisolid", "oil_presence": "present", "pcb_possible": false, "toxic_chemical_discard": false, "oil_content_pct": 5.1} → 기대 선택지 20개 / 결과 11개
- abs#14 {"physical_state": "liquid", "oil_presence": "none", "pcb_possible": false, "toxic_chemical_discard": true} → 기대 선택지 14개 / 결과 5개
- abs#16 {"physical_state": "liquid", "oil_presence": "none", "pcb_possible": true, "toxic_chemical_discard": false, "pcb_mg_l": 2.04} → 기대 선택지 14개 / 결과 2개
- abs#18 {"physical_state": "liquid", "oil_presence": "present", "pcb_possible": false, "toxic_chemical_discard": false, "oil_content_pct": 5.1} → 기대 선택지 20개 / 결과 11개
- abs#20 {"physical_state": "semisolid", "oil_presence": "none", "pcb_possible": false, "toxic_chemical_discard": true} → 기대 선택지 14개 / 결과 5개
- abs#22 {"physical_state": "semisolid", "oil_presence": "none", "pcb_possible": true, "toxic_chemical_discard": false, "pcb_leach_mg_l": 0.004} → 기대 선택지 14개 / 결과 2개
- abs#24 {"physical_state": "semisolid", "oil_presence": "present", "pcb_possible": false, "toxic_chemical_discard": false, "oil_content_pct": 5.1} → 기대 선택지 20개 / 결과 11개
