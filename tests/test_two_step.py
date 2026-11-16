"""2단계 질문(상위 분류 → 세부 값): 카탈로그 parent/value_parent."""

import pytest

from app.agent.extractor import catalog_view
from app.agent.guard import validate_extraction
from app.agent.router import Branch, SessionState, run_engine
from app.domain.facts import FactStatus, FactStore
from app.rules.evaluator import evaluate
from app.rules.loader import RuleDataError, build_kb, parse_catalog
from app.rules.selector import select_question, value_domain
from tests.conftest import AS_OF, F, facts

GROUP = {
    "key": "grp",
    "type": "enum",
    "question_hint": "분류",
    "values": {"a": "가 분류", "b": "나 분류", "c": "다 분류", "d": "빈 분류"},
}
ITEM = {
    "key": "item",
    "type": "enum",
    "question_hint": "세부",
    "values": {"a1": "가1", "a2": "가2", "b1": "나1", "c1": "다1", "c2": "다2"},
    "parent": "grp",
    "value_parent": {"a1": "a", "a2": "a", "b1": "b", "c1": "c", "c2": "c"},
}


def _table(item: str, code: str) -> dict:
    return {
        "table_id": item,
        "version": "1",
        "hit_policy": "PRIORITY",
        "applies_when": {"fact": "item", "op": "eq", "value": item},
        "rules": [
            {
                "rule_id": f"{item}:X",
                "priority": 2,
                "when": {"fact": "x", "op": "eq", "value": True},
                "then": {"code": f"{code}-X"},
            },
            {
                "rule_id": f"{item}:BASE",
                "priority": 1,
                "when": {"fact": "item", "op": "eq", "value": item},
                "then": {"code": code},
            },
        ],
    }


def _kb(group=GROUP, item=ITEM):
    cat = [group, item, {"key": "x", "type": "bool", "question_hint": "x?"}]
    codes = {"a1": "A1", "a2": "A2", "b1": "B1", "c1": "C1", "c2": "C2"}
    return build_kb(cat, [_table(k, v) for k, v in codes.items() if k in item["values"]])


@pytest.fixture(scope="module")
def kb2():
    return _kb()


def pick(kb, fs):
    return select_question(kb, fs, evaluate(kb, fs, AS_OF), AS_OF)


def values(q):
    return [o.value for o in q.value_options if o.kind == "value"]


# ---- 선택기 -----------------------------------------------------------------------------


def test_parent_is_asked_first(kb2):
    q = pick(kb2, {})
    assert q.key == "grp" and q.facts == ["grp"]
    # 세부 값이 없는 분류(d)는 선택지에 없다. '모름'은 마지막.
    assert values(q) == ["a", "b", "c"]
    assert [o.label for o in q.value_options] == ["가 분류", "나 분류", "다 분류", "모름"]
    assert [e.key for e in q.score_breakdown] == ["grp"]
    # 분류별 남는 후보 = 세부 값 후보의 합집합
    assert q.score_breakdown[0].outcomes == {"가 분류": 4, "나 분류": 2, "다 분류": 4}
    assert q.score_breakdown[0].gain > 0


def test_child_domain_filtered_by_parent(kb2):
    q = pick(kb2, facts(grp="c"))
    assert q.key == "item" and values(q) == ["c1", "c2"]
    assert q.value_options[-1].kind == "unknown"
    dom = value_domain(kb2, kb2.catalog["item"], facts=facts(grp="c"))
    assert [p for _, p in dom] == [0.5, 0.5]


def test_parent_declared_unknown_asks_child_with_all_values(kb2):
    q = pick(kb2, {"grp": F("grp", None, FactStatus.DECLARED_UNKNOWN)})
    assert q.key == "item" and values(q) == ["a1", "a2", "b1", "c1", "c2"]


def test_parent_without_children_does_not_narrow(kb2):
    q = pick(kb2, facts(grp="d"))
    assert q.key == "item" and len(values(q)) == 5


def test_single_parent_value_asks_child_directly():
    item = {**ITEM, "value_parent": dict.fromkeys(ITEM["values"], "a")}
    kb = _kb(item=item)
    q = pick(kb, {})
    assert q.key == "item" and len(values(q)) == 5


def test_selection_is_deterministic(kb2):
    a, b = pick(kb2, {}), pick(kb2, {})
    assert a.model_dump() == b.model_dump()


# ---- 라우터: 자동 채움, 충돌 ---------------------------------------------------------------


def test_single_child_is_auto_filled(kb2):
    store = FactStore([F("grp", "b")])
    step = run_engine(kb2, store, SessionState(), AS_OF)
    (auto,) = store.history_of("item")
    assert auto.value == "b1" and auto.source_type == "DERIVED"
    assert auto.source_ref == "parent_single"
    assert step.evaluation.table_id == "b1"
    assert step.decision.branch == Branch.ASK_FACT and step.decision.question.key == "x"


def test_child_wins_over_conflicting_parent(kb2):
    # 분류는 a라고 했지만 소재는 b1이라고 말함 → 세부 값이 이긴다(막히지 않음).
    store = FactStore([F("grp", "a"), F("item", "b1"), F("x", False)])
    step = run_engine(kb2, store, SessionState(), AS_OF)
    assert step.decision.branch == Branch.FINAL_REVIEW
    assert step.evaluation.decided.code == "B1"
    assert not step.conflicts


# ---- 로더 검증 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("patch", "msg"),
    [
        ({"parent": "nope"}, "카탈로그에 없는 parent"),
        ({"parent": "x"}, "enum 사실끼리만"),
        ({"parent": "item"}, "자기 자신"),
        ({"value_parent": {**ITEM["value_parent"], "a1": "zz"}}, "상위 분류 값"),
        ({"value_parent": {**ITEM["value_parent"], "zz": "a"}}, "값 영역에 없는 값"),
        ({"value_parent": {"a1": "a"}}, "상위 분류가 없는 값"),
        ({"parent": None}, "value_parent에는 parent가 필요"),
        ({"domain": "referenced"}, "domain이 있는 사실"),
    ],
)
def test_loader_rejects_bad_parent(patch, msg):
    item = {**ITEM, **patch}
    with pytest.raises(RuleDataError, match=msg):
        parse_catalog([GROUP, item, {"key": "x", "type": "bool", "question_hint": "x"}])


def test_loader_rejects_parent_chain():
    grp = {**GROUP, "parent": "top", "value_parent": dict.fromkeys(GROUP["values"], "t")}
    top = {"key": "top", "type": "enum", "question_hint": "t", "values": ["t"]}
    with pytest.raises(RuleDataError, match="한 단계만"):
        parse_catalog([top, grp, ITEM])


# ---- 실제 규칙 ---------------------------------------------------------------------------


def test_real_material_group_covers_every_material(real_kb):
    mat = real_kb.catalog["material"]
    grp = real_kb.catalog["material_group"]
    assert mat.parent == "material_group"
    assert set(mat.value_parent) == set(mat.values)
    assert set(mat.value_parent.values()) == set(grp.values)
    assert len(grp.values) == 14
    # 상위 분류는 규칙이 참조하지 않는다(판정은 소재로만).
    assert all("material_group" not in r.facts() for t in real_kb.tables for r in t.rules)


def test_real_first_question_is_material_group(real_kb):
    q = run_engine(real_kb, FactStore(), SessionState(), AS_OF).decision.question
    assert q.key == "material_group"
    assert len(values(q)) == 14 and q.value_options[-1].kind == "unknown"


def test_real_broad_category_limits_material_options(real_kb):
    store = FactStore([F("emission_facility", True), F("material_group", "solvent_paint")])
    q = run_engine(real_kb, store, SessionState(), AS_OF).decision.question
    mat = real_kb.catalog["material"]
    expected = [k for k in mat.values if mat.value_parent[k] == "solvent_paint"]
    assert q.key == "material" and values(q) == expected
    assert {"solvent_halogen", "solvent_other", "paint_oil"} <= set(expected)
    assert len(expected) == 5


def test_real_special_group_auto_fills_mixed_material(real_kb):
    store = FactStore([F("emission_facility", True), F("material_group", "special")])
    step = run_engine(real_kb, store, SessionState(), AS_OF)
    assert step.evaluation.table_id == "mixed_inseparable"
    assert store.history_of("material")[0].source_type == "DERIVED"


# ---- LLM 경계: 추출 검증, 카탈로그 보기 ----------------------------------------------------


def _item(key, value, quote):
    return {
        "key": key,
        "value_text": value,
        "value_number": None,
        "value_bool": None,
        "range": None,
        "status": "CLAIMED",
        "note": None,
        "quote": quote,
    }


def test_guard_accepts_broad_category(real_kb):
    text = "폐유기용제가 나와요"
    raw = {"facts": [_item("material_group", "solvent_paint", "폐유기용제")]}
    res = validate_extraction(real_kb, raw, text, last_question=None, message_id="m1")
    assert not res.rejected
    assert [(f.key, f.value) for f in res.facts] == [("material_group", "solvent_paint")]


def test_catalog_view_links_parent_and_detail(real_kb):
    view = {v["key"]: v for v in catalog_view(real_kb, None)}
    assert view["material"]["parent"] == "material_group"
    assert view["material_group"]["detail_facts"] == ["material"]
    assert "폐유기용제" in view["material_group"]["aliases"]["solvent_paint"]
