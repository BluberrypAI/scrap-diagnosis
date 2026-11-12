"""확인대상 폐기물(시행규칙 제17조의2제1항): '기준 미만'도 분석결과서로만 받는다.

자세한 내용: docs/rule-changes/confirm-target-waste.md
"""

from __future__ import annotations

from app.agent.simulation import simulate
from app.domain.facts import Fact
from app.domain.facts import FactStatus as S
from app.rules.evaluator import TV, eval_cond
from app.rules.model import Cond, FactDef

AS_OF = "2026-11-08"
LEACH = ["leach_as", "leach_cd", "leach_cn", "leach_cr6", "leach_cu", "leach_hg", "leach_pb"]
BELOW = {k: 0 for k in LEACH} | {"oil_content_pct": 0}
CAT = {"n": FactDef(key="n", type="number", question_hint="n")}


def _f(value, status):
    return {"n": Fact(key="n", value=value, status=status)}


def test_falsify_min_status_keeps_claimed_below_threshold_unknown():
    c = Cond("n", "gte", 5, S.EVIDENCED, S.EVIDENCED)
    r = eval_cond(c, _f(1, S.CLAIMED), CAT)
    assert (r.status, r.reason) == (TV.UNKNOWN, "NEEDS_EVIDENCE")
    assert eval_cond(c, _f(1, S.EVIDENCED), CAT).status == TV.FALSE
    # 기본값(CLAIMED)이면 말로도 지운다(확인대상이 아닌 폐기물)
    assert eval_cond(Cond("n", "gte", 5, S.EVIDENCED), _f(1, S.CLAIMED), CAT).status == TV.FALSE


def _run(real_kb, material, answers=None, documents=None):
    sc = {
        "id": material,
        "as_of": AS_OF,
        "setup": {"facts": {"emission_facility": True, "material": material}},
        "answers": {"scope_screen": "none", "contamination_screen": "none", **(answers or {})},
    }
    if documents:
        sc["documents"] = {"TEST_REPORT": documents}
    return simulate(real_kb, sc)


def test_slag_claimed_below_is_not_confirmed_as_general(real_kb):
    # 이전: "모두 기준 미만"이라고 말만 해도 일반(51-04-02)으로 확정했다
    res = _run(real_kb, "steel_slag", answers={"physical_state": "solid", **BELOW})
    assert res.final_branch == "UNSUPPORTED"
    branches = [t.branch for t in res.turns]
    assert "REQUEST_EVIDENCE" in branches
    # 시험 수치는 말로 묻지 않는다
    asked = {t.question for t in res.turns if t.branch == "ASK_FACT"}
    assert not asked & set(BELOW)


def test_slag_with_report_below_is_general(real_kb):
    res = _run(real_kb, "steel_slag", answers={"physical_state": "solid"}, documents=BELOW)
    assert (res.final_branch, res.final_code) == ("FINAL_REVIEW", "51-04-02")


def test_not_confirm_target_needs_no_report(real_kb):
    # 깨끗한 PP는 확인대상이 아니다 → 서류 없이 일반 번호
    res = _run(real_kb, "pp", answers={"physical_state": "solid"})
    assert (res.final_branch, res.final_code) == ("FINAL_REVIEW", "51-03-01")
    assert all(t.branch != "REQUEST_EVIDENCE" for t in res.turns)


def test_build_marks_only_confirm_target_tables(real_kb):
    def strict_facts(table_id):
        from app.rules.model import iter_conds

        t = next(t for t in real_kb.tables if t.table_id == table_id)
        return {
            c.fact
            for r in t.rules
            for c in iter_conds(r.when)
            if c.falsify_min_status == S.EVIDENCED
        }

    assert set(LEACH) <= strict_facts("steel_slag")
    assert strict_facts("pp") == set()
    assert strict_facts("h2so4") == set()  # 폐산은 확인대상이 아니다(pH는 말로 '기준 미만' 가능)
    # PCB 수치는 확인대상 소재에서도 말로 받는다(fact_settings.yaml exclude_facts)
    assert not strict_facts("steel_slag") & {"pcb_mg_l", "pcb_leach_mg_l"}
