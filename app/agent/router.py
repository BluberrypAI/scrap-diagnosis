"""결정적 분기 라우터 (docs/engine/algorithm.md 6절).

우선순위 순서대로 첫 번째로 해당하는 분기를 고른다.
1. 사실 충돌 또는 후보 0개 → RESOLVE_CONFLICT (대화 계속)
2. 지원 범위 밖 / 질문 상한 초과 / 남은 미확인이 모두 모름·증빙 거부 → UNSUPPORTED (NEEDS_INFO)
   (결론이 나지 않은 경우만. 확정할 수 없다)
3. 사유가 MISSING인 미확인 사실이 있음 → ASK_FACT (대화 계속)
4. 사유가 NEEDS_EVIDENCE인 미확인 사실만 남음 → REQUEST_EVIDENCE (NEEDS_INFO)
5. decided 있음 → FINAL_REVIEW (사용자 확정 시 CODE_CONFIRMED). 코드 없는 결론(outcome)도 포함
사용자가 질문을 던지면 ANSWER_USER_QUESTION 하위 분기를 붙인다(판정 상태는 바뀌지 않음).
미확인 판단은 확정을 실제로 막는 blocking_facts 기준이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from pydantic import BaseModel

from app.domain.facts import Fact, FactStatus, FactStore
from app.rules.conflicts import Conflict, detect_conflicts
from app.rules.evaluator import EvaluationResult, UnknownFact, evaluate
from app.rules.implications import apply_implications
from app.rules.model import KnowledgeBase
from app.rules.selector import (
    QuestionChoice,
    SelectionContext,
    implied_child,
    referenced_values,
    select_question,
)

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


def deferred_evidence_types(kb: KnowledgeBase, facts: dict[str, Fact]) -> set[str]:
    """사용자가 '모름'이라 답한 사실의 증빙 종류. 같은 증빙으로 확인할 다른 사실은 묻지 않는다.

    예: 납 용출 농도를 모른다 → 다른 용출 항목도 같은 시험성적서에서 나오므로 하나씩 묻지 않고
    성적서를 한 번에 요청한다.
    """
    out = set()
    for k, f in facts.items():
        fd = kb.catalog.get(k)
        if f.status == FactStatus.DECLARED_UNKNOWN and fd is not None and fd.evidence_type:
            out.add(fd.evidence_type)
    return out


@dataclass
class BlockingView:
    askable: list[UnknownFact]  # 지금 물을 수 있는 사실
    evidence: list[UnknownFact]  # 증빙으로 받을 사실
    deferred_keys: set[str]  # 증빙으로 미룬 MISSING 사실


def blocking_view(kb: KnowledgeBase, ev: EvaluationResult, facts: dict[str, Fact]) -> BlockingView:
    """확정을 막는 사실을 '물을 것 / 증빙으로 받을 것'으로 나눈다.

    - ask_last 사실(별표4 번호 선택)은 다른 막는 사실이 없을 때만 묻는다.
    - 이미 '모름'이라 답한 증빙 종류의 사실은 묻지 않고 증빙으로 받는다.
    """
    deferred_types = deferred_evidence_types(kb, facts)
    missing = [u for u in ev.blocking_facts if u.reason == "MISSING"]
    deferred = [u for u in missing if u.evidence_type and u.evidence_type in deferred_types]
    deferred_keys = {u.key for u in deferred}
    missing = [u for u in missing if u.key not in deferred_keys]
    others = [u for u in ev.blocking_facts if not kb.catalog[u.key].ask_last]
    if others:
        missing = [u for u in missing if not kb.catalog[u.key].ask_last]
    evidence = [u for u in ev.blocking_facts if u.reason == "NEEDS_EVIDENCE"] + deferred
    return BlockingView(askable=missing, evidence=evidence, deferred_keys=deferred_keys)


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
    view = blocking_view(kb, ev, facts)

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
        missing = view.askable
        needs_ev = view.evidence
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
    if not decided and view.askable:
        ctx = state.selection_context()
        ctx = SelectionContext(
            expanded_groups=ctx.expanded_groups,
            focus_codes=ctx.focus_codes,
            exclude_keys=frozenset(view.deferred_keys),
        )
        q = select_question(kb, facts, ev, as_of, ctx)
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
    needs_ev = view.evidence
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

    # 5. 확정 검토. 코드 없는 결론(폐기물 아님·적용 제외·해석 필요 등)도 규칙 엔진이 낸 결론이라
    #    확정할 수 있다(result_type NO_CODE, docs/handoff-contract.md).
    if decided:
        c = ev.decided
        what = c.code if c.code is not None else f"코드 없는 결론 {c.outcome}"
        return RouteDecision(
            branch=Branch.FINAL_REVIEW,
            rank=5,
            sub_branch=sub,
            reason=f"규칙 {c.rule_ids[0]}로 확정 가능({what})",
        )

    return RouteDecision(
        branch=Branch.UNSUPPORTED,
        rank=2,
        sub_branch=sub,
        reason="진행할 수 있는 분기가 없음",
        failure_reason="NO_PATH",
        next_status="NEEDS_INFO",
    )


def auto_fill(
    kb: KnowledgeBase,
    ev: EvaluationResult,
    as_of: date,
    facts: dict[str, Fact] | None = None,
) -> Fact | None:
    """남은 선택지가 하나뿐인 사실을 채운다. 출처는 DERIVED로 남긴다.

    - 상위 분류에 속한 세부 값이 하나뿐이면 그 값(예: 소재 분류 → 소재). facts가 있을 때만.
    - auto_single 사실만 확정을 막고 있고 남은 선택지가 하나면 그 값.
      기존 엔진의 '번호 후보가 하나면 그대로 정함'과 같다.
    """
    if ev.decided is not None or not ev.blocking_facts:
        return None
    if facts is not None:
        implied = implied_child(kb, facts, ev)
        if implied is not None:
            return implied
    if any(not kb.catalog[u.key].auto_single for u in ev.blocking_facts):
        return None
    if len(ev.blocking_facts) != 1:
        return None
    (u,) = ev.blocking_facts
    if u.reason != "MISSING":
        return None
    values = referenced_values(kb, ev, u.key)
    if len(values) != 1:
        return None
    return Fact(
        key=u.key,
        value=values[0],
        status=FactStatus.CLAIMED,
        source_type="DERIVED",
        source_ref="auto_single",
        note="남은 선택지가 하나라 자동으로 정함",
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
    """평가 → 자동 채움 → 충돌 검사 → 분기 결정.

    한 턴의 LLM 없는 부분(docs/engine/algorithm.md 7절 4단계).
    """
    # 대리 질문의 추정(implies)도 유효 사실에 보인다(판정 보드·Trace). evaluate도 같은 추정을 쓴다.
    effective = apply_implications(kb, store.effective())
    ev = evaluate(kb, effective, as_of)
    for _ in range(3):
        filled = auto_fill(kb, ev, as_of, effective)
        if filled is None:
            break
        store.append(filled)
        effective = apply_implications(kb, store.effective())
        ev = evaluate(kb, effective, as_of)
    conflicts = detect_conflicts(store.history, ev, kb)
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
