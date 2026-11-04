import random

import pytest

from wastecalc import UNKNOWN, evaluate, load_kb
from wastecalc.engine import TRUE, eval_stage, parse_answers

KB = load_kb()
BIZ = {"no_longer_needed": True, "direct_reinput": False, "circular_resource_recognized": False,
       "law_exclusion": "none", "emission_facility": True}
GATES_NO = {"oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": False}


def ev(extra, strict=False):
    return evaluate({**BIZ, **extra}, strict=strict, kb=KB)


def s3(r):
    return next(d for d in r["decided"] if d["stage"] == "S3")


# ---------------------------------------------------------------- 부식성 폐기물 경계값

@pytest.mark.parametrize("ph,designated", [(1.99, True), (2.0, True), (2.01, False)])
def test_acid_ph_boundary(ph, designated):
    r = ev({"waste_kind": "acid", "physical_state": "liquid", "ph": ph, **GATES_NO})
    assert (s3(r)["conclusion"] == "DESIGNATED") is designated


@pytest.mark.parametrize("ph,designated", [(12.49, False), (12.5, True), (12.51, True)])
def test_alkali_ph_boundary(ph, designated):
    r = ev({"waste_kind": "alkali", "physical_state": "liquid", "ph": ph,
            "alkali_solid_naoh_koh": False, **GATES_NO})
    assert (s3(r)["conclusion"] == "DESIGNATED") is designated


def test_solid_naoh_is_designated_alkali():
    r = ev({"waste_kind": "alkali", "physical_state": "solid", "alkali_solid_naoh_koh": True})
    assert s3(r)["conclusion"] == "DESIGNATED"
    assert "폐알칼리(수산화나트륨·수산화칼륨)" in s3(r)["items"]


def test_acid_without_ph_asks_for_test_with_method():
    r = ev({"waste_kind": "acid", "physical_state": "liquid", **GATES_NO})
    assert r["status"] == "NEED_TEST"
    assert r["next_question"]["fact"] == "ph"
    assert "ES 06304.1" in r["next_question"]["test"]["method"]


# ---------------------------------------------------------------- 폐유(기름성분 5%)

@pytest.mark.parametrize("pct,designated", [(4.99, False), (5, True)])
def test_oily_scrap_oil_content_boundary(pct, designated):
    r = ev({"waste_kind": "other", "physical_state": "solid", "oil_presence": "present", "oil_content_pct": pct,
            "pcb_possible": False, "toxic_chemical_discard": False})
    assert (s3(r)["conclusion"] == "DESIGNATED") is designated


def test_oily_scrap_unknown_content_needs_oil_test():
    r = ev({"waste_kind": "other", "physical_state": "solid", "oil_presence": "present",
            "pcb_possible": False, "toxic_chemical_discard": False})
    assert r["status"] == "NEED_TEST"
    assert "ES 06302.1b" in r["next_question"]["test"]["method"]


def test_edible_oil_is_not_waste_oil():
    r = ev({"waste_kind": "edible_oil", "physical_state": "liquid", "oil_presence": "present",
            "oil_content_pct": 100, "pcb_possible": False, "toxic_chemical_discard": False})
    assert s3(r)["conclusion"] == "NOT_DESIGNATED"


# ---------------------------------------------------------------- 폐페인트 용기 6mm

@pytest.mark.parametrize("dried,mm,designated", [(True, 6, False), (True, 6.01, True), (False, 1, True)])
def test_paint_container(dried, mm, designated):
    r = ev({"waste_kind": "paint_container", "physical_state": "solid", "paint_dried": dried,
            "paint_residue_mm": mm, **GATES_NO})
    assert (s3(r)["conclusion"] == "DESIGNATED") is designated


def test_paint_mix_from_small_shop_needs_interpretation():
    r = ev({"waste_kind": "paint_solvent_mix", "physical_state": "liquid", "paint_mixed_source": "other", **GATES_NO})
    assert r["status"] == "NEED_EXPERT" and r["reason"] == "INTERPRETATION_NEEDED"


def test_designated_overrides_interpretation():
    r = ev({"waste_kind": "paint_solvent_mix", "physical_state": "liquid", "paint_mixed_source": "other",
            "oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": True})
    assert s3(r)["conclusion"] == "DESIGNATED"


# ---------------------------------------------------------------- 오니

def test_sludge_designated_only_with_all_conditions():
    base = {"waste_kind": "sludge_process", "physical_state": "semisolid", **GATES_NO,
            **{f: 0 for f in KB.facts if f.startswith("leach_")}, "oil_content_pct": 0}
    r = ev({**base, "sludge_facility_notified": True, "sludge_water_pct": 94.9, "leach_pb": 3})
    assert s3(r)["conclusion"] == "DESIGNATED"
    r = ev({**base, "sludge_facility_notified": True, "sludge_water_pct": 95, "leach_pb": 3})
    assert s3(r)["conclusion"] == "NOT_DESIGNATED"
    r = ev({**base, "sludge_facility_notified": False, "sludge_water_pct": 80, "leach_pb": 3})
    assert s3(r)["conclusion"] == "NOT_DESIGNATED"


def test_sludge_lists_needed_leach_tests():
    r = ev({"waste_kind": "sludge_wastewater", "physical_state": "semisolid", **GATES_NO,
            "sludge_facility_notified": True, "sludge_water_pct": 80})
    assert r["status"] == "NEED_TEST"
    tests = {c["fact"] for c in r["resolution"] if c.get("test")}
    assert {"leach_pb", "leach_hg", "leach_cr6", "oil_content_pct"} <= tests


# ---------------------------------------------------------------- PCB

@pytest.mark.parametrize("state,fact,val,designated", [
    ("liquid", "pcb_mg_l", 1.99, False), ("liquid", "pcb_mg_l", 2, True),
    ("solid", "pcb_leach_mg_l", 0.0029, False), ("solid", "pcb_leach_mg_l", 0.003, True),
])
def test_pcb_thresholds(state, fact, val, designated):
    r = ev({"waste_kind": "other", "physical_state": state, "oil_presence": "none",
            "toxic_chemical_discard": False, "pcb_possible": True, fact: val})
    assert (s3(r)["conclusion"] == "DESIGNATED") is designated


# ---------------------------------------------------------------- S2 ↔ S3 연결

def test_small_shop_waste_oil_is_business_waste_not_household():
    """배출시설 없고 하루 100kg인 작은 사업장이라도, 이 폐기물이 폐유(지정)면 사업장폐기물이다."""
    small = {**BIZ, "emission_facility": False, "work_type": "none", "daily_avg_kg": 100,
             "designated_waste_emitted": False, "waste_facility": False, "public_facility": "none",
             "waste_kind": "waste_oil", "physical_state": "liquid", **GATES_NO}
    r = evaluate(small, strict=False, kb=KB)
    s2 = next(d for d in r["decided"] if d["stage"] == "S2")
    assert s2["conclusion"] == "BUSINESS"
    assert s3(r)["conclusion"] == "DESIGNATED"


def test_small_shop_asks_s3_questions_before_calling_it_household():
    small = {**BIZ, "emission_facility": False, "work_type": "none", "daily_avg_kg": 100}
    r = evaluate(small, strict=False, kb=KB)
    assert r["stage"] == "S2"
    assert r["next_question"]["fact"] == "waste_kind"
    assert r["next_question"]["asked_for_stage"] == "S3"


def test_not_designated_carries_notice_gap_and_is_provisional_in_strict():
    r = ev({"waste_kind": "other", "physical_state": "solid", **GATES_NO,
            "general_group": "51-29", "code": "51-29-02"}, strict=True)
    assert r["status"] == "NEED_EXPERT" and r["provisional"]
    assert any("제12호" in g for g in s3(r)["gaps"])


def test_user_cannot_set_derived_fact():
    from wastecalc import InputError
    with pytest.raises(InputError):
        evaluate({"this_waste_designated": True}, kb=KB)


# ---------------------------------------------------------------- 무작위 전수(겹침·구멍)

S3_FACTS = sorted({c.fact for r in KB.rules_for("S3") for c in r.when})
NUM_SAMPLES = {}
for r in KB.rules_for("S3"):
    for c in r.when:
        if KB.facts[c.fact]["type"] == "number":
            v = c.value
            NUM_SAMPLES.setdefault(c.fact, set()).update({0, v, round(v * 0.999, 6), round(v * 1.001 + 0.001, 6)})


def _sample_value(rng, fid, allow_unknown):
    f = KB.facts[fid]
    if allow_unknown and rng.random() < 0.15:
        return UNKNOWN
    if f["type"] == "bool":
        return rng.choice([True, False])
    if f["type"] == "enum":
        return rng.choice(list(f["values"]))
    return rng.choice(sorted(NUM_SAMPLES[fid]))


@pytest.mark.parametrize("seed", range(5))
def test_s3_random_full_assignments_never_overlap_or_hole(seed):
    rng = random.Random(seed)
    for _ in range(3000):
        combo = {f: _sample_value(rng, f, allow_unknown=False) for f in S3_FACTS}
        st = eval_stage(KB, "S3", parse_answers(KB, combo))
        trues = [c for c, s in st["candidates"].items() if s == TRUE]
        assert len(trues) == 1, combo


@pytest.mark.parametrize("seed", range(3))
def test_s3_with_unknowns_never_overlap(seed):
    rng = random.Random(100 + seed)
    for _ in range(3000):
        combo = {f: _sample_value(rng, f, allow_unknown=True) for f in S3_FACTS}
        st = eval_stage(KB, "S3", parse_answers(KB, combo))
        assert sum(s == TRUE for s in st["candidates"].values()) <= 1, combo


def test_every_waste_kind_reachable_to_a_conclusion():
    for kind in KB.facts["waste_kind"]["values"]:
        rng = random.Random(kind)
        reached = set()
        for _ in range(400):
            combo = {f: _sample_value(rng, f, allow_unknown=False) for f in S3_FACTS}
            combo["waste_kind"] = kind
            st = eval_stage(KB, "S3", parse_answers(KB, combo))
            reached |= {c for c, s in st["candidates"].items() if s == TRUE}
        assert reached, kind
