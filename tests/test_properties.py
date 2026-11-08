"""속성 테스트: 순서 불변성·단조성 (md 6.5)."""

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.facts import FactStatus, FactStore
from app.rules.evaluator import evaluate
from app.rules.loader import load_kb  # noqa: E402  (모듈 수준 KB 캐시)
from tests.conftest import AS_OF, DATA, F

KB = load_kb(DATA)

STATUSES = st.sampled_from(
    [FactStatus.CLAIMED, FactStatus.EVIDENCED, FactStatus.DECLARED_UNKNOWN, FactStatus.UNKNOWN]
)


def value_strategy(key):
    fd = KB.catalog[key]
    if fd.type == "enum":
        return st.sampled_from(fd.values)
    if fd.type == "bool":
        return st.booleans()
    return st.sampled_from([0, 2.5, 4.99, 5, 5.01, 30])


@st.composite
def fact_lists(draw, max_size=12):
    keys = sorted(KB.catalog)
    n = draw(st.integers(0, max_size))
    out = []
    for i in range(n):
        k = draw(st.sampled_from(keys))
        status = draw(STATUSES)
        v = (
            None
            if status in (FactStatus.UNKNOWN, FactStatus.DECLARED_UNKNOWN)
            else draw(value_strategy(k))
        )
        out.append(F(k, v, status, t=draw(st.integers(0, 5)), ref=f"m{i}"))
    return out


def snapshot(fact_list):
    r = evaluate(KB, FactStore(fact_list).effective(), AS_OF)
    return r.model_dump(mode="json")


@settings(max_examples=200, deadline=None)
@given(fact_lists(), st.randoms())
def test_order_invariance(fact_list, rnd):
    shuffled = list(fact_list)
    rnd.shuffle(shuffled)
    assert snapshot(fact_list) == snapshot(shuffled)


@settings(max_examples=200, deadline=None)
@given(st.data())
def test_monotonic_candidates_when_adding_new_facts(data):
    """서로 다른 키의 사실을 추가하면(정정 아님) 후보 집합은 커지지 않는다."""
    keys = sorted(KB.catalog)
    chosen = data.draw(st.lists(st.sampled_from(keys), unique=True, max_size=len(keys)))
    current = {}
    material = data.draw(st.sampled_from(KB.catalog["material"].values))
    current["material"] = F("material", material)
    prev = {c.code for c in evaluate(KB, current, AS_OF).candidates}
    for k in chosen:
        if k == "material":
            continue
        status = data.draw(st.sampled_from([FactStatus.CLAIMED, FactStatus.EVIDENCED]))
        current[k] = F(k, data.draw(value_strategy(k)), status)
        now = {c.code for c in evaluate(KB, current, AS_OF).candidates}
        assert now <= prev, (k, prev, now)
        prev = now
