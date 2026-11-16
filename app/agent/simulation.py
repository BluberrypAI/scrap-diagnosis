"""스크립트된 답변으로 문진을 끝까지 돌리는 시뮬레이터 (LLM 없음).

시나리오 형식(YAML)
    id: SIM-001
    as_of: 2026-11-08
    max_questions: 40             # 생략하면 엔진 기본값(DEFAULT_MAX_QUESTIONS)
    setup:                        # 문진 전에 알고 있는 사실 (기업 프로필·건 메모)
      facts: {material: PP}
      evidenced: {oil_content_pct: 3}
      code_claim: SAMPLE-A
    answers:                      # 질문 키 → 답. 사실: 값 | unknown. 묶음: none | expand
      form: FILM
      contamination_screen: none
      oil_content_pct: unknown
    documents:                    # 증빙 요청 시 제출할 문서 → 문서에서 확인되는 값
      TEST_REPORT: {oil_content_pct: 2.1}
    expect: {branch: FINAL_REVIEW, code: SAMPLE-A, questions: 3}
문서가 없으면 증빙 거부로 처리한다. 답이 없는 질문은 '모름'으로 답한다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel

from app.agent.router import DEFAULT_MAX_QUESTIONS, Branch, SessionState, run_engine
from app.domain.facts import FactStatus, FactStore
from app.rules.answers import fact_answer, group_none_answer
from app.rules.model import KnowledgeBase

MAX_STEPS = 60


class TurnLog(BaseModel):
    turn: int
    branch: str
    question: str | None = None
    unit: str | None = None
    answer: Any = None
    candidates: list[str]
    decided: str | None = None
    reason: str
    score_top: list[tuple[str, float]] = []


class SimulationResult(BaseModel):
    scenario_id: str
    turns: list[TurnLog]
    final_branch: str
    final_code: str | None
    questions_asked: int
    failure_reason: str | None = None
    final_outcome: str | None = None  # 코드 없는 결론의 사유(FINAL_REVIEW, 코드 없음)


def simulate(kb: KnowledgeBase, scenario: dict) -> SimulationResult:
    as_of = scenario.get("as_of") or date.today()
    if isinstance(as_of, str):
        as_of = date.fromisoformat(as_of)
    max_q = int(scenario.get("max_questions", DEFAULT_MAX_QUESTIONS))
    setup = scenario.get("setup") or {}
    answers: dict[str, Any] = dict(scenario.get("answers") or {})
    documents: dict[str, dict] = scenario.get("documents") or {}

    store = FactStore()
    for k, v in (setup.get("facts") or {}).items():
        store.append(fact_answer(kb, k, v, source_type="PROFILE", source_ref="setup"))
    for k, v in (setup.get("evidenced") or {}).items():
        store.append(
            fact_answer(
                kb, k, v, source_type="DOCUMENT", source_ref="setup", status=FactStatus.EVIDENCED
            )
        )
    state = SessionState()
    if setup.get("code_claim"):
        state.focus_codes.add(setup["code_claim"])

    turns: list[TurnLog] = []
    step = None
    for i in range(MAX_STEPS):
        step = run_engine(kb, store, state, as_of, max_questions=max_q)
        d = step.decision
        ev = step.evaluation
        log = TurnLog(
            turn=i + 1,
            branch=d.branch.value,
            reason=d.reason,
            candidates=[str(c.code) for c in ev.live_candidates],
            decided=ev.decided.code if ev.decided else None,
        )
        if d.branch == Branch.ASK_FACT and d.question is not None:
            q = d.question
            log.question, log.unit = q.key, q.unit
            log.score_top = [(e.key, e.score) for e in q.score_breakdown[:3]]
            state.questions_asked += 1
            ans = answers.get(q.key, "unknown")
            log.answer = ans
            ref = f"sim-{i + 1}"
            if q.unit == "group":
                if ans == "none":
                    store.extend(group_none_answer(kb, q.key, q.facts, source_ref=ref))
                else:
                    state.expanded_groups.add(q.key)
            elif ans == "unknown":
                store.append(fact_answer(kb, q.key, None, unknown=True, source_ref=ref))
            else:
                store.append(fact_answer(kb, q.key, ans, source_ref=ref))
            turns.append(log)
            continue
        if d.branch == Branch.REQUEST_EVIDENCE:
            provided = False
            for doc in d.requested_documents:
                values = documents.pop(doc.evidence_type, None)
                if values:
                    provided = True
                    for k, v in values.items():
                        store.append(
                            fact_answer(
                                kb,
                                k,
                                v,
                                source_type="DOCUMENT",
                                source_ref=doc.evidence_type,
                                status=FactStatus.EVIDENCED,
                            )
                        )
            log.answer = "documents" if provided else "refused"
            if not provided:
                state.evidence_refused = True
            turns.append(log)
            continue
        turns.append(log)
        break
    assert step is not None
    ev = step.evaluation
    return SimulationResult(
        scenario_id=str(scenario.get("id", "scenario")),
        turns=turns,
        final_branch=step.decision.branch.value,
        final_code=ev.decided.code if ev.decided else None,
        questions_asked=state.questions_asked,
        failure_reason=step.decision.failure_reason,
        final_outcome=ev.decided.outcome if ev.decided and ev.decided.code is None else None,
    )
