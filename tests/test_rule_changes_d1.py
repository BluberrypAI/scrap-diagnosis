"""규칙 변경 D1: 비폐기물·적용 제외 과판정 막기.

자세한 내용: docs/rule-changes/d1-not-waste-and-exclusions.md
"""

from __future__ import annotations

from datetime import date

from app.agent.router import Branch, SessionState, run_engine
from app.domain.facts import FactStatus, FactStore
from app.rules.answers import fact_answer

AS_OF = date(2026, 11, 9)
BASE = {"emission_facility": True, "material": "pp", "physical_state": "solid"}


def _run(kb, evidenced: tuple[str, ...] = (), **kv):
    store = FactStore()
    for k, v in {**BASE, **kv}.items():
        status = FactStatus.EVIDENCED if k in evidenced else FactStatus.CLAIMED
        store.append(fact_answer(kb, k, v, status=status))
    return run_engine(kb, store, SessionState(), AS_OF)


def test_still_used_is_interpretation_not_auto_not_waste(real_kb):
    step = _run(real_kb, material_fate="still_used", circular_resource_recognized=False)
    assert step.evaluation.decided.outcome == "INTERPRETATION_NEEDED"


def test_circular_resource_needs_certificate_document(real_kb):
    said = _run(real_kb, circular_resource_recognized=True)  # 말로만 "인정서 있음"
    decided = said.evaluation.decided
    assert decided is None or decided.outcome != "CIRCULAR_RESOURCE"
    assert any(
        u.key == "circular_resource_recognized" and u.reason == "NEEDS_EVIDENCE"
        for u in said.evaluation.blocking_facts
    )
    doc = _run(
        real_kb, evidenced=("circular_resource_recognized",), circular_resource_recognized=True
    )
    assert doc.evaluation.decided.outcome == "CIRCULAR_RESOURCE"


def test_fisheries_exclusion_only_for_recycling_chain(real_kb):
    common = {
        "material_fate": "released",
        "circular_resource_recognized": False,
        "law_exclusion": "fisheries_byproduct_unmixed",
    }
    yes = _run(real_kb, fisheries_activity="recycle_chain", **common)
    assert yes.evaluation.decided.outcome == "EXCLUDED"
    other = _run(real_kb, fisheries_activity="other", **common)
    assert other.evaluation.decided is None or other.evaluation.decided.outcome != "EXCLUDED"
    asked = _run(real_kb, **common)  # 처리 방식을 아직 모름 → 확정을 막는 사실(물을 것)
    assert asked.decision.branch == Branch.ASK_FACT
    assert any(u.key == "fisheries_activity" for u in asked.evaluation.blocking_facts)


def test_disease_exclusion_only_for_legal_measures(real_kb):
    common = {"material_fate": "released", "circular_resource_recognized": False}
    for kind in ("livestock_disease", "aquatic_disease"):
        yes = _run(real_kb, law_exclusion=kind, disease_measure_applies=True, **common)
        assert yes.evaluation.decided.outcome == "EXCLUDED", kind
        no = _run(real_kb, law_exclusion=kind, disease_measure_applies=False, **common)
        assert no.evaluation.decided is None or no.evaluation.decided.outcome != "EXCLUDED"


def test_emission_facility_asks_about_installation_and_operation(real_kb):
    fd = real_kb.catalog["emission_facility"]
    assert fd.label == "배출시설 설치·운영" and "설치해 운영" in fd.question_hint
