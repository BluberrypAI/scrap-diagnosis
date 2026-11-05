"""사용자가 실제로 막히거나 잘못된 구체적 결과를 받던 문진 경로."""
import pytest

from wastecalc import evaluate, load_kb
from wastecalc.compact import compact

KB = load_kb(as_of="2026-11-05")
BASE = {"material": "unlisted", "material_fate": "released", "circular_resource_recognized": False,
        "law_exclusion": "none", "emission_facility": True}
CLEAN = {"designated_residue": False, "oil_presence": "none", "pcb_possible": False,
         "toxic_chemical_discard": False}
RESIN = {**BASE, **CLEAN, "waste_kind": "synthetic_resin", "physical_state": "solid"}


def ev(extra):
    return evaluate({**BASE, **extra}, strict=False, kb=KB)


def test_oil_must_screen_pcb_before_offering_specific_codes():
    r = ev({"waste_kind": "waste_oil", "toxic_chemical_discard": False})
    assert next(d for d in r["decided"] if d["stage"] == "S3")["conclusion"] == "DESIGNATED"
    assert r["next_question"]["fact"] == "pcb_possible"
    assert not any(d["stage"] in {"S4", "S5"} for d in r["decided"])


def test_oil_unknown_pcb_does_not_present_recycling_permission():
    r = ev({"waste_kind": "waste_oil", "pcb_possible": "UNKNOWN", "toxic_chemical_discard": False,
            "code": "06-01-01"})
    assert not r.get("next_question")
    assert not any(d["stage"] in {"S4", "S5"} for d in r["decided"])
    c = compact(r, KB, {**BASE, "waste_kind": "waste_oil", "pcb_possible": "UNKNOWN", "toxic_chemical_discard": False})
    assert any(h["fact"] == "pcb_possible" and h["how_to_check"] for h in c["how_to_resolve"])


def test_pcb_oil_must_still_prohibit_recycling():
    r = ev({"waste_kind": "waste_oil", "physical_state": "liquid", "pcb_possible": True,
            "pcb_mg_l": 3, "toxic_chemical_discard": False, "code": "08-01-00"})
    assert r["decided"][-1]["conclusion"] == "PROHIBITED"


@pytest.mark.parametrize("extra,fact", [
    ({"code": "UNKNOWN"}, "code"),
    ({"general_group": "UNKNOWN", "waste_kind": "other"}, "general_group"),
    ({"code": "51-03-99", "no_specific_code_applies": "UNKNOWN"}, "no_specific_code_applies"),
])
def test_unknown_classification_stops_with_a_way_to_resolve(extra, fact):
    a = {**RESIN, **extra}
    r = evaluate(a, strict=False, kb=KB)
    assert not r.get("next_question")
    assert r["status"] == "NEED_INFO"
    c = compact(r, KB, a)
    assert any(h["fact"] == fact and h["how_to_check"] for h in c["how_to_resolve"])


def test_nested_s3_question_has_explanation_and_checking_help():
    a = {**BASE, "emission_facility": False, "work_type": "none", "daily_avg_kg": 100}
    c = compact(evaluate(a, strict=False, kb=KB), KB, a)
    q = c["next_question"]
    assert q["asked_for_stage"] == "S3"
    assert q["why"] and q["purpose"]
    assert q["how_to_check"]


def test_question_carries_document_check_help():
    a = {"material": "unlisted", "material_fate": "released"}
    q = compact(evaluate(a, strict=False, kb=KB), KB, a)["next_question"]
    assert q["fact"] == "circular_resource_recognized"
    assert any("인정서" in h for h in q["how_to_check"])


def test_rubber_does_not_require_choosing_unrelated_resin_codes():
    r = ev({**CLEAN, "waste_kind": "synthetic_rubber", "physical_state": "solid"})
    assert next(d for d in r["decided"] if d["stage"] == "S4")["conclusion"] == "51-03-02"


def test_rubber_cannot_be_assigned_a_resin_code_even_on_initial_input():
    r = ev({**CLEAN, "waste_kind": "synthetic_rubber", "physical_state": "solid", "code": "51-03-01"})
    assert r["reason"] == "CODE_MISMATCH"


def test_rejecting_catchall_reopens_specific_code_selection():
    a = {**RESIN, "code": "51-03-99", "no_specific_code_applies": False}
    r = evaluate(a, strict=False, kb=KB)
    assert r["next_question"]["fact"] == "code"
    assert "51-03-99" not in r["next_question"]["allowed_values"]


def test_conflicting_codes_are_not_overridden_by_single_code_mapping():
    r = ev({**CLEAN, "waste_kind": "synthetic_rubber", "physical_state": "solid",
            "code": {"conflict": ["51-03-02", "51-03-01"]}})
    assert r["status"] == "NEED_EXPERT" and r["reason"] == "FACT_CONFLICT"
    assert not any(d["stage"] in {"S4", "S5"} for d in r["decided"])
