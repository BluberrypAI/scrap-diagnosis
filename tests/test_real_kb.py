"""변환한 실제 규칙(data/real)의 구조와 대표 시나리오."""

import time

import pytest
import yaml

from app.agent.router import Branch, SessionState, run_engine
from app.agent.simulation import simulate
from app.domain.facts import FactStatus, FactStore
from app.rules.evaluator import evaluate
from app.rules.model import iter_conds
from tests.conftest import AS_OF, REAL, F

SCENARIOS = {
    s["id"]: s
    for s in yaml.safe_load((REAL / "scenarios" / "basic.yaml").read_text(encoding="utf-8"))
}

# 소재를 미리 모르면 소재 분류 → 소재 두 단계로 묻는다(소재 질문 1개 → 2개).
# (최종 분기, 코드, 질문 수, 코드 없는 결론). 코드 없는 결론도 FINAL_REVIEW로 확정할 수 있다.
EXPECT = {
    "REAL-PP-CLEAN": ("FINAL_REVIEW", "51-03-01", 5, None),
    "REAL-PP-PREFILL": ("FINAL_REVIEW", "51-03-01", 2, None),
    "REAL-PP-EXPAND": ("FINAL_REVIEW", "51-03-01", 12, None),
    "REAL-H2SO4": ("FINAL_REVIEW", "02-01-02", 3, None),
    # D2(2026-11-09): PCB 관문이 대리 질문이 되어 유해화학물질 경로에서도 묻는다(6 → 7회)
    "REAL-PP-TOXIC": ("FINAL_REVIEW", "09-01-00", 7, None),
    # D1(2026-11-09): 해석 필요 결론끼리 합쳐져 상태·다른 법 질문을 먼저 묻는다(4 → 6회)
    "REAL-NOT-WASTE": ("FINAL_REVIEW", None, 6, "INTERPRETATION_NEEDED"),
    "REAL-SLUDGE-NO-REPORT": ("UNSUPPORTED", None, 4, None),
    "REAL-SOLVENT-GROUP": ("FINAL_REVIEW", "04-02-00", 3, None),
    "REAL-MIXED-AUTO": ("FINAL_REVIEW", None, 3, "NO_MIXTURE_RULE"),
}


def test_structure(real_kb):
    assert real_kb.warnings == ()
    assert len(real_kb.tables) == 97
    assert all(t.effective_from.isoformat() == "2026-10-02" for t in real_kb.tables)
    code = real_kb.catalog["annex4_code"]
    assert code.domain == "referenced" and code.ask_last and code.auto_single and code.internal
    assert {g.group_id for g in real_kb.groups} == {"scope_screen", "contamination_screen"}


def test_each_material_selects_exactly_one_table(real_kb):
    for mid in real_kb.catalog["material"].values:
        ev = evaluate(real_kb, {"material": F("material", mid)}, AS_OF)
        assert ev.table_status == "SELECTED" and ev.table_id == mid


def test_test_facts_require_evidence(real_kb):
    test_facts = {k for k, fd in real_kb.catalog.items() if fd.evidence_type == "TEST_REPORT"}
    assert {"ph", "oil_content_pct", "leach_pb"} <= test_facts
    for t in real_kb.tables:
        for r in t.rules:
            for c in iter_conds(r.when):
                if c.fact in test_facts:
                    assert c.min_status == FactStatus.EVIDENCED, (r.rule_id, c.fact)


def test_all_rules_carry_basis_and_review(real_kb):
    for t in real_kb.tables:
        for r in t.rules:
            assert r.basis, r.rule_id
            assert r.review == "UNVERIFIED", r.rule_id


@pytest.mark.parametrize("sid", sorted(EXPECT))
def test_real_scenarios(real_kb, sid):
    res = simulate(real_kb, SCENARIOS[sid])
    got = (res.final_branch, res.final_code, res.questions_asked, res.final_outcome)
    assert got == EXPECT[sid]


def test_screening_beats_one_by_one(real_kb):
    a = simulate(real_kb, SCENARIOS["REAL-PP-CLEAN"])
    b = simulate(real_kb, SCENARIOS["REAL-PP-EXPAND"])
    assert a.final_code == b.final_code
    assert a.questions_asked < b.questions_asked


def test_unknown_test_value_requests_whole_report(real_kb):
    # 한 시험 항목을 모르면 같은 성적서의 다른 항목은 묻지 않고 한 번에 요청한다.
    hist = [
        F(k, v)
        for k, v in dict(
            material="sludge_ww_inorganic",
            emission_facility=True,
            material_fate="released",
            circular_resource_recognized=False,
            law_exclusion="none",
            designated_residue=False,
            oil_presence="none",
            pcb_possible=False,
            toxic_chemical_discard=False,
            sludge_facility_notified=True,
        ).items()
    ] + [F("sludge_water_pct", None, FactStatus.DECLARED_UNKNOWN)]
    d = run_engine(real_kb, FactStore(hist), SessionState(), AS_OF).decision
    assert d.branch == Branch.REQUEST_EVIDENCE
    (doc,) = d.requested_documents
    assert doc.evidence_type == "TEST_REPORT"
    assert {"sludge_water_pct", "leach_pb", "leach_hg"} <= set(doc.facts)


def test_code_choice_auto_filled_when_single(real_kb):
    hist = [
        F(k, v)
        for k, v in dict(
            material="pp",
            emission_facility=True,
            material_fate="released",
            circular_resource_recognized=False,
            law_exclusion="none",
            designated_residue=False,
            oil_presence="none",
            pcb_possible=False,
            toxic_chemical_discard=False,
            physical_state="liquid",
        ).items()
    ]
    store = FactStore(hist)
    step = run_engine(real_kb, store, SessionState(), AS_OF)
    assert step.decision.branch == Branch.FINAL_REVIEW
    assert step.evaluation.decided.code == "01-01-02"
    auto = store.history_of("annex4_code")
    assert len(auto) == 1 and auto[0].source_type == "DERIVED"


def test_first_question_is_fast(real_kb):
    t = time.perf_counter()
    step = run_engine(real_kb, FactStore(), SessionState(), AS_OF)
    elapsed = time.perf_counter() - t
    assert step.decision.question.key == "material_group"
    assert elapsed < 1.0, elapsed
