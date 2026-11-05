import copy

from wastecalc import evaluate, load_kb
from wastecalc.engine import parse_answers
from wastecalc.kb import Condition, Rule

KB = load_kb(as_of="2026-11-05")
BASE = {"material_fate": "released", "circular_resource_recognized": False,
        "law_exclusion": "none", "emission_facility": True}


def test_partial_designation_does_not_mark_code_or_reporting_complete():
    r = evaluate({**BASE, "waste_kind": "waste_oil", "toxic_chemical_discard": False}, kb=KB)
    checks = {c["key"]: c for c in r["checks"]}
    assert checks["designation"]["status"] == "PROVISIONAL"
    assert checks["code"]["status"] in {"NEED_INFO", "NEED_TEST"}
    assert checks["general_notice"]["status"] == "NOT_REQUESTED"
    assert not r["assessment_complete"]


def test_kind_is_marked_as_user_confirmed_fact_not_component_analysis():
    r = evaluate({**BASE, "waste_kind": "other"}, kb=KB)
    c = next(c for c in r["checks"] if c["key"] == "kind")
    assert c["source"] == "USER" and c["status"] == "FACT_CONFIRMED"


def test_question_selection_prefers_a_more_balanced_legal_partition():
    from wastecalc.questioning import order_questions
    from wastecalc.engine import _resolution, eval_stage

    kb = copy.copy(KB)
    kb.facts = copy.deepcopy(KB.facts)
    for f in ("oil_presence", "pcb_possible", "emission_facility"):
        kb.facts[f]["cost"] = "USER"  # 동일 응답 비용일 때의 분기 구분력을 검사
    kb.stages = copy.deepcopy(KB.stages)
    kb.stages["S3"] = {"title": "선택 검사", "question_order": ["oil_presence", "emission_facility", "pcb_possible"],
                       "candidates": {x: {"label": x} for x in "ABCD"}}
    raw = [("A", [("oil_presence", "none"), ("pcb_possible", True)]),
           ("B", [("oil_presence", "present"), ("pcb_possible", True)]),
           ("C", [("pcb_possible", False), ("emission_facility", True)]),
           ("D", [("pcb_possible", False), ("emission_facility", False)])]
    kb.rules = [Rule(id="toy-" + k, stage="S3", concludes=k,
                     when=[Condition(f, "eq", v) for f, v in conditions], source="DEC-A1",
                     location="test", quote="test", review="UNVERIFIED") for k, conditions in raw]
    answers = parse_answers(kb, {"waste_kind": "other"})
    st = eval_stage(kb, "S3", answers)
    cards = _resolution(kb, "S3", st, answers)
    ranked = order_questions(kb, "S3", cards, answers)
    assert ranked[0]["fact"] == "pcb_possible"
    assert set(c["fact"] for c in ranked) == {"oil_presence", "pcb_possible"}


def test_question_selector_never_reasks_unknown():
    from wastecalc.questioning import order_questions
    from wastecalc.engine import _resolution, eval_stage

    answers = parse_answers(KB, {"waste_kind": "other", "designated_residue": "UNKNOWN"})
    cards = _resolution(KB, "S3", eval_stage(KB, "S3", answers), answers)
    ranked = order_questions(KB, "S3", cards, answers)
    assert ranked[0]["state"] == "MISSING"
