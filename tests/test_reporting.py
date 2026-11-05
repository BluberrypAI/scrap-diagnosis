import pytest

from wastecalc import evaluate, load_kb
from wastecalc.engine import parse_answers

KB = load_kb(as_of="2026-11-05")
BASE = {"material_fate": "released", "circular_resource_recognized": False,
        "law_exclusion": "none", "emission_facility": True}
GEN = {**BASE, "waste_kind": "synthetic_resin", "physical_state": "solid", "code": "51-03-01",
       "designated_residue": False, "oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": False}
OIL = {**BASE, "waste_kind": "waste_oil", "code": "06-01-01", "pcb_possible": False,
       "toxic_chemical_discard": False}
CONTEXT = {"reporting_shared": "none", "reporting_intermediate": "none"}


def run(a, strict=False):
    return evaluate(a, kb=KB, strict=strict, include_reporting=True)


@pytest.mark.parametrize("qty,want", [(99.99, "NOT_REQUIRED"), (100, "REQUIRED")])
def test_general_notice_facility_boundary_uses_excluded_adjusted_quantity(qty, want):
    r = run({**GEN, **CONTEXT, "work_type": "none", "reporting_general_daily_kg": qty})
    assert r["reporting"]["general_notice"]["conclusion"] == want
    assert r["reporting"]["designated_plan"]["conclusion"] == "NOT_APPLICABLE"
    assert r["assessment_complete"]


@pytest.mark.parametrize("qty,want", [(299.99, "NOT_REQUIRED"), (300, "REQUIRED")])
def test_general_notice_without_facilities_has_its_own_boundary(qty, want):
    r = run({**GEN, **CONTEXT, "emission_facility": False, "public_facility": "none", "waste_facility": False,
             "daily_avg_kg": 400, "work_type": "none", "reporting_general_daily_kg": qty})
    assert r["reporting"]["general_notice"]["conclusion"] == want


def test_business_status_does_not_substitute_for_notice_quantity():
    r = run({**GEN, **CONTEXT, "work_type": "none"})
    assert r["next_question"]["fact"] == "reporting_general_daily_kg"
    assert not r["assessment_complete"]


def test_work_total_is_separate_from_all_waste_total():
    r = run({**GEN, **CONTEXT, "work_type": "series", "work_total_ton": 50,
             "reporting_general_daily_kg": 0, "reporting_work_total_ton": 4.99})
    assert r["reporting"]["general_notice"]["conclusion"] == "NOT_REQUIRED"
    r = run({**GEN, **CONTEXT, "work_type": "series", "reporting_general_daily_kg": 0,
             "reporting_work_total_ton": 5})
    assert r["reporting"]["general_notice"]["conclusion"] == "REQUIRED"


@pytest.mark.parametrize("qty,want", [(49.99, "NOT_REQUIRED"), (50, "REQUIRED")])
def test_single_kind_oil_plan_boundary(qty, want):
    r = run({**OIL, **CONTEXT, "reporting_designated_inventory": "single", "reporting_current_monthly_kg": qty})
    assert r["reporting"]["designated_plan"]["conclusion"] == want


def test_low_current_quantity_does_not_imply_other_site_wastes_are_zero():
    r = run({**OIL, **CONTEXT, "reporting_current_monthly_kg": 1})
    assert r["reporting"]["designated_plan"]["status"] == "NEED_INFO"
    assert r["next_question"]["fact"] == "reporting_designated_inventory"


def test_positive_current_quantity_can_prove_requirement_without_other_inventory():
    r = run({**OIL, **CONTEXT, "reporting_current_monthly_kg": 50})
    assert r["reporting"]["designated_plan"]["conclusion"] == "REQUIRED"


def test_unknown_quantity_has_help_and_no_identical_question_loop():
    r = run({**OIL, **CONTEXT, "reporting_current_monthly_kg": "UNKNOWN",
             "reporting_designated_inventory": "single"})
    assert not r.get("next_question")
    assert r["reporting"]["designated_plan"]["status"] == "NEED_INFO"
    assert any(c["fact"] == "reporting_current_monthly_kg" for c in r["resolution"])


def test_other_intermediate_waste_is_explicit_exception():
    r = run({**OIL, **CONTEXT, "reporting_intermediate": "other_intermediate"})
    assert r["reporting"]["designated_plan"]["conclusion"] == "NOT_REQUIRED"


def test_collective_cases_are_not_guessed_from_factory_classification():
    r = run({**GEN, **CONTEXT, "reporting_shared": "member"})
    assert r["reporting"]["general_notice"]["status"] == "NEED_EXPERT"


def test_reporting_conflict_does_not_become_required_by_using_one_number():
    r = run({**GEN, **CONTEXT, "work_type": "none", "reporting_general_daily_kg": {"conflict": [0, 500]}})
    assert r["reporting"]["general_notice"]["status"] == "NEED_EXPERT"


def test_reporting_is_separately_provisional_until_rules_are_reviewed():
    r = run({**GEN, **CONTEXT, "work_type": "none", "reporting_general_daily_kg": 100}, strict=True)
    assert r["reporting"]["general_notice"]["provisional"]
    assert next(c for c in r["checks"] if c["key"] == "general_notice")["status"] == "PROVISIONAL"


def plan_for_code(code, extra, kb=KB):
    from wastecalc.reporting import assess_reporting
    # 분류기의 결과를 소비하는 별도 행정의무 계산 경계 검사.
    core = {"decided": [{"stage": "S3", "conclusion": "DESIGNATED"}, {"stage": "S4", "conclusion": code}]}
    return assess_reporting(kb, parse_answers(kb, {**CONTEXT, **extra}), core, False)["designated_plan"]


@pytest.mark.parametrize("code,boundary", [("01-02-01", 500), ("02-01-02", 100), ("07-01-00", 20)])
def test_other_single_kind_boundaries(code, boundary):
    for qty, want in [(boundary - .01, "NOT_REQUIRED"), (boundary, "REQUIRED")]:
        result = plan_for_code(code, {"reporting_designated_inventory": "single", "reporting_current_monthly_kg": qty})
        assert result["conclusion"] == want


MULTI = {"reporting_designated_inventory": "multiple", "reporting_current_monthly_kg": 1,
         "reporting_unconditional_designated": False, "reporting_other_designated_notice": False,
         "reporting_sludge_monthly_kg": 0, "reporting_group50_max_kg": 49,
         "reporting_group50_sum_kg": 129.99, "reporting_group100_max_kg": 0,
         "reporting_group100_sum_kg": 0, "reporting_asbestos_monthly_kg": 0}


@pytest.mark.parametrize("qty,want", [(129.99, "NOT_REQUIRED"), (130, "REQUIRED")])
def test_multiple_kinds_50_group_combined_boundary(qty, want):
    result = plan_for_code("06-01-01", {**MULTI, "reporting_group50_sum_kg": qty})
    assert result["conclusion"] == want


def test_multiple_kinds_other_group_can_trigger_plan():
    result = plan_for_code("06-01-01", {**MULTI, "reporting_group100_max_kg": 100, "reporting_group100_sum_kg": 100})
    assert result["conclusion"] == "REQUIRED"


def test_inconsistent_group_quantities_require_checking():
    result = plan_for_code("06-01-01", {**MULTI, "reporting_group50_max_kg": 60, "reporting_group50_sum_kg": 20})
    assert result["status"] == "NEED_EXPERT"


@pytest.mark.parametrize("code,word", [("08-01-00", "폴리클로리네이티드비페닐"), ("10-11-00", "의료폐기물"), ("11-02-00", "수은폐기물")])
def test_unconditional_categories_cite_the_corresponding_clause(code, word):
    result = plan_for_code(code, {})
    assert result["conclusion"] == "REQUIRED"
    assert word in result["basis"][0]["quote"]


def test_reporting_never_uses_current_rule_for_an_unsupported_date():
    result = plan_for_code("06-01-01", {"reporting_current_monthly_kg": 100}, KB.at("2020-01-01"))
    assert result["status"] == "OUT_OF_SCOPE"


def test_new_reporting_citations_are_present_in_owning_source():
    import re
    import fitz
    from wastecalc.kb import ROOT

    src = KB.sources[KB.reporting["source"]]
    text = re.sub(r"\s+", "", "".join(p.get_text() for p in fitz.open(ROOT / src["path"])))
    def quotes(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "quote":
                    yield item
                else:
                    yield from quotes(item)
        elif isinstance(value, list):
            for item in value:
                yield from quotes(item)
    for quote in quotes(KB.reporting):
        assert re.sub(r"\s+", "", quote) in text, quote
