"""문진 한 턴의 응답 스키마(docs/engine/algorithm.md 7절).

화면용 보강 필드는 docs/ui/ui-contract.md(ui-v1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.agent import templates
from app.agent.router import Branch, EngineStep, blocking_view
from app.domain.clock import seoul_iso
from app.domain.facts import Fact, FactStatus, document_id_of
from app.domain.ranges import NumRange
from app.rules.evaluator import TV
from app.rules.model import Cond, FactDef, KnowledgeBase, Rule, iter_conds
from app.rules.selector import QuestionChoice

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


# ---- 화면용 보강 필드 (ui-v1) ----------------------------------------------------------

InputKind = Literal["choice", "group", "material_group", "material", "number", "code"]
ValueType = Literal["enum", "bool", "number"]


class _DictAccess:
    """예전 코드가 `ui.question["key"]`처럼 dict로 읽던 것을 그대로 받기 위한 접근자."""

    def __getitem__(self, name: str) -> Any:
        try:
            return getattr(self, name)
        except AttributeError as exc:
            raise KeyError(name) from exc

    def get(self, name: str, default: Any = None) -> Any:
        return getattr(self, name, default)


class OptionView(BaseModel):
    """선택지 버튼. value는 사실 값(enum 문자열·bool·NumRange dict) 또는 묶음 답."""

    label: str
    value: Any = None
    kind: Literal["value", "unknown", "none_all", "expand"] = "value"


class QuestionItem(BaseModel):
    key: str
    label: str


class AnsweredItem(QuestionItem):
    value_label: str | None = None


class TermView(BaseModel):
    """질문 글에 나온 전문용어의 쉬운 설명(knowledge/glossary.yaml, 사람이 쓴 고정 설명)."""

    term: str
    plain: str
    example: str | None = None


class QuestionView(_DictAccess, BaseModel):
    """지금 질문 카드(1.1절). key·unit·facts·options는 M4부터 있던 필드다."""

    key: str
    unit: Literal["fact", "group"]
    facts: list[str] = []
    options: list[OptionView] = []
    text: str | None = None  # 카드 제목(결정적). 응답 message는 LLM이 다듬은 말
    help: str | None = None
    input: InputKind | None = None
    value_type: ValueType | None = None  # group이면 null
    allow_unknown: bool = False
    allow_free_number: bool = False
    items: list[QuestionItem] = []  # group: 이번에 묻는 항목
    answered_items: list[AnsweredItem] = []  # group: 같은 묶음에서 이미 답한 항목
    terms: list[TermView] = []  # 질문 글(제목·도움말·선택지·항목)에 나온 용어 설명


class EditView(BaseModel):
    """보드에서 사실을 고칠 때의 입력 형식."""

    input: Literal["choice", "number"]
    value_type: ValueType
    unit: str | None = None
    options: list[OptionView] = []  # enum: 카탈로그 전체, bool: 예/아니오, number: 비움(직접 입력)


class BoardFact(BaseModel):
    key: str
    label: str
    value: Any
    value_label: str | None
    status: str
    source_type: str
    source_label: str
    document_id: str | None = None  # 출처가 DOCUMENT면 문서 id(문서 링크)
    quote: str | None = None
    recorded_at: str | None = None  # ISO 8601, Asia/Seoul
    editable: bool
    edit: EditView | None = None  # editable일 때만


class PendingItem(BaseModel):
    key: str
    label: str
    reason: Literal["MISSING", "NEEDS_EVIDENCE", "DECLARED_UNKNOWN"]


class Progress(BaseModel):
    questions_asked: int
    max_questions: int


class TopCandidate(BaseModel):
    code: str | None
    name: str | None = None
    outcome: str | None = None


class DocumentNeeded(BaseModel):
    evidence_type: str
    label: str
    facts: list[str]
    fact_labels: list[str]


class Board(BaseModel):
    """판정 보드(1.2절)."""

    facts: list[BoardFact] = []
    pending: list[PendingItem] = []
    progress: Progress
    candidates_count: int = 0
    top_candidates: list[TopCandidate] = []
    documents_needed: list[DocumentNeeded] = []


class ConflictChoice(BaseModel):
    label: str
    quick_reply: dict | None = None  # 이 버튼이 보낼 quick_reply
    action: Literal["UPLOAD", "EDIT_FACT"] | None = None  # 화면 동작
    key: str | None = None  # EDIT_FACT: 고칠 사실


class ConflictView(BaseModel):
    """충돌 카드(1.3절)."""

    kind: Literal["CLAIM_VS_EVIDENCE", "NO_CANDIDATE"]
    fact: str | None
    facts: list[str]
    label: str | None
    fact_labels: list[str] = []
    claimed: Any = None
    claimed_label: str | None = None
    evidenced: Any = None
    evidenced_label: str | None = None
    document_id: str | None = None
    message: str
    choices: list[ConflictChoice]


class ResultView(BaseModel):
    """결과 카드(1.4절). FINAL_REVIEW일 때만."""

    result_type: Literal["WASTE_CODE", "NO_CODE"]
    code: str | None
    name: str | None
    category: str | None
    category_label: str | None = None
    outcome: str | None
    conclusion: str
    next_step: str
    review: str
    # 시험·서류가 아니라 사용자 답에서 추정한 사실의 안내(예: PCB 관련 없음 → 기준 미만 추정)
    assumptions: list[str] = []
    # 코드 없는 결론의 이유 한 줄(규칙 설명). 분류번호가 있으면 null
    reason: str | None = None


class UI(BaseModel):
    can_confirm: bool
    suggested_replies: list[str] = []
    requested_documents: list[dict] = []
    question: QuestionView | None = None  # 지금 질문 카드(ASK_FACT일 때)
    board: Board | None = None  # 판정 보드(모든 턴)
    conflicts: list[ConflictView] = []  # RESOLVE_CONFLICT일 때
    result: ResultView | None = None  # FINAL_REVIEW일 때


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


# ---- 화면용 보강 필드 만들기 ----------------------------------------------------------


def fact_label(kb: KnowledgeBase, key: str) -> str:
    fd = kb.catalog.get(key)
    return (fd.label or fd.question_hint or key) if fd else key


def value_label(kb: KnowledgeBase, key: str, value: Any) -> str | None:
    """사실 값의 화면 라벨: enum은 카탈로그 라벨, bool은 예/아니오, 수치는 단위를 붙인다."""
    if value is None:
        return None
    fd = kb.catalog.get(key)
    unit = fd.unit if fd else None
    if isinstance(value, dict) and value and set(value) <= {"lo", "lo_inc", "hi", "hi_inc"}:
        value = NumRange(**value)
    if isinstance(value, NumRange):
        return value.label(unit)
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if fd is not None and fd.type == "enum":
        return fd.value_labels.get(str(value), str(value))
    if isinstance(value, int | float):
        return f"{value:g}{unit or ''}"
    return str(value)


def parent_keys(kb: KnowledgeBase) -> set[str]:
    """다른 사실의 상위 분류인 사실 키(예: material_group)."""
    return {fd.parent for fd in kb.catalog.values() if fd.parent}


def is_code_fact(kb: KnowledgeBase, fd: FactDef) -> bool:
    """별표 4 번호를 고르는 사실(값이 모두 코드표에 있음)."""
    return fd.type == "enum" and bool(fd.values) and set(fd.values) <= set(kb.codes)


def input_kind(kb: KnowledgeBase, unit: str, key: str) -> InputKind:
    """질문 카드 종류. 상위 분류 → material_group, parent가 있는 사실 → material."""
    if unit == "group":
        return "group"
    fd = kb.catalog[key]
    if key in parent_keys(kb):
        return "material_group"
    if fd.parent:
        return "material"
    if fd.type == "number":
        return "number"
    if is_code_fact(kb, fd):
        return "code"
    return "choice"


def question_view(kb: KnowledgeBase, q: QuestionChoice, effective: dict[str, Fact]) -> QuestionView:
    options = [OptionView.model_validate(o.model_dump()) for o in q.value_options]
    kind = input_kind(kb, q.unit, q.key)
    items: list[QuestionItem] = []
    answered: list[AnsweredItem] = []
    value_type = None
    if q.unit == "group":
        g = kb.group(q.key)
        items = [QuestionItem(key=k, label=fact_label(kb, k)) for k in q.facts]
        for k in g.facts if g else ():
            f = effective.get(k)
            if k in q.facts or f is None or not f.is_known:
                continue
            answered.append(
                AnsweredItem(
                    key=k, label=fact_label(kb, k), value_label=value_label(kb, k, f.value)
                )
            )
    else:
        value_type = kb.catalog[q.key].type
    from app.rules.glossary import find_terms  # 순환 import 방지

    found = find_terms(
        kb.glossary,
        q.question_hint,
        q.help,
        *(o.label for o in options),
        *(i.label for i in items),
    )
    terms = [TermView(term=e.term, plain=e.plain, example=e.example) for e in found]
    return QuestionView(
        key=q.key,
        unit=q.unit,
        facts=list(q.facts),
        options=options,
        text=q.question_hint,
        help=q.help,
        input=kind,
        value_type=value_type,
        allow_unknown=any(o.kind == "unknown" for o in options),
        allow_free_number=kind == "number",
        items=items,
        answered_items=answered,
        terms=terms,
    )


# 서류 값은 서류로만, 자동으로 정한 값은 원래 사실을 고쳐서 바꾼다.
NOT_EDITABLE_SOURCES = frozenset({"DOCUMENT", "DERIVED"})


def edit_view(fd: FactDef) -> EditView:
    if fd.type == "enum":
        opts = [OptionView(label=fd.value_labels.get(v, v), value=v) for v in fd.values or ()]
        return EditView(input="choice", value_type="enum", unit=fd.unit, options=opts)
    if fd.type == "bool":
        opts = [OptionView(label="예", value=True), OptionView(label="아니오", value=False)]
        return EditView(input="choice", value_type="bool", unit=fd.unit, options=opts)
    return EditView(input="number", value_type="number", unit=fd.unit)


def is_editable(kb: KnowledgeBase, f: Fact) -> bool:
    return (
        f.key in kb.catalog
        and f.source_type not in NOT_EDITABLE_SOURCES
        and f.status != FactStatus.EVIDENCED
    )


def board_fact(kb: KnowledgeBase, f: Fact) -> BoardFact:
    editable = is_editable(kb, f)
    return BoardFact(
        key=f.key,
        label=fact_label(kb, f.key),
        value=f.model_dump(mode="json")["value"],
        value_label=value_label(kb, f.key, f.value),
        status=f.status.value,
        source_type=f.source_type,
        source_label=templates.SOURCE_LABEL.get(f.source_type, f.source_type),
        document_id=(document_id_of(f.source_ref) or None) if f.source_type == "DOCUMENT" else None,
        quote=f.quote,
        recorded_at=seoul_iso(f.recorded_at) if isinstance(f.recorded_at, datetime) else None,
        editable=editable,
        edit=edit_view(kb.catalog[f.key]) if editable else None,
    )


def documents_needed(kb: KnowledgeBase, step: EngineStep) -> list[DocumentNeeded]:
    """증빙이 있어야 확정할 수 있는 사실을 서류별로 묶는다(REQUEST_EVIDENCE가 아니어도)."""
    d = step.decision
    if d.requested_documents:
        groups = [(r.evidence_type, list(r.facts)) for r in d.requested_documents]
    else:
        docs: dict[str, set[str]] = {}
        for u in blocking_view(kb, step.evaluation, step.effective).evidence:
            docs.setdefault(u.evidence_type or "DOCUMENT", set()).add(u.key)
        groups = [(k, sorted(v)) for k, v in sorted(docs.items())]
    return [
        DocumentNeeded(
            evidence_type=t,
            label=templates.evidence_label(t),
            facts=keys,
            fact_labels=[fact_label(kb, k) for k in keys],
        )
        for t, keys in groups
    ]


def build_board(
    kb: KnowledgeBase, step: EngineStep, *, questions_asked: int, max_questions: int
) -> Board:
    ev = step.evaluation
    return Board(
        facts=[board_fact(kb, f) for _, f in sorted(step.effective.items()) if f.is_known],
        pending=[
            PendingItem(key=u.key, label=fact_label(kb, u.key), reason=u.reason)
            for u in ev.blocking_facts
        ],
        progress=Progress(questions_asked=questions_asked, max_questions=max_questions),
        candidates_count=len(ev.live_candidates),
        top_candidates=[
            TopCandidate(code=c.code, name=c.name, outcome=c.outcome)
            for c in ev.live_candidates[:5]
        ],
        documents_needed=documents_needed(kb, step),
    )


def _claim_conflict(kb: KnowledgeBase, step: EngineStep, c: Any) -> ConflictView:
    key = c.facts[0]
    label = fact_label(kb, key)
    ef = step.effective.get(key)
    doc = document_id_of(ef.source_ref) if ef is not None and ef.source_type == "DOCUMENT" else None
    ev_label = value_label(kb, key, c.evidenced)
    return ConflictView(
        kind=c.kind,
        fact=key,
        facts=list(c.facts),
        label=label,
        fact_labels=[label],
        claimed=c.claimed,
        claimed_label=value_label(kb, key, c.claimed),
        evidenced=c.evidenced,
        evidenced_label=ev_label,
        document_id=doc or None,
        message=c.message,
        choices=[
            ConflictChoice(
                label=templates.CONFLICT_ACCEPT_DOCUMENT.format(value=ev_label),
                quick_reply={"key": key, "kind": "value", "value": c.evidenced},
            ),
            ConflictChoice(label=templates.CONFLICT_UPLOAD_NEW, action="UPLOAD"),
        ],
    )


def build_conflicts(kb: KnowledgeBase, step: EngineStep) -> list[ConflictView]:
    out = []
    for c in step.decision.conflicts:
        if c.kind == "CLAIM_VS_EVIDENCE" and c.facts:
            out.append(_claim_conflict(kb, step, c))
            continue
        labels = [fact_label(kb, k) for k in c.facts]
        out.append(
            ConflictView(
                kind=c.kind,
                fact=c.facts[0] if c.facts else None,
                facts=list(c.facts),
                label=labels[0] if labels else None,
                fact_labels=labels,
                message=c.message,
                choices=[
                    ConflictChoice(
                        label=templates.CONFLICT_EDIT_FACT.format(label=lb),
                        action="EDIT_FACT",
                        key=k,
                    )
                    for k, lb in zip(c.facts, labels, strict=True)
                ],
            )
        )
    return out


def build_result(
    step: EngineStep, rule_index: dict[str, Rule], kb: KnowledgeBase | None = None
) -> ResultView | None:
    d, ev = step.decision, step.evaluation
    if d.branch != Branch.FINAL_REVIEW or ev.decided is None:
        return None
    c = ev.decided
    rule = rule_index.get(c.rule_ids[0])
    review = (rule.review if rule else None) or "UNVERIFIED"
    from app.rules.implications import assumption_notes  # 순환 import 방지

    common = dict(
        category=c.category,
        category_label=templates.CATEGORY_LABEL.get(c.category or ""),
        review=review,
        assumptions=assumption_notes(kb, step.effective) if kb is not None else [],
    )
    if c.code is not None:
        return ResultView(
            result_type="WASTE_CODE",
            code=c.code,
            name=c.name,
            outcome=None,
            conclusion=templates.code_conclusion(c.code, c.name, c.category),
            next_step=templates.WASTE_CODE_NEXT_STEP,
            **common,
        )
    return ResultView(
        result_type="NO_CODE",
        code=None,
        name=None,
        outcome=c.outcome,
        conclusion=templates.OUTCOME_TEXT.get(c.outcome or "", ""),
        next_step=templates.no_code_next_step(_guidance_action(kb, c.outcome)),
        reason=templates.outcome_reason(c.name),
        **common,
    )


def _guidance_action(kb: KnowledgeBase | None, outcome: str | None) -> str | None:
    """확정하면 이어질 경로추천 안내의 행동(outcome_guidance.yaml의 action). 없으면 None."""
    if kb is None:
        return None
    try:
        return kb.guidance_for("NO_CODE", outcome).action
    except KeyError:
        return None


def build_ui(
    kb: KnowledgeBase,
    step: EngineStep,
    rule_index: dict[str, Rule],
    *,
    suggested_replies: list[str],
    questions_asked: int,
    max_questions: int,
) -> UI:
    """한 턴의 UI 필드 전체. questions_asked는 이번 질문까지 센 값이다."""
    d = step.decision
    q = d.question
    return UI(
        can_confirm=step.evaluation.can_confirm and d.branch == Branch.FINAL_REVIEW,
        suggested_replies=suggested_replies,
        requested_documents=[r.model_dump() for r in d.requested_documents],
        question=None if q is None else question_view(kb, q, step.effective),
        board=build_board(kb, step, questions_asked=questions_asked, max_questions=max_questions),
        conflicts=build_conflicts(kb, step) if d.branch == Branch.RESOLVE_CONFLICT else [],
        result=build_result(step, rule_index, kb),
    )
