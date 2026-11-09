"""규칙 변경 D2: 지정폐기물 누락 막기(오니 수분·고형물, PCB 관문).

자세한 내용: docs/rule-changes/d2-sludge-and-pcb.md
"""

from __future__ import annotations

import pytest

from app.agent.router import Branch, SessionState, run_engine
from app.domain.facts import FactStatus
from tools.legacy_regression import AS_OF, check_row, load_rows, row_store

META, _ = load_rows()
BASE = META["base"]

# 폐수처리 무기성 오니 + 기름성분 5.1%(지정 기준 5% 이상) → 오니 성상이면 지정(01-02-01)
SLUDGE = {
    "oil_presence": "none",
    "toxic_chemical_discard": False,
    "pcb_possible": False,
    "sludge_facility_notified": True,
    "oil_content_pct": 5.1,
}
DESIGNATED, GENERAL = "01-02-01", "51-02-01"


def _sludge_row(code: str, **numbers) -> dict:
    return {
        "id": "d2-sludge",
        "material": "sludge_ww_inorganic",
        "answers": {**SLUDGE, **numbers},
        "expect": {"kind": "CODE", "code": code},
    }


@pytest.mark.parametrize(
    ("numbers", "code"),
    [
        ({"sludge_water_pct": 94.9, "sludge_solids_pct": 5.1}, DESIGNATED),
        # 경계: 수분 95.0은 "95% 미만"이 아니지만 고형물 5.0은 "5% 이상" → 지정(이전에는 일반)
        ({"sludge_water_pct": 95.0, "sludge_solids_pct": 5.0}, DESIGNATED),
        ({"sludge_water_pct": 95.1, "sludge_solids_pct": 4.9}, GENERAL),
        ({"sludge_solids_pct": 5.2}, DESIGNATED),  # 수분 모름 + 고형물 5.2
        ({"sludge_water_pct": 94.8}, DESIGNATED),  # 수분 94.8 + 고형물 모름
        # 수분만 알면 고형물 = 100 − 수분으로 계산(보수 관계, fact_settings.yaml)
        ({"sludge_water_pct": 95.0}, DESIGNATED),  # 고형물 5.0으로 계산
        ({"sludge_water_pct": 96.0}, GENERAL),  # 고형물 4.0으로 계산
        # 성적서에 고형물이 따로 있으면 계산값보다 그 값이 이긴다
        ({"sludge_water_pct": 96.0, "sludge_solids_pct": 5.5}, DESIGNATED),
    ],
)
def test_sludge_state_is_water_below_95_or_solids_at_least_5(real_kb, numbers, code):
    verdict, why, _ = check_row(real_kb, BASE, _sludge_row(code, **numbers))
    assert verdict == "MATCH", why


def test_sludge_solids_is_computed_from_water_and_keeps_evidence(real_kb):
    row = _sludge_row(GENERAL, sludge_water_pct=96.9)
    step = run_engine(real_kb, row_store(real_kb, BASE, row), SessionState(), AS_OF)
    solids = step.effective["sludge_solids_pct"]
    assert solids.source_type == "DERIVED" and solids.value == pytest.approx(3.1)
    assert solids.status == FactStatus.EVIDENCED  # 같은 성적서의 값 → 증빙 상태를 잇는다


def test_sludge_asks_water_first_when_both_unknown(real_kb):
    row = _sludge_row(GENERAL)
    step = run_engine(real_kb, row_store(real_kb, BASE, row), SessionState(), AS_OF)
    assert step.decision.branch == Branch.ASK_FACT
    assert step.decision.question.key == "sludge_water_pct"  # 고형물 대신 함수율을 먼저


def _oil_row(code: str, **answers) -> dict:
    return {
        "id": "d2-pcb",
        "material": "insulating_oil",
        "answers": {"toxic_chemical_discard": False, **answers},
        "expect": {"kind": "CODE", "code": code},
    }


def test_pcb_test_value_designates_even_if_screening_said_no(real_kb):
    # 이전: "PCB 관련 아니오"면 함량 시험값이 2.04여도 지정 규칙이 성립하지 않았다(관문)
    row = _oil_row("08-01-00", pcb_possible=False, pcb_mg_l=2.04)
    verdict, why, _ = check_row(real_kb, BASE, row)
    assert verdict == "MATCH", why


def test_pcb_screening_no_still_concludes_general_without_test(real_kb):
    # "PCB 관련 없음"이면 함량을 기준 미만으로 추정해 시험값 없이 일반 번호로 확정한다
    row = _oil_row("06-01-07", pcb_possible=False)
    verdict, why, _ = check_row(real_kb, BASE, row)
    assert verdict == "MATCH", why
    step = run_engine(real_kb, row_store(real_kb, BASE, row), SessionState(), AS_OF)
    assert step.effective["pcb_mg_l"].source_type == "DERIVED"


def test_pcb_screening_yes_asks_concentration(real_kb):
    row = _oil_row("08-01-00", pcb_possible=True)
    step = run_engine(real_kb, row_store(real_kb, BASE, row), SessionState(), AS_OF)
    assert step.decision.branch == Branch.ASK_FACT
    assert step.decision.question.key == "pcb_mg_l"


def test_pcb_assumption_is_labelled_in_result_and_handoff(real_kb):
    """PCB '관련 없음' 추정은 결과 카드·인계 객체에 '시험값 아님'으로 표시한다(2차 검수)."""
    from datetime import UTC, datetime

    from app.domain.handoff import build_handoff
    from app.domain.verdict import build_result

    row = _oil_row("06-01-07", pcb_possible=False)
    step = run_engine(real_kb, row_store(real_kb, BASE, row), SessionState(), AS_OF)
    rules = {r.rule_id: r for t in real_kb.tables for r in t.rules}
    result = build_result(step, rules, real_kb)
    assert result is not None and any("PCB" in a and "추정" in a for a in result.assumptions)
    decided = step.evaluation.decided
    now = datetime.now(UTC)
    h = build_handoff(
        real_kb,
        case_id="C",
        verdict_version=1,
        decided=decided,
        rule=rules.get(decided.rule_ids[0]),
        effective=step.effective,
        table_id=None,
        table_version=None,
        kb_version="t",
        diagnosis_started_at=now,
        confirmed_at=now,
        as_of=AS_OF,
    )
    assert h.assumptions == result.assumptions
    # 함량 시험값을 주면 함량은 추정이 아니므로 함량 안내는 빠진다(용출 농도 추정 안내만 남음)
    label = real_kb.catalog["pcb_mg_l"].label
    assert any(a.startswith(label) for a in result.assumptions)
    row = _oil_row("06-01-07", pcb_possible=False, pcb_mg_l=0.5)
    step = run_engine(real_kb, row_store(real_kb, BASE, row), SessionState(), AS_OF)
    assert not any(a.startswith(label) for a in build_result(step, rules, real_kb).assumptions)
