"""docs/engine/algorithm.md 1절·5.4절의 PP 예시가 실제 엔진 결과와 같은지 확인한다.

규칙 데이터나 질문 선택 로직을 바꿔 이 테스트가 깨지면 문서의 예시 숫자도 함께 고친다.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.agent.router import Branch, SessionState, run_engine
from app.domain.facts import FactStore
from app.rules.answers import fact_answer, group_none_answer

AS_OF = date(2026, 11, 9)
ANSWERS = {"material_group": "plastic", "material": "pp", "physical_state": "solid"}


def test_pp_walkthrough_matches_doc(real_kb):
    store = FactStore()
    store.append(fact_answer(real_kb, "emission_facility", True, source_type="PROFILE"))
    state = SessionState()
    asked, live, gains = [], [], {}
    for _ in range(10):
        step = run_engine(real_kb, store, state, AS_OF)
        live.append(len(step.evaluation.live_candidates))
        q = step.decision.question
        if q is None:
            break
        asked.append(q.key)
        gains[q.key] = q.score_breakdown[0]
        if q.unit == "group":
            store.extend(group_none_answer(real_kb, q.key, q.facts))
        else:
            store.append(fact_answer(real_kb, q.key, ANSWERS[q.key]))
        state.questions_asked += 1

    assert asked == [
        "material_group",
        "material",
        "contamination_screen",
        "scope_screen",
        "physical_state",
    ]
    assert live == [243, 243, 21, 5, 2, 1]
    assert step.decision.branch == Branch.FINAL_REVIEW
    assert step.evaluation.decided.code == "51-03-01"

    # 5.4절 표: 묶음 질문 gain 0.972, score 2.917
    e = gains["contamination_screen"]
    assert e.gain == pytest.approx(0.972, abs=1e-3)
    assert e.score == pytest.approx(2.917, abs=1e-3)
    assert e.outcomes == {"모두 해당 없음": 5, "해당하는 게 있어요 / 잘 모르겠어요": 21}
