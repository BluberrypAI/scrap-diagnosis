"""질문 전략 분리: 대리 질문의 추정(implies)과 대리 질문 선택(app/rules/implications.py).

SAMPLE 규칙의 PCB 규칙을 법 조건(PCB 함량 ≥ 2, 성적서 필요)으로 바꾸고, "PCB 관련" 질문을
대리 질문으로 둔 복사본으로 시험한다.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from app.agent.router import Branch, SessionState, run_engine
from app.domain.facts import Fact, FactStatus, FactStore
from app.domain.ranges import NumRange
from app.rules.answers import fact_answer, group_none_answer
from app.rules.implications import apply_implications, screening_map
from app.rules.loader import RuleDataError, load_kb
from tests.conftest import DATA

AS_OF = date(2026, 11, 8)


def _sample_with_screening(tmp_path: Path, implies: dict | None = None) -> Path:
    src = tmp_path / "kb"
    shutil.copytree(DATA, src)
    cat_path = src / "facts_catalog.yaml"
    cat = yaml.safe_load(cat_path.read_text(encoding="utf-8"))
    for f in cat:
        if f["key"] == "pcb_related":
            f["implies"] = implies if implies is not None else {False: {"pcb_mg_l": {"hi": 2}}}
    cat.append(
        {
            "key": "pcb_mg_l",
            "label": "PCB 함량",
            "type": "number",
            "unit": "mg/L",
            "ask_cost": 4,
            "evidence_type": "TEST_REPORT",
            "legal_priority": 3,
            "question_hint": "PCB 함량(mg/L)",
        }
    )
    cat_path.write_text(yaml.safe_dump(cat, allow_unicode=True), encoding="utf-8")
    cm_path = src / "rules" / "common" / "contamination.yaml"
    cm = yaml.safe_load(cm_path.read_text(encoding="utf-8"))
    for r in cm["rules"]:
        if r["rule_id"] == "CM-PCB":  # 법 조건만: PCB 함량 2mg/L 이상(성적서)
            r["when"] = {"fact": "pcb_mg_l", "op": "gte", "value": 2, "min_status": "EVIDENCED"}
    cm_path.write_text(yaml.safe_dump(cm, allow_unicode=True), encoding="utf-8")
    return src


@pytest.fixture
def kb(tmp_path):
    return load_kb(_sample_with_screening(tmp_path))


def _store(kb, **kv) -> FactStore:
    store = FactStore()
    for k, v in kv.items():
        status = (
            FactStatus.EVIDENCED if k in ("oil_content_pct", "pcb_mg_l") else FactStatus.CLAIMED
        )
        store.append(fact_answer(kb, k, v, status=status))
    return store


BASE = {"material": "PP", "form": "FILM", "oil_content_pct": 1.0}


def test_screening_answer_implies_target_value(kb):
    assert screening_map(kb) == {"pcb_mg_l": ["pcb_related"]}
    facts = _store(kb, pcb_related=False).effective()
    out = apply_implications(kb, facts)
    f = out["pcb_mg_l"]
    assert f.source_type == "DERIVED" and f.value == NumRange(hi=2)
    assert "pcb_mg_l" not in facts  # 저장하지 않는다
    # '예'는 추정하지 않는다
    assert "pcb_mg_l" not in apply_implications(kb, _store(kb, pcb_related=True).effective())


def test_explicit_value_wins_over_implication(kb):
    store = _store(kb, pcb_related=False, pcb_mg_l=3.0, **BASE)
    store.extend(
        group_none_answer(kb, "contamination_screen", ["hazardous_residue", "toxic_chemical"])
    )
    ev = run_engine(kb, store, SessionState(), AS_OF).evaluation
    assert ev.decided is not None and ev.decided.code == "SAMPLE-D1"  # 성적서 3mg/L → 지정


def test_proxy_question_is_asked_instead_of_test_value(kb):
    store = _store(kb, hazardous_residue=False, toxic_chemical=False, **BASE)
    step = run_engine(kb, store, SessionState(), AS_OF)
    q = step.decision.question
    assert step.decision.branch == Branch.ASK_FACT and q.key == "pcb_related"  # 함량 대신 대리 질문

    store.append(fact_answer(kb, "pcb_related", False))  # 관련 없음 → 함량 기준 미만으로 추정
    step = run_engine(kb, store, SessionState(), AS_OF)
    assert step.decision.branch == Branch.FINAL_REVIEW
    assert step.evaluation.decided.code == "SAMPLE-A"
    assert step.effective["pcb_mg_l"].source_type == "DERIVED"  # 판정 보드·Trace에 보인다


def test_yes_or_unknown_then_asks_target_directly(kb):
    store = _store(kb, pcb_related=True, hazardous_residue=False, toxic_chemical=False, **BASE)
    q = run_engine(kb, store, SessionState(), AS_OF).decision.question
    assert q is not None and q.key == "pcb_mg_l"
    store = _store(kb, hazardous_residue=False, toxic_chemical=False, **BASE)
    store.append(fact_answer(kb, "pcb_related", None, unknown=True))
    q = run_engine(kb, store, SessionState(), AS_OF).decision.question
    assert q is not None and q.key == "pcb_mg_l"


def test_retracting_screening_answer_removes_implication(kb):
    store = _store(kb, pcb_related=False, **BASE)
    assert "pcb_mg_l" in apply_implications(kb, store.effective())
    store.append(Fact(key="pcb_related", value=None, status=FactStatus.UNKNOWN, retracted=True))
    assert "pcb_mg_l" not in apply_implications(kb, store.effective())


def test_group_none_all_works_through_proxy(kb):
    store = _store(kb, **BASE)
    q = run_engine(kb, store, SessionState(), AS_OF).decision.question
    assert q.unit == "group" and "pcb_related" in q.facts  # 묶음 질문에 대리 질문이 들어간다
    store.extend(group_none_answer(kb, q.key, q.facts))
    ev = run_engine(kb, store, SessionState(), AS_OF).evaluation
    assert ev.decided is not None and ev.decided.code == "SAMPLE-A"


def test_invalid_implies_is_rejected(tmp_path):
    src = _sample_with_screening(tmp_path, implies={False: {"no_such_fact": 1}})
    with pytest.raises(RuleDataError, match="implies"):
        load_kb(src)


def test_complement_must_target_another_number_fact(tmp_path):
    src = _sample_with_screening(tmp_path)
    cat_path = src / "facts_catalog.yaml"
    cat = yaml.safe_load(cat_path.read_text(encoding="utf-8"))
    for f in cat:
        if f["key"] == "oil_content_pct":
            f["complement"] = {"fact": "material", "total": 100}  # enum 사실은 안 됨
    cat_path.write_text(yaml.safe_dump(cat, allow_unicode=True), encoding="utf-8")
    with pytest.raises(RuleDataError, match="complement"):
        load_kb(src)


def test_complement_value_of_range():
    from app.rules.implications import _complement_value

    # 수분 95% 미만 ⇔ 고형물 5% 초과
    assert _complement_value(NumRange(hi=95), 100) == NumRange(lo=5, lo_inc=False)
    assert _complement_value(NumRange(lo=95), 100) == NumRange(hi=5, hi_inc=True)
    assert _complement_value(96.9, 100) == pytest.approx(3.1)
