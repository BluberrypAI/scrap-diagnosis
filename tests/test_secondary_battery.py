"""폐이차전지 종류: 납축·알칼리·스크랩은 일반 번호로 가지 않는다(docs/rule-changes/d6)."""

from __future__ import annotations

from datetime import date

import pytest

from app.agent.orchestrator import DiagnosisSession, QuickReply

AS_OF = date(2026, 11, 11)


def _run(kb, material: str, answers: dict) -> tuple[list[str], object]:
    s = DiagnosisSession(kb, case_id="b", as_of=AS_OF)
    s.seed({"emission_facility": True, "material_group": "product", "material": material})
    r = s.handle()
    asked = []
    for _ in range(10):
        if r.branch != "ASK_FACT":
            break
        q = r.ui.question
        asked.append(q["key"])
        if q["input"] == "group":
            r = s.handle(quick_reply=QuickReply(key=q["key"], kind="none_all"))
        else:
            r = s.handle(quick_reply=QuickReply(key=q["key"], value=answers[q["key"]]))
    return asked, r


@pytest.mark.parametrize(
    ("material", "answers", "basis_code"),
    [
        ("battery_lead_acid", {}, "03-10-01"),
        ("battery_alkaline", {}, "03-10-02"),
        ("battery_scrap", {}, "03-10-04"),
        ("battery_secondary_other", {"battery_type": "lead_acid"}, "03-10-01"),
        ("battery_ev", {"battery_type": "alkaline"}, "03-10-02"),
    ],
)
def test_lead_acid_alkaline_and_scrap_need_interpretation(real_kb, material, answers, basis_code):
    _, r = _run(real_kb, material, answers)
    assert r.branch == "FINAL_REVIEW"
    assert r.verdict.waste_code is None and r.verdict.outcome == "INTERPRETATION_NEEDED"
    assert any(basis_code in (x.excerpt or "") for x in r.verdict.rationale)


def test_lithium_without_damage_keeps_general_code(real_kb):
    asked, r = _run(
        real_kb,
        "battery_secondary_other",
        {"battery_type": "lithium", "battery_damaged": False},
    )
    assert "battery_type" in asked and "battery_damaged" in asked
    assert r.verdict.waste_code == "51-41-99"


def test_primary_battery_is_not_asked_type_or_damage(real_kb):
    asked, r = _run(real_kb, "battery_primary", {})
    assert "battery_type" not in asked and "battery_damaged" not in asked
    assert r.verdict.waste_code == "51-41-01"
