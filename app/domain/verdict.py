"""문진 한 턴의 응답 스키마 (md 10절)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.agent.router import Branch, EngineStep
from app.rules.evaluator import TV
from app.rules.model import Cond, KnowledgeBase, Rule, iter_conds

VerdictStatus = Literal["CONFIRMABLE", "NEEDS_EVIDENCE", "UNDETERMINABLE", "IN_PROGRESS"]

OP_TEXT = {
    "eq": "{v}",
    "ne": "{v} 아님",
    "in": "{v} 중 하나",
    "not_in": "{v} 아님",
    "lt": "{v} 미만",
    "lte": "{v} 이하",
    "gt": "{v} 초과",
    "gte": "{v} 이상",
    "exists": "확인됨",
}


class CandidateView(BaseModel):
    code: str | None
    name: str | None = None
    outcome: str | None = None
    rule_ids: list[str]


class ConditionView(BaseModel):
    fact: str
    text: str
    satisfied: bool | None
    evidence: str | None = None


class RationaleView(BaseModel):
    id: str
    type: str
    ref: str
    excerpt: str | None = None


class Verdict(BaseModel):
    status: VerdictStatus
    waste_code: str | None = None
    waste_name: str | None = None
    category: str | None = None
    # 코드 없는 결론의 사유(NOT_WASTE 등). FINAL_REVIEW에서 waste_code가 null일 때만 채운다.
    outcome: str | None = None
    candidates: list[CandidateView] = []
    conditions: list[ConditionView] = []
    rationale: list[RationaleView] = []
    failure_reason: str | None = None
    review: str | None = None


class UI(BaseModel):
    can_confirm: bool
    suggested_replies: list[str] = []
    requested_documents: list[dict] = []
    question: dict | None = None  # 화면이 버튼을 그릴 때 쓰는 질문 정보(key, unit, options)


class TurnResponse(BaseModel):
    case_id: str
    session_id: str
    turn_id: str
    branch: str
    sub_branch: str | None = None
    message: str
    verdict: Verdict
    ui: UI
    case_status: str


def _value_text(kb: KnowledgeBase, c: Cond) -> str:
    fd = kb.catalog.get(c.fact)
    unit = (fd.unit or "") if fd else ""

    def one(v: Any) -> str:
        if fd and fd.type == "enum":
            return fd.value_labels.get(str(v), str(v))
        if isinstance(v, bool):
            return "예" if v else "아니오"
        return f"{v:g}{unit}" if isinstance(v, int | float) else str(v)

    v = ", ".join(one(x) for x in c.value) if isinstance(c.value, tuple) else one(c.value)
    return OP_TEXT.get(c.op, "{v}").format(v=v)


def condition_views(kb: KnowledgeBase, rule: Rule, step: EngineStep) -> list[ConditionView]:
    rr = next((r for r in step.evaluation.rule_results if r.rule_id == rule.rule_id), None)
    status_of = {}
    if rr is not None:
        for cr in rr.conditions:
            status_of.setdefault(cr.fact, cr.status)
    out = []
    for c in iter_conds(rule.when):
        if c.fact == "material" and c.op == "eq":
            continue  # 테이블 선택 조건(항상 참)은 보여 주지 않음
        fd = kb.catalog.get(c.fact)
        label = (fd.label or fd.question_hint) if fd else c.fact
        st = status_of.get(c.fact)
        sat = None if st in (None, TV.UNKNOWN) else st == TV.TRUE
        ev = (fd.evidence_type if fd else None) if c.min_status.value == "EVIDENCED" else None
        out.append(
            ConditionView(
                fact=c.fact, text=f"{label}: {_value_text(kb, c)}", satisfied=sat, evidence=ev
            )
        )
    return out


def build_verdict(kb: KnowledgeBase, step: EngineStep, rule_index: dict[str, Rule]) -> Verdict:
    d, ev = step.decision, step.evaluation
    status: VerdictStatus = {
        Branch.FINAL_REVIEW: "CONFIRMABLE",
        Branch.REQUEST_EVIDENCE: "NEEDS_EVIDENCE",
        Branch.UNSUPPORTED: "UNDETERMINABLE",
    }.get(d.branch, "IN_PROGRESS")
    cands = [
        CandidateView(code=c.code, name=c.name, outcome=c.outcome, rule_ids=c.rule_ids)
        for c in ev.live_candidates[:20]
    ]
    v = Verdict(status=status, candidates=cands, failure_reason=d.failure_reason)
    focus = ev.decided
    if focus is None and ev.live_candidates:
        focus = ev.live_candidates[0]
    if focus is not None:
        rule = rule_index.get(focus.rule_ids[0])
        if rule is not None:
            v.conditions = condition_views(kb, rule, step)
            if ev.decided is not None:
                v.rationale = [
                    RationaleView(id=f"B{i}", type=b.type, ref=b.ref, excerpt=b.excerpt)
                    for i, b in enumerate(rule.basis, start=1)
                ]
                v.review = rule.review
    if d.branch == Branch.FINAL_REVIEW and ev.decided is not None:
        v.waste_code, v.waste_name, v.category = (
            ev.decided.code,
            ev.decided.name if ev.decided.code is not None else None,
            ev.decided.category,
        )
        if ev.decided.code is None:
            v.outcome = ev.decided.outcome
    return v
