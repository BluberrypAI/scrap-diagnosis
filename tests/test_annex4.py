"""S4 분류번호: 별표 4 번호 표와 앞 단계 연결."""
import re

import fitz
import pytest

from wastecalc import InputError, evaluate, load_kb
from wastecalc.kb import ROOT

KB = load_kb(as_of="2026-11-05")  # 테스트 기준일 고정
BIZ = {"no_longer_needed": True, "direct_reinput": False, "circular_resource_recognized": False,
       "law_exclusion": "none", "emission_facility": True}
GATES_NO = {"oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": False}
ACID = {"waste_kind": "acid", "physical_state": "liquid", "ph": 1.0, **GATES_NO}


def ev(extra, strict=False):
    return evaluate({**BIZ, **extra}, strict=strict, kb=KB)


def s4(r):
    return next((d for d in r["decided"] if d["stage"] == "S4"), None)


# ---------------------------------------------------------------- 번호 표 자체

def test_annex4_has_313_unique_codes():
    ids = [c["id"] for c in KB.annex4["codes"]]
    assert len(ids) == 313 == len(set(ids))


def test_every_code_line_matches_source_text():
    text = re.sub(r"\s+", "", "".join(p.get_text() for p in fitz.open(ROOT / "sources/raw/170401309.pdf")))
    for c in KB.annex4["codes"]:
        assert re.sub(r"\s+", "", f"{c['id']}{c['name']}") in text, c["id"]


def test_every_mapping_prefix_has_codes():
    ids = [c["id"] for c in KB.annex4["codes"]]
    for key, prefixes in KB.s4_map["designated"].items():
        for p in prefixes:
            assert any(i.startswith(p) for i in ids), (key, p)
    for kind, prefixes in KB.s4_map["general_by_kind"].items():
        assert kind in KB.facts["waste_kind"]["values"], kind
        for p in prefixes:
            assert any(i.startswith(p) for i in ids), (kind, p)


def test_every_designated_s3_rule_maps_to_a_group():
    keys = KB.s4_map["designated"]
    for r in KB.rules_for("S3"):
        if r.concludes == "DESIGNATED":
            assert any(r.id.startswith(k) for k in keys), r.id


# ---------------------------------------------------------------- 흐름

def test_liquid_acid_narrows_to_02_01_only():
    r = ev(ACID)
    assert r["stage"] == "S4"
    assert set(r["resolution"][0]["allowed_values"]) == {
        "02-01-01", "02-01-02", "02-01-03", "02-01-04", "02-01-05", "02-01-99"}


def test_choose_specific_acid_code():
    r = ev({**ACID, "code": "02-01-01"})
    assert r["status"] == "DETERMINED" and s4(r)["conclusion"] == "02-01-01"
    assert s4(r)["user_selected"] is True


def test_catch_all_code_needs_confirmation():
    base = {**ACID, "code": "02-01-99"}
    r = ev(base)
    assert r["status"] == "NEED_INFO" and r["next_question"]["fact"] == "no_specific_code_applies"
    assert s4(ev({**base, "no_specific_code_applies": True}))["conclusion"] == "02-01-99"
    r = ev({**base, "no_specific_code_applies": False})
    assert r["status"] == "NEED_INFO" and "02-01-99" not in r["resolution"][0]["allowed_values"]


def test_code_contradicting_earlier_stage_needs_expert():
    r = ev({**ACID, "code": "51-29-01"})
    assert r["status"] == "NEED_EXPERT" and r["reason"] == "CODE_MISMATCH"


def test_solid_naoh_offers_only_solid_alkali_codes():
    r = ev({"waste_kind": "alkali", "physical_state": "solid", "alkali_solid_naoh_koh": True, **GATES_NO})
    assert set(r["resolution"][0]["allowed_values"]) == {"02-02-03", "02-02-04"}


def test_single_code_range_is_decided_without_asking():
    r = ev({"waste_kind": "dust", "physical_state": "solid", "dust_from_apc": True,
            "dust_from_incinerator": False, **GATES_NO, "leach_pb": 5})
    assert s4(r)["conclusion"] == "03-02-00" and s4(r)["user_selected"] is False


def test_pcb_oil_goes_to_08_not_06():
    r = ev({"waste_kind": "waste_oil", "physical_state": "liquid", "oil_presence": "present",
            "pcb_possible": True, "pcb_mg_l": 10, "toxic_chemical_discard": False})
    assert all(k.startswith("08") for k in r["resolution"][0]["allowed_values"])


def test_general_scrap_asks_group_then_code():
    r = ev({"waste_kind": "other", "physical_state": "solid", **GATES_NO})
    assert r["next_question"]["fact"] == "general_group"
    assert "51-29" in r["resolution"][0]["allowed_values"]
    r = ev({"waste_kind": "other", "physical_state": "solid", **GATES_NO, "general_group": "51-29"})
    assert set(r["resolution"][0]["allowed_values"]) == {"51-29-01", "51-29-02", "51-29-03", "51-29-04", "51-29-99"}


def test_solid_plastic_goes_straight_to_51_03_with_2023_hints():
    r = ev({"waste_kind": "synthetic_resin", "physical_state": "solid", **GATES_NO})
    card = r["resolution"][0]
    assert {"51-03-01", "51-03-07"} <= set(card["allowed_values"])
    assert "51-03-07" in card["guide_hints_2023"]


def test_standalone_general_code_auto():
    r = ev({"waste_kind": "edible_oil", "physical_state": "liquid", "oil_presence": "present",
            "oil_content_pct": 90, "pcb_possible": False, "toxic_chemical_discard": False})
    assert s4(r)["conclusion"] == "51-16-00"


def test_designated_code_not_accepted_for_general_waste():
    r = ev({"waste_kind": "synthetic_resin", "physical_state": "solid", **GATES_NO, "code": "01-01-02"})
    assert r["reason"] == "CODE_MISMATCH"


def test_damaged_battery_needs_interpretation():
    r = ev({"waste_kind": "battery", "physical_state": "solid", "battery_damaged": True, **GATES_NO})
    assert r["status"] == "NEED_EXPERT" and r["reason"] == "INTERPRETATION_NEEDED"


def test_undamaged_battery_goes_to_51_41():
    r = ev({"waste_kind": "battery", "physical_state": "solid", "battery_damaged": False, **GATES_NO})
    assert all(k.startswith("51-41") for k in r["resolution"][0]["allowed_values"])


@pytest.mark.parametrize("bad", ["51-29", "99-99-99", "30-00-00"])
def test_code_input_validated(bad):
    with pytest.raises(InputError):
        ev({"code": bad})
