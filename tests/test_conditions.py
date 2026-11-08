"""연산자 × 사실 상태 조합 (md 6.1)."""

import pytest

from app.domain.facts import Fact, FactStatus
from app.rules.evaluator import TV, eval_cond
from app.rules.model import Cond, FactDef

S = FactStatus
CAT = {
    "n": FactDef(key="n", type="number", question_hint="n"),
    "e": FactDef(key="e", type="enum", question_hint="e", values=("A", "B")),
    "b": FactDef(key="b", type="bool", question_hint="b"),
}

# (조건, 참이 되는 값, 거짓이 되는 값)
CASES = [
    (Cond("n", "eq", 5), 5, 4),
    (Cond("n", "ne", 5), 4, 5),
    (Cond("n", "lt", 5), 4.9, 5),
    (Cond("n", "lte", 5), 5, 5.1),
    (Cond("n", "gt", 5), 5.1, 5),
    (Cond("n", "gte", 5), 5, 4.9),
    (Cond("e", "eq", "A"), "A", "B"),
    (Cond("e", "ne", "A"), "B", "A"),
    (Cond("e", "in", ("A",)), "A", "B"),
    (Cond("e", "not_in", ("A",)), "B", "A"),
    (Cond("b", "eq", True), True, False),
]


def _f(key, value, status):
    return {key: Fact(key=key, value=value, status=status)}


@pytest.mark.parametrize("cond, tval, fval", CASES)
@pytest.mark.parametrize("min_status", [S.CLAIMED, S.EVIDENCED])
@pytest.mark.parametrize("status", list(S))
def test_operator_status_matrix(cond, tval, fval, min_status, status):
    c = Cond(cond.fact, cond.op, cond.value, min_status)
    r_true = eval_cond(c, _f(c.fact, tval, status), CAT)
    r_false = eval_cond(c, _f(c.fact, fval, status), CAT)
    if status in (S.UNKNOWN, S.DECLARED_UNKNOWN):
        assert r_true.status == r_false.status == TV.UNKNOWN
        expected = "DECLARED_UNKNOWN" if status == S.DECLARED_UNKNOWN else "MISSING"
        assert r_true.reason == expected
        return
    # 값으로 거짓이면 상태와 무관하게 FALSE (CLAIMED로도 후보를 지울 수 있다)
    assert r_false.status == TV.FALSE
    if status == S.CLAIMED and min_status == S.EVIDENCED:
        assert r_true.status == TV.UNKNOWN and r_true.reason == "NEEDS_EVIDENCE"
    else:
        assert r_true.status == TV.TRUE


def test_missing_fact_is_unknown():
    r = eval_cond(Cond("n", "lt", 5), {}, CAT)
    assert r.status == TV.UNKNOWN and r.reason == "MISSING"


def test_null_value_with_claimed_status_is_unknown():
    # "기름 좀 있다" → 값 null. 수치를 지어내지 않는다.
    r = eval_cond(Cond("n", "lt", 5), _f("n", None, S.CLAIMED), CAT)
    assert r.status == TV.UNKNOWN


def test_exists():
    assert eval_cond(Cond("n", "exists"), _f("n", 1, S.CLAIMED), CAT).status == TV.TRUE
    assert eval_cond(Cond("n", "exists"), {}, CAT).status == TV.UNKNOWN
    r = eval_cond(Cond("n", "exists", None, S.EVIDENCED), _f("n", 1, S.CLAIMED), CAT)
    assert r.reason == "NEEDS_EVIDENCE"


def test_type_mismatch_is_unknown_not_crash():
    r = eval_cond(Cond("n", "lt", 5), _f("n", "많음", S.CLAIMED), CAT)
    assert r.status == TV.UNKNOWN
