"""테이블 평가·확정 조건 (docs/engine/algorithm.md 4.3~4.5절)과 blocking_facts 보강."""

from app.domain.facts import FactStatus, FactStore
from app.rules.evaluator import TV, evaluate
from app.rules.loader import build_kb
from tests.conftest import AS_OF, CLEAN, F, facts

E = "EVIDENCED"


def codes(cands):
    return [c.code for c in cands]


def test_table_pending_until_material_known(kb):
    r = evaluate(kb, {}, AS_OF)
    assert r.table_status == "PENDING"
    assert [u.key for u in r.blocking_facts] == ["material"]
    assert r.decided is None


def test_table_none_is_out_of_scope(kb):
    r = evaluate(kb, facts(material="OTHER"), AS_OF)
    assert r.table_status == "NONE"


def test_full_facts_decide_general_code(kb):
    r = evaluate(kb, facts(material="PP", form="FILM", oil_content_pct=(3, E), **CLEAN), AS_OF)
    assert r.table_id == "plastic_waste" and r.table_version == "2026.11.0"
    assert r.decided is not None and r.decided.code == "SAMPLE-A"
    assert r.can_confirm
    assert r.blocking_facts == []


def test_higher_priority_unknown_blocks_lower_true(kb):
    # 오염 사실을 모르면 하위 일반 코드 규칙이 TRUE여도 확정하지 않는다.
    r = evaluate(kb, facts(material="PP", form="FILM", oil_content_pct=(3, E)), AS_OF)
    assert r.decided is None
    assert {u.key for u in r.blocking_facts} == {
        "pcb_related",
        "hazardous_residue",
        "toxic_chemical",
    }
    # 하위 규칙(SAMPLE-Z 등)은 이미 FALSE거나 확정에 무관하다.
    assert "form" not in {u.key for u in r.blocking_facts}


def test_designated_true_decides_immediately(kb):
    # 최상위 지정 규칙이 TRUE면 다른 사실을 물을 필요가 없다.
    r = evaluate(kb, facts(material="PP", pcb_related=True), AS_OF)
    assert r.decided is not None and r.decided.code == "SAMPLE-D1"
    assert r.decided.category == "DESIGNATED"
    assert r.blocking_facts == []
    assert codes(r.live_candidates) == ["SAMPLE-D1"]


def test_lower_priority_true_still_blocked_by_higher_unknown(kb):
    r = evaluate(kb, facts(material="PP", toxic_chemical=True), AS_OF)
    assert r.decided is None
    assert {u.key for u in r.blocking_facts} == {"pcb_related", "hazardous_residue"}


def test_claimed_value_eliminates_but_needs_evidence_to_confirm(kb):
    r = evaluate(kb, facts(material="PP", form="FILM", oil_content_pct=3, **CLEAN), AS_OF)
    assert "SAMPLE-B" not in codes(r.candidates)  # CLAIMED 3%로 ≥5% 후보는 지운다
    assert r.decided is None
    (u,) = r.blocking_facts
    assert u.key == "oil_content_pct" and u.reason == "NEEDS_EVIDENCE"
    assert u.evidence_type == "TEST_REPORT"
    pw002 = next(rr for rr in r.rule_results if rr.rule_id == "PW-002")
    assert pw002.status == TV.FALSE and pw002.eliminated_by == ["oil_content_pct"]


def test_declared_unknown_with_evidence_type_needs_evidence(kb):
    fs = facts(material="PP", form="FILM", **CLEAN)
    fs["oil_content_pct"] = F("oil_content_pct", None, FactStatus.DECLARED_UNKNOWN)
    r = evaluate(kb, fs, AS_OF)
    (u,) = r.blocking_facts
    assert u.reason == "NEEDS_EVIDENCE"


def test_declared_unknown_without_evidence_type():
    kb = build_kb(
        [{"key": "b", "type": "bool", "question_hint": "b"}],
        [
            {
                "table_id": "t",
                "version": "1",
                "hit_policy": "PRIORITY",
                "rules": [
                    {
                        "rule_id": "R1",
                        "priority": 1,
                        "when": {"fact": "b", "op": "eq", "value": True},
                        "then": {"code": "X"},
                    }
                ],
            }
        ],
    )
    r = evaluate(kb, {"b": F("b", None, FactStatus.DECLARED_UNKNOWN)}, AS_OF)
    assert r.blocking_facts[0].reason == "DECLARED_UNKNOWN"


def test_unique_policy(kb):
    r = evaluate(kb, facts(material="MIXED"), AS_OF)
    assert r.table_id == "mixed_waste" and r.decided is None
    assert [u.key for u in r.blocking_facts] == ["emission_facility"]
    r = evaluate(kb, facts(material="MIXED", emission_facility=False), AS_OF)
    assert r.decided.code == "SAMPLE-C"


def _tie_kb(hit="PRIORITY", with_higher=False):
    rules = [
        {
            "rule_id": "R1",
            "priority": 5,
            "when": {"fact": "a", "op": "eq", "value": True},
            "then": {"code": "X"},
        },
        {
            "rule_id": "R2",
            "priority": 5,
            "when": {"fact": "b", "op": "eq", "value": True},
            "then": {"code": "Y"},
        },
    ]
    if with_higher:
        rules.append(
            {
                "rule_id": "R3",
                "priority": 9,
                "when": {"fact": "a", "op": "eq", "value": True},
                "then": {"code": "X"},
            }
        )
    return build_kb(
        [
            {"key": "a", "type": "bool", "question_hint": "a"},
            {"key": "b", "type": "bool", "question_hint": "b"},
        ],
        [{"table_id": "t", "version": "1", "hit_policy": hit, "rules": rules}],
    )


def test_same_priority_true_with_different_codes_is_tie():
    r = evaluate(_tie_kb(), facts(a=True, b=True), AS_OF)
    assert r.decided is None and r.tie == ["R1", "R2"]
    # 더 높은 우선순위 규칙이 TRUE면 동순위 충돌과 무관하게 확정된다.
    r = evaluate(_tie_kb(with_higher=True), facts(a=True, b=True), AS_OF)
    assert r.decided.code == "X" and r.decided.rule_ids[0] == "R3"


def test_same_code_higher_unknown_does_not_block():
    kb = build_kb(
        [
            {"key": "a", "type": "bool", "question_hint": "a"},
            {"key": "b", "type": "bool", "question_hint": "b"},
        ],
        [
            {
                "table_id": "t",
                "version": "1",
                "hit_policy": "PRIORITY",
                "rules": [
                    {
                        "rule_id": "HI",
                        "priority": 9,
                        "when": {"fact": "b", "op": "eq", "value": True},
                        "then": {"code": "X"},
                    },
                    {
                        "rule_id": "LO",
                        "priority": 1,
                        "when": {"fact": "a", "op": "eq", "value": True},
                        "then": {"code": "X"},
                    },
                ],
            }
        ],
    )
    r = evaluate(kb, facts(a=True), AS_OF)
    assert r.decided is not None and r.decided.code == "X"


def test_unique_two_true_different_codes_not_decided():
    r = evaluate(_tie_kb("UNIQUE"), facts(a=True, b=True), AS_OF)
    assert r.decided is None and r.tie


def test_effective_fact_prefers_evidenced_then_latest():
    store = FactStore(
        [
            F("oil_content_pct", 3, FactStatus.EVIDENCED, t=0),
            F("oil_content_pct", 7, FactStatus.CLAIMED, t=10),
        ]
    )
    assert store.effective()["oil_content_pct"].value == 3
    store.append(F("oil_content_pct", 4, FactStatus.EVIDENCED, t=20))
    assert store.effective()["oil_content_pct"].value == 4
    store.append(F("oil_content_pct", None, FactStatus.DECLARED_UNKNOWN, t=30))
    assert store.effective()["oil_content_pct"].value == 4
    assert len(store.history_of("oil_content_pct")) == 4  # append-only
