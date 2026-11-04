"""실제 사례 시험에서 드러난 빈틈 3가지의 보완 검증."""
from wastecalc import evaluate, load_kb

KB = load_kb(as_of="2026-11-05")
S01 = {"no_longer_needed": True, "direct_reinput": False, "continuous_feedstock": False,
       "circular_resource_recognized": False, "law_exclusion": "none"}
BIZ = {**S01, "emission_facility": True}
GATES_NO = {"oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": False}
SMALL_HOME = {**S01, "emission_facility": False, "public_facility": "none", "waste_facility": False,
              "designated_waste_emitted": False, "daily_avg_kg": 1, "work_type": "none"}


def ev(a):
    return evaluate(a, strict=False, kb=KB)


def ev_ref(a):
    """해석 근거 결론까지 보는 참고 경로(평가 도구용)."""
    return evaluate(a, strict=False, kb=KB, allow_interpretive=True)


def stage(r, s):
    return next((d for d in r["decided"] if d["stage"] == s), None)


# ① 지정폐기물이 남은 용기
def test_drum_with_solvent_residue_consults_regional_office():
    a = {**BIZ, "waste_kind": "other", "physical_state": "solid", **GATES_NO,
         "designated_residue": True, "residue_kind": "organic_solvent"}
    r = ev(a)
    assert r["status"] == "NEED_EXPERT" and r["reason"] == "INTERPRETATION_NEEDED" and r["stage"] == "S3"
    assert r["reference_conclusion"]["label"] == "지정폐기물"
    assert r["consult"]["where"][0]["name"] == "관할 유역(지방)환경청"  # 배출시설 있는 공장의 지정폐기물
    assert "유기용제" in r["consult"]["draft"] and "p.245" in r["consult"]["draft"]
    ref = ev_ref(a)
    assert stage(ref, "S3")["conclusion"] == "DESIGNATED"
    assert all(k.startswith("04") for k in ref["resolution"][0]["allowed_values"])  # 폐유기용제 번호만


def test_interpretive_designation_does_not_make_small_shop_business_waste():
    """해석 근거로만 '지정'이면, 작은 사업장을 사업장폐기물로 만드는 데 쓰지 않는다."""
    r = ev({**SMALL_HOME, "waste_kind": "other", "physical_state": "solid", **GATES_NO,
            "designated_residue": True, "residue_kind": "waste_oil"})
    assert r["status"] == "NEED_EXPERT" and r["stage"] == "S3"
    assert stage(r, "S2") is None or stage(r, "S2")["conclusion"] != "BUSINESS" or         "앞 판정 결과" not in " ".join(stage(r, "S2")["explanation"]["because"])


def test_washed_container_is_general_by_material():
    r = ev({**BIZ, "waste_kind": "synthetic_resin", "physical_state": "solid", **GATES_NO,
            "designated_residue": False})
    assert stage(r, "S3")["conclusion"] == "NOT_DESIGNATED"


def test_residue_question_is_asked_for_containers():
    r = ev({**BIZ, "waste_kind": "other", "physical_state": "solid"})
    assert r["next_question"]["fact"] == "designated_residue"


def test_residue_question_not_asked_for_liquid_acid():
    r = ev({**BIZ, "waste_kind": "acid", "physical_state": "liquid", **GATES_NO})
    assert r["next_question"]["fact"] == "ph"


def test_residue_rule_never_concludes_by_default():
    a = {**BIZ, "waste_kind": "other", "physical_state": "solid", **GATES_NO,
         "designated_residue": True, "residue_kind": "waste_oil", "code": "06-01-99", "no_specific_code_applies": True}
    for strict in (True, False):
        r = evaluate(a, strict=strict, kb=KB)
        assert r["status"] == "NEED_EXPERT" and stage(r, "S3") is None and stage(r, "S4") is None
    assert stage(ev_ref(a), "S3")["law_based"] is False


# ② 의료폐기물 발생처
def test_home_care_medical_waste_is_household():
    r = ev({**SMALL_HOME, "waste_kind": "medical", "medical_institution": False, "physical_state": "solid", **GATES_NO})
    assert stage(r, "S2")["conclusion"] == "HOUSEHOLD"


def test_clinic_medical_waste_is_designated_business_waste():
    r = ev({**SMALL_HOME, "daily_avg_kg": 50, "waste_kind": "medical", "medical_institution": True,
            "physical_state": "solid", **GATES_NO})
    assert stage(r, "S2")["conclusion"] == "BUSINESS"
    assert stage(r, "S3")["conclusion"] == "DESIGNATED"


def test_medical_asks_institution_first():
    r = ev({**BIZ, "waste_kind": "medical", "physical_state": "solid", **GATES_NO})
    assert r["next_question"]["fact"] == "medical_institution"


# ③ 연속공정으로 다른 제품 원료 투입
def test_byproduct_fed_continuously_to_other_product_is_not_waste():
    a = {"no_longer_needed": True, "direct_reinput": False, "continuous_feedstock": True,
         "circular_resource_recognized": False}
    r = ev(a)
    assert r["status"] == "NEED_EXPERT" and r["reference_conclusion"]["label"] == "폐기물 아님"
    s0 = stage(ev_ref(a), "S0")
    assert s0["conclusion"] == "NOT_WASTE" and s0["law_based"] is False


def test_byproduct_sold_after_storage_is_still_waste():
    r = ev({"no_longer_needed": True, "direct_reinput": False, "continuous_feedstock": False,
            "circular_resource_recognized": False})
    assert stage(r, "S0")["conclusion"] == "WASTE"


def test_law_based_conclusions_are_not_affected():
    r = ev({**BIZ, "waste_kind": "acid", "physical_state": "liquid", "ph": 1, **GATES_NO})
    assert stage(r, "S3")["conclusion"] == "DESIGNATED" and "consult" not in r


def test_damaged_battery_gives_consult_draft():
    r = ev({**BIZ, "waste_kind": "battery", "physical_state": "solid", "battery_damaged": True, **GATES_NO})
    assert r["reason"] == "INTERPRETATION_NEEDED" and r["consult"]["where"]
    assert "시행령 별표 1" in r["consult"]["draft"]


def test_general_waste_ambiguity_goes_to_local_office():
    from wastecalc.engine import _consult, parse_answers
    c = _consult(KB, "S4", parse_answers(KB, {"emission_facility": True}),
                 [{"stage": "S3", "conclusion": "NOT_DESIGNATED"}], "분류번호 애매", [])
    assert c["where"][0]["name"] == "관할 시·군·구 환경 담당 부서"
