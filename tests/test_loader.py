from datetime import date

import pytest

from app.rules.loader import RuleDataError, build_kb

CAT = [
    {"key": "n", "type": "number", "question_hint": "n"},
    {"key": "e", "type": "enum", "values": ["A", "B", "C"], "question_hint": "e"},
    {"key": "b", "type": "bool", "question_hint": "b", "none_value": False},
    {"key": "b2", "type": "bool", "question_hint": "b2", "none_value": False},
]


def table(rules, hit="PRIORITY", **kw):
    return {"table_id": "t", "version": "1", "hit_policy": hit, "rules": rules, **kw}


def rule(rid, when, code="X", prio=1):
    return {"rule_id": rid, "priority": prio, "when": when, "then": {"code": code}}


def test_sample_data_loads_without_warnings(kb):
    assert {t.table_id for t in kb.tables} == {"plastic_waste", "mixed_waste"}
    assert kb.warnings == ()
    pw = next(t for t in kb.tables if t.table_id == "plastic_waste")
    assert {"CM-PCB", "CM-RESIDUE", "CM-TOXIC"} <= {r.rule_id for r in pw.rules}


@pytest.mark.parametrize(
    "when, msg",
    [
        ({"fact": "zzz", "op": "eq", "value": 1}, "카탈로그에 없는"),
        ({"fact": "e", "op": "lt", "value": 1}, "number 사실에만"),
        ({"fact": "n", "op": "eq", "value": "x"}, "숫자 값"),
        ({"fact": "e", "op": "eq", "value": "Z"}, "값 영역에 없는"),
        ({"fact": "b", "op": "eq", "value": "yes"}, "true/false"),
        ({"fact": "e", "op": "in", "value": []}, "비지 않은 목록"),
        ({"fact": "n", "op": "between", "value": 1}, "지원하지 않는 연산자"),
        ({"fact": "n", "op": "lt", "value": 1, "min_status": "UNKNOWN"}, "min_status"),
        ({"all": []}, "비지 않은 목록"),
    ],
)
def test_invalid_conditions_rejected(when, msg):
    with pytest.raises(RuleDataError, match=msg):
        build_kb(CAT, [table([rule("R1", when)])])


def test_duplicate_rule_id_rejected():
    w = {"fact": "b", "op": "eq", "value": True}
    with pytest.raises(RuleDataError, match="rule_id 중복"):
        build_kb(CAT, [table([rule("R1", w), rule("R1", w)])])


def test_priority_required():
    r = {"rule_id": "R1", "when": {"fact": "b", "op": "eq", "value": True}, "then": {"code": "X"}}
    with pytest.raises(RuleDataError, match="priority"):
        build_kb(CAT, [table([r])])


def test_unknown_code_rejected_when_code_table_present():
    w = {"fact": "b", "op": "eq", "value": True}
    with pytest.raises(RuleDataError, match="코드표에 없는"):
        build_kb(
            CAT,
            [table([rule("R1", w, code="NOPE")])],
            codes={"codes": [{"code": "X", "name": "x"}]},
        )


def test_unique_overlap_warning_and_disjoint_pairs():
    overlap = build_kb(
        CAT,
        [
            table(
                [
                    rule("R1", {"fact": "b", "op": "eq", "value": True}, code="X"),
                    rule("R2", {"fact": "b2", "op": "eq", "value": True}, code="Y"),
                ],
                hit="UNIQUE",
            )
        ],
    )
    assert any("겹칠 수 있음" in w for w in overlap.warnings)

    disjoint = build_kb(
        CAT,
        [
            table(
                [
                    rule("R1", {"all": [{"fact": "e", "op": "eq", "value": "A"}]}, code="X"),
                    rule("R2", {"all": [{"fact": "e", "op": "in", "value": ["B", "C"]}]}, code="Y"),
                ],
                hit="UNIQUE",
            )
        ],
    )
    assert disjoint.warnings == ()

    numeric = build_kb(
        CAT,
        [
            table(
                [
                    rule("R1", {"fact": "n", "op": "lt", "value": 5}, code="X"),
                    rule("R2", {"fact": "n", "op": "gte", "value": 5}, code="Y"),
                ],
                hit="UNIQUE",
            )
        ],
    )
    assert numeric.warnings == ()


def test_priority_same_level_overlap_warning():
    kb = build_kb(
        CAT,
        [
            table(
                [
                    rule("R1", {"fact": "b", "op": "eq", "value": True}, code="X", prio=5),
                    rule("R2", {"fact": "b2", "op": "eq", "value": True}, code="Y", prio=5),
                ]
            )
        ],
    )
    assert any("priority 5" in w for w in kb.warnings)


def test_group_requires_none_value():
    cat = CAT + [{"key": "b3", "type": "bool", "question_hint": "b3"}]
    w = {"fact": "b", "op": "eq", "value": True}
    with pytest.raises(RuleDataError, match="none_value"):
        build_kb(
            cat,
            [table([rule("R1", w)])],
            groups={"groups": [{"group_id": "g", "title": "g", "facts": ["b", "b3"]}]},
        )


def test_effective_dates_filter_rules_and_tables():
    w = {"fact": "b", "op": "eq", "value": True}
    r_old = rule("OLD", w, code="X") | {"effective_to": "2026-01-01"}
    r_new = rule("NEW", w, code="X") | {"effective_from": "2026-01-01"}
    kb = build_kb(CAT, [table([r_old, r_new], effective_from="2025-01-01")])
    t = kb.tables[0]
    assert [r.rule_id for r in t.rules_as_of(date(2025, 6, 1))] == ["OLD"]
    assert [r.rule_id for r in t.rules_as_of(date(2026, 6, 1))] == ["NEW"]
    assert kb.tables_as_of(date(2024, 1, 1)) == ()
