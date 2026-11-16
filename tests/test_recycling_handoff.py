from copy import deepcopy

import pytest

from app.domain.recycling import assess_recycling


def handoff(code="51-03-01"):
    return {
        "case_id": "owned-case",
        "verdict_version": 1,
        "waste_code": code,
        "category": "GENERAL",
        "result_type": "WASTE_CODE",
        "route_guidance": {"action": "RECOMMEND_ROUTE"},
        "timestamps": {"as_of": "2026-11-16"},
    }


@pytest.mark.parametrize(
    "code",
    [f"51-03-{i:02d}" for i in range(1, 9)]
    + ["51-03-99"]
    + [f"51-29-{i:02d}" for i in range(1, 5)]
    + ["51-29-99"],
)
def test_all_scoped_rows_preserve_source_and_conditions(real_kb, code):
    h = handoff(code)
    original = deepcopy(h)
    r = assess_recycling(real_kb.recycling, h)
    assert r.status == "table_listed"
    assert r.source["sha256"] and r.pages
    assert r.facility_permit_verified is False
    assert "R-10" in r.types.free
    assert h == original


def test_r10_is_not_deduplicated_across_analysis_groups(real_kb):
    r = assess_recycling(real_kb.recycling, handoff())
    assert "R-10" in r.types.free and "R-10" in r.types.analysis
    assert "R-3-5" not in r.types.analysis
    packaging = assess_recycling(real_kb.recycling, handoff("51-03-07"))
    assert "R-3-5" in packaging.types.analysis


def test_no_table_or_old_law_date_never_invents_types(real_kb):
    h = handoff()
    assert assess_recycling({}, h).status == "not_covered"
    h["timestamps"]["as_of"] = "2026-11-11"
    r = assess_recycling(real_kb.recycling, h)
    assert r.status == "out_of_date" and not r.types.free
    assert assess_recycling(real_kb.recycling, handoff("99-99-99")).status == "not_covered"


@pytest.mark.parametrize(
    "patch",
    [
        {"category": "DESIGNATED"},
        {"result_type": "NO_CODE"},
        {"route_guidance": {"action": "NEEDS_TEST"}},
    ],
)
def test_general_table_cannot_bypass_hazard_or_unresolved_classification(real_kb, patch):
    r = assess_recycling(real_kb.recycling, handoff() | patch)
    assert r.status == "not_applicable" and not r.types.free
