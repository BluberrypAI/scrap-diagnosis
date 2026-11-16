import math

from app.domain.facts import FactStore
from app.domain.ranges import NumRange
from app.rules.evaluator import evaluate
from app.rules.loader import build_kb
from app.rules.selector import SelectionContext, numeric_segments, select_question, value_domain
from tests.conftest import AS_OF, CLEAN, F, facts


def pick(kb, fs, ctx=None):
    ev = evaluate(kb, fs, AS_OF)
    return select_question(kb, fs, ev, AS_OF, ctx)


def test_numeric_segments_from_thresholds(kb):
    segs = numeric_segments(kb, "oil_content_pct")
    assert [s.label("%") for s in segs] == ["5% 미만", "5% 이상"]


def test_numeric_segments_mixed_ops():
    kb = build_kb(
        [{"key": "n", "type": "number", "unit": "mg/L", "question_hint": "n"}],
        [
            {
                "table_id": "t",
                "version": "1",
                "hit_policy": "PRIORITY",
                "rules": [
                    {
                        "rule_id": "A",
                        "priority": 3,
                        "when": {"fact": "n", "op": "gt", "value": 2},
                        "then": {"code": "A"},
                    },
                    {
                        "rule_id": "B",
                        "priority": 2,
                        "when": {"fact": "n", "op": "gte", "value": 10},
                        "then": {"code": "B"},
                    },
                    {
                        "rule_id": "C",
                        "priority": 1,
                        "when": {"fact": "n", "op": "lte", "value": 2},
                        "then": {"code": "C"},
                    },
                ],
            }
        ],
    )
    labels = [s.label("mg/L") for s in numeric_segments(kb, "n")]
    assert labels == ["2mg/L 이하", "2mg/L 초과 10mg/L 미만", "10mg/L 이상"]


def test_value_domain_uses_priors(kb):
    dom = value_domain(kb, kb.catalog["pcb_related"])
    probs = {o.label: p for o, p in dom}
    assert math.isclose(probs["예"], 0.03) and math.isclose(probs["아니오"], 0.97)


def test_first_question_is_table_selector(kb):
    q = pick(kb, {})
    assert q.unit == "fact" and q.key == "material"


def test_group_question_beats_individual_contamination_questions(kb):
    q = pick(kb, facts(material="PP"))
    assert q.unit == "group" and q.key == "contamination_screen"
    assert set(q.facts) == {"pcb_related", "hazardous_residue", "toxic_chemical"}
    assert [o.kind for o in q.value_options] == ["none_all", "expand"]
    keys = [e.key for e in q.score_breakdown]
    assert {"pcb_related", "oil_content_pct", "form"} <= set(keys)


def test_expanded_group_is_not_offered_again(kb):
    q = pick(
        kb,
        facts(material="PP"),
        SelectionContext(expanded_groups=frozenset({"contamination_screen"})),
    )
    assert q.unit == "fact"
    assert all(e.unit == "fact" for e in q.score_breakdown)


def test_group_needs_two_open_members(kb):
    q = pick(kb, facts(material="PP", form="FILM", pcb_related=False, hazardous_residue=False))
    assert all(e.unit == "fact" for e in q.score_breakdown)


def test_only_blocking_facts_are_asked(kb):
    # 오염 사실만 확정을 막고 있으면 form 등 다른 사실은 묻지 않는다.
    fs = facts(material="PP", form="FILM", oil_content_pct=(3, "EVIDENCED"))
    q = pick(kb, fs)
    assert {e.key for e in q.score_breakdown} <= {
        "contamination_screen",
        "pcb_related",
        "hazardous_residue",
        "toxic_chemical",
    }


def test_numeric_question_options_and_unknown(kb):
    q = pick(kb, facts(material="PP", form="FILM", **CLEAN))
    assert q.key == "oil_content_pct"
    assert [o.label for o in q.value_options] == ["5% 미만", "5% 이상", "모름"]
    assert q.value_options[0].value == NumRange(lo=None, hi=5, hi_inc=False).model_dump()


def _rule(rid, prio, when, code):
    return {"rule_id": rid, "priority": prio, "when": when, "then": {"code": code}}


def _eq(k, v=True):
    return {"fact": k, "op": "eq", "value": v}


def _kb(rules, keys):
    return build_kb(
        [{"key": k, "type": "bool", "question_hint": k} for k in keys],
        [{"table_id": "t", "version": "1", "hit_policy": "PRIORITY", "rules": rules}],
    )


def test_zero_gain_question_is_not_chosen_while_others_help():
    # w는 어떤 값이든 Y 후보를 남기므로 후보 수를 바꾸지 못한다(gain 0).
    kb = _kb(
        [
            _rule("R1", 10, _eq("a"), "X"),
            _rule("R2", 5, {"all": [_eq("b"), _eq("w", True)]}, "Y"),
            _rule("R3", 5, {"all": [_eq("b"), _eq("w", False)]}, "Y"),
            _rule("R4", 1, _eq("e"), "Z"),
        ],
        ("a", "b", "w", "e"),
    )
    q = pick(kb, {})
    w = next(e for e in q.score_breakdown if e.key == "w")
    assert w.gain == 0 and not q.fallback
    assert q.key != "w"


def test_fallback_when_all_gains_zero():
    # 후보가 X 하나뿐이지만 아직 어떤 규칙도 TRUE가 아니다 → 해소 정도로 고른다.
    kb = _kb([_rule("R1", 10, _eq("c"), "X"), _rule("R2", 1, _eq("d"), "X")], ("c", "d"))
    q = pick(kb, {})
    assert q.fallback and q.key == "c"
    assert all(e.gain == 0 for e in q.score_breakdown)


def test_focus_code_weight(kb):
    fs = facts(material="PP", form="FILM", **CLEAN)
    base = pick(kb, fs)
    focused = pick(kb, fs, SelectionContext(focus_codes=frozenset({"SAMPLE-A"})))
    assert focused.key == "oil_content_pct"
    b = next(e for e in base.score_breakdown if e.key == "oil_content_pct")
    f = next(e for e in focused.score_breakdown if e.key == "oil_content_pct")
    assert f.score > b.score


def test_selection_is_deterministic_and_order_independent(kb):
    hist = [F("material", "PP", t=1), F("form", "FILM", t=2), F("pcb_related", False, t=3)]
    a = pick(kb, FactStore(hist).effective())
    b = pick(kb, FactStore(list(reversed(hist))).effective())
    assert a.model_dump() == b.model_dump()
    assert a.model_dump() == pick(kb, FactStore(hist).effective()).model_dump()
