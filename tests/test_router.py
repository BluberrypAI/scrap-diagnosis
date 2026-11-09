from app.agent.router import Branch, SessionState, run_engine
from app.domain.facts import FactStatus, FactStore
from tests.conftest import AS_OF, CLEAN, F


def run(kb, hist, state=None, **kw):
    return run_engine(kb, FactStore(hist), state or SessionState(), AS_OF, **kw)


def base_hist(**extra):
    kv = dict(material="PP", form="FILM", **CLEAN) | extra
    return [F(k, v) for k, v in kv.items()]


def test_ask_fact_when_missing(kb):
    d = run(kb, []).decision
    assert d.branch == Branch.ASK_FACT and d.rank == 3 and d.question.key == "material"


def test_unsupported_when_no_table(kb):
    d = run(kb, [F("material", "OTHER")]).decision
    assert d.branch == Branch.UNSUPPORTED and d.failure_reason == "NO_TABLE"
    assert d.next_status == "NEEDS_INFO"


def test_request_evidence_after_declared_unknown(kb):
    hist = base_hist() + [F("oil_content_pct", None, FactStatus.DECLARED_UNKNOWN)]
    d = run(kb, hist).decision
    assert d.branch == Branch.REQUEST_EVIDENCE
    assert [r.evidence_type for r in d.requested_documents] == ["TEST_REPORT"]
    assert d.requested_documents[0].facts == ["oil_content_pct"]


def test_claimed_value_still_needs_evidence(kb):
    d = run(kb, base_hist(oil_content_pct=3)).decision
    assert d.branch == Branch.REQUEST_EVIDENCE


def test_evidence_refused_is_unsupported(kb):
    hist = base_hist() + [F("oil_content_pct", None, FactStatus.DECLARED_UNKNOWN)]
    d = run(kb, hist, SessionState(evidence_refused=True)).decision
    assert d.branch == Branch.UNSUPPORTED and d.failure_reason == "UNDETERMINABLE"


def test_final_review_when_decided(kb):
    hist = base_hist() + [F("oil_content_pct", 2.0, FactStatus.EVIDENCED)]
    step = run(kb, hist)
    assert step.decision.branch == Branch.FINAL_REVIEW and step.decision.rank == 5
    assert step.evaluation.decided.code == "SAMPLE-A"


def test_decided_beats_question_limit(kb):
    hist = base_hist() + [F("oil_content_pct", 2.0, FactStatus.EVIDENCED)]
    d = run(kb, hist, SessionState(questions_asked=99)).decision
    assert d.branch == Branch.FINAL_REVIEW


def test_question_limit(kb):
    d = run(kb, [F("material", "PP")], SessionState(questions_asked=12)).decision
    assert d.branch == Branch.UNSUPPORTED and d.failure_reason == "QUESTION_LIMIT"
    d = run(kb, [F("material", "PP")], SessionState(questions_asked=3), max_questions=3).decision
    assert d.failure_reason == "QUESTION_LIMIT"


def test_conflict_claim_vs_evidence(kb):
    hist = base_hist() + [
        F("oil_content_pct", 2.0, FactStatus.EVIDENCED, t=1),
        F("oil_content_pct", 8.0, FactStatus.CLAIMED, t=2),
    ]
    d = run(kb, hist).decision
    assert d.branch == Branch.RESOLVE_CONFLICT and d.rank == 1
    (c,) = d.conflicts
    assert c.kind == "CLAIM_VS_EVIDENCE" and c.facts == ["oil_content_pct"]
    # 같은 값을 다시 진술하면 해소된다
    hist.append(F("oil_content_pct", 2.0, FactStatus.CLAIMED, t=3))
    assert run(kb, hist).decision.branch == Branch.FINAL_REVIEW


def test_claimed_range_consistent_with_evidence_is_not_conflict(kb):
    hist = base_hist() + [
        F("oil_content_pct", {"lo": None, "hi": 5, "hi_inc": False}, t=1),
        F("oil_content_pct", 2.0, FactStatus.EVIDENCED, t=2),
    ]
    assert run(kb, hist).decision.branch == Branch.FINAL_REVIEW


def test_no_candidate_conflict():
    from app.rules.loader import build_kb

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
                        "rule_id": "R1",
                        "priority": 2,
                        "when": {"fact": "a", "op": "eq", "value": True},
                        "then": {"code": "X"},
                    },
                    {
                        "rule_id": "R2",
                        "priority": 1,
                        "when": {
                            "all": [
                                {"fact": "a", "op": "eq", "value": True},
                                {"fact": "b", "op": "eq", "value": True},
                            ]
                        },
                        "then": {"code": "Y"},
                    },
                ],
            }
        ],
    )
    d = run(kb, [F("a", False), F("b", False)]).decision
    assert d.branch == Branch.RESOLVE_CONFLICT
    (c,) = d.conflicts
    assert c.kind == "NO_CANDIDATE" and c.facts == ["a"]  # a 하나로 두 규칙이 모두 설명됨


def test_user_question_sub_branch_keeps_branch(kb):
    d = run(kb, [], user_question="왜 기름이 중요해?").decision
    assert d.branch == Branch.ASK_FACT and d.sub_branch == "ANSWER_USER_QUESTION"
