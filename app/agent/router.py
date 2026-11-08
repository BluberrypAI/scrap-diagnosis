"""결정적 분기 라우터 (md 8절).

우선순위 순서대로 첫 번째로 해당하는 분기를 고른다.
1. 사실 충돌 또는 후보 0개 → RESOLVE_CONFLICT (대화 계속)
2. 지원 범위 밖 / 질문 상한 초과 / 남은 미확인이 모두 모름·증빙 거부 → UNSUPPORTED (NEEDS_INFO)
3. 사유가 MISSING인 미확인 사실이 있음 → ASK_FACT (대화 계속)
4. 사유가 NEEDS_EVIDENCE인 미확인 사실만 남음 → REQUEST_EVIDENCE (NEEDS_INFO)
5. decided 있음 → FINAL_REVIEW (사용자 확정 시 CODE_CONFIRMED)
사용자가 질문을 던지면 ANSWER_USER_QUESTION 하위 분기를 붙인다(판정 상태는 바뀌지 않음).
미확인 판단은 확정을 실제로 막는 blocking_facts 기준이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from pydantic import BaseModel

from app.domain.facts import Fact, FactStore
from app.rules.conflicts import Conflict, detect_conflicts
from app.rules.evaluator import EvaluationResult, evaluate
from app.rules.model import KnowledgeBase
from app.rules.selector import QuestionChoice, SelectionContext, select_question

DEFAULT_MAX_QUESTIONS = 12


class Branch(StrEnum):
    RESOLVE_CONFLICT = "RESOLVE_CONFLICT"
    UNSUPPORTED = "UNSUPPORTED"
    ASK_FACT = "ASK_FACT"
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"
    FINAL_REVIEW = "FINAL_REVIEW"


SUB_ANSWER_USER_QUESTION = "ANSWER_USER_QUESTION"


class RequestedDocument(BaseModel):
    evidence_type: str
    facts: list[str]


class RouteDecision(BaseModel):
    branch: Branch
    rank: int  # 표의 순위
    reason: str  # 고른 근거 (Trace)
    sub_branch: str | None = None
    question: QuestionChoice | None = None
    requested_documents: list[RequestedDocument] = []
    conflicts: list[Conflict] = []
    failure_reason: str | None = None
    next_status: str = "DIAGNOSING"


@dataclass
class SessionState:
    """라우터·선택기가 쓰는 세션 상태. 영속화는 M4에서."""

    questions_asked: int = 0
    expanded_groups: set[str] = field(default_factory=set)
    focus_codes: set[str] = field(default_factory=set)
    evidence_refused: bool = False

    def selection_context(self) -> SelectionContext:
        return SelectionContext(
            expanded_groups=frozenset(self.expanded_groups), focus_codes=frozenset(self.focus_codes)
        )


def route(
    kb: KnowledgeBase,
    ev: EvaluationResult,
    facts: dict[str, Fact],
    conflicts: list[Conflict],
    state: SessionState,
    *,
    as_of: date,
    max_questions: int = DEFAULT_MAX_QUESTIONS,
    user_question: str | None = None,
) -> RouteDecision:
    sub = SUB_ANSWER_USER_QUESTION if user_question else None
    decided = ev.decided is not None

    # 1. 충돌 / 후보 0개
    if conflicts:
        kinds = ",".join(sorted({c.kind for c in conflicts}))
        return RouteDecision(
            branch=Branch.RESOLVE_CONFLICT,
            rank=1,
            sub_branch=sub,
            reason=f"충돌 감지: {kinds}",
            conflicts=conflicts,
        )

    # 2. 지원 범위 밖
    unsupported = None
    if ev.table_status == "NONE":
        unsupported = ("NO_TABLE", "적용할 규칙 테이블이 없음")
    elif ev.table_status == "AMBIGUOUS":
        unsupported = ("AMBIGUOUS_TABLE", f"적용 테이블이 여럿: {ev.table_candidates}")
    elif ev.tie:
        unsupported = ("RULE_TIE", f"같은 우선순위 규칙이 서로 다른 코드: {ev.tie}")
    elif not decided:
        missing = [u for u in ev.blocking_facts if u.reason == "MISSING"]
        needs_ev = [u for u in ev.blocking_facts if u.reason == "NEEDS_EVIDENCE"]
        if state.questions_asked >= max_questions and (missing or not needs_ev):
            unsupported = ("QUESTION_LIMIT", f"질문 상한 {max_questions}회 도달")
        elif not missing and (not needs_ev or state.evidence_refused):
            why = "증빙 거부" if needs_ev else "남은 미확인 사실이 모두 '모름'"
            unsupported = ("UNDETERMINABLE", why)
    if unsupported:
        code, why = unsupported
        return RouteDecision(
            branch=Branch.UNSUPPORTED,
            rank=2,
            sub_branch=sub,
            reason=why,
            failure_reason=code,
            next_status="NEEDS_INFO",
        )

    # 3. 물어볼 사실
    if not decided and any(u.reason == "MISSING" for u in ev.blocking_facts):
        q = select_question(kb, facts, ev, as_of, state.selection_context())
        if q is not None:
            return RouteDecision(
                branch=Branch.ASK_FACT,
                rank=3,
                sub_branch=sub,
                question=q,
                reason=f"확정을 막는 미확인 사실 중 '{q.key}' 선택"
                + (" (해소 정도 기준)" if q.fallback else ""),
            )
        # 값 영역을 만들 수 없는 사실만 남음 → 증빙 분기로 넘어간다

    # 4. 증빙 요청
    needs_ev = [u for u in ev.blocking_facts if u.reason == "NEEDS_EVIDENCE"]
    if not decided and needs_ev:
        docs: dict[str, list[str]] = {}
        for u in needs_ev:
            docs.setdefault(u.evidence_type or "DOCUMENT", []).append(u.key)
        return RouteDecision(
            branch=Branch.REQUEST_EVIDENCE,
            rank=4,
            sub_branch=sub,
            reason="증빙이 있어야 확정할 수 있는 사실만 남음",
            requested_documents=[
                RequestedDocument(evidence_type=k, facts=sorted(v)) for k, v in sorted(docs.items())
            ],
            next_status="NEEDS_INFO",
        )

    # 5. 확정 검토
    if decided:
        return RouteDecision(
            branch=Branch.FINAL_REVIEW,
            rank=5,
            sub_branch=sub,
            reason=f"규칙 {ev.decided.rule_ids[0]}로 확정 가능",
        )

    return RouteDecision(
        branch=Branch.UNSUPPORTED,
        rank=2,
        sub_branch=sub,
        reason="진행할 수 있는 분기가 없음",
        failure_reason="NO_PATH",
        next_status="NEEDS_INFO",
    )


@dataclass
class EngineStep:
    evaluation: EvaluationResult
    conflicts: list[Conflict]
    decision: RouteDecision
    effective: dict[str, Fact]


def run_engine(
    kb: KnowledgeBase,
    store: FactStore,
    state: SessionState,
    as_of: date,
    *,
    max_questions: int = DEFAULT_MAX_QUESTIONS,
    user_question: str | None = None,
) -> EngineStep:
    """평가 → 충돌 검사 → 분기 결정. 한 턴의 LLM 없는 부분 (md 10절 3~5단계)."""
    effective = store.effective()
    ev = evaluate(kb, effective, as_of)
    conflicts = detect_conflicts(store.history, ev)
    decision = route(
        kb,
        ev,
        effective,
        conflicts,
        state,
        as_of=as_of,
        max_questions=max_questions,
        user_question=user_question,
    )
    return EngineStep(evaluation=ev, conflicts=conflicts, decision=decision, effective=effective)
