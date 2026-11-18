"""지정폐기물 판정 안내(ui.result.designated, handoff.designated).

판정은 규칙 엔진이 하고, 이 모듈은 이미 정해진 결과를 설명만 한다(판정 규칙은 바꾸지 않는다).
이유 문장은 LLM이 아니라 코드가 결정한 규칙의 만족한 조건과 실제 사실 값으로 만든다.
다음 할 일은 데이터 파일(`knowledge/designated_guidance.yaml`)이다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.domain.facts import Fact
from app.domain.ranges import NumRange
from app.rules.evaluator import TV, Candidate, eval_expr
from app.rules.model import (
    All,
    AnyOf,
    Cond,
    DesignatedAction,
    Expr,
    FactDef,
    KnowledgeBase,
    Rule,
)

CATEGORY_DESIGNATED = "DESIGNATED"
WARNING = (
    "지정폐기물은 지정폐기물 처리 허가를 받은 업체에만 맡길 수 있어요. "
    "일반 재활용 업체에는 보낼 수 없어요."
)

# 이유 문장에 쓰지 않는 조건: 소재·번호를 고르는 조건(어느 규칙이든 항상 붙음)
_SKIP_FACTS = frozenset({"material", "annex4_code"})
_OP_WORD = {"lt": "미만", "lte": "이하", "gt": "초과", "gte": "이상"}
_MAX_PARTS = 3


class DesignatedActionOut(BaseModel):
    id: str
    text: str
    source_id: str | None = None
    source_title: str | None = None
    form: str | None = None
    source_ref: str | None = None  # 조항 위치(예: 제18조의2)


class DesignatedGuidance(BaseModel):
    reason: str | None = None
    warning: str = WARNING
    next_actions: list[DesignatedActionOut] = []


def is_designated(decided: Candidate | None) -> bool:
    return decided is not None and decided.category == CATEGORY_DESIGNATED


def _num(x: float) -> str:
    return f"{x:g}"


def _satisfied_leaves(expr: Expr, facts: dict[str, Fact], kb: KnowledgeBase) -> list[Cond]:
    """실제 사실로 참인 조건. any는 참인 가지만, not(제외 조건)은 건너뛴다."""
    if isinstance(expr, Cond):
        return [expr] if eval_expr(expr, facts, kb.catalog) == TV.TRUE else []
    if isinstance(expr, All):
        return [c for it in expr.items for c in _satisfied_leaves(it, facts, kb)]
    if isinstance(expr, AnyOf):
        return [
            c
            for it in expr.items
            if eval_expr(it, facts, kb.catalog) == TV.TRUE
            for c in _satisfied_leaves(it, facts, kb)
        ]
    return []  # Not: '이런 경우는 제외' 조건이라 지정 이유가 아니다


def _actual_text(fd: FactDef, value: Any) -> str | None:
    unit = fd.unit or ""
    if isinstance(value, NumRange):
        return value.label(fd.unit)
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if fd.type == "enum":
        return fd.value_labels.get(str(value), str(value))
    if isinstance(value, int | float):
        return f"{_num(value)}{unit}"
    return None


def _part(kb: KnowledgeBase, c: Cond, facts: dict[str, Fact]) -> tuple[bool, str] | None:
    """(수치 조건인지, 문장 조각). 믿을 수 없으면 None."""
    fd = kb.catalog.get(c.fact)
    f = facts.get(c.fact)
    if fd is None or f is None or not f.is_known:
        return None
    label = fd.label or fd.question_hint
    actual = _actual_text(fd, f.value)
    if actual is None:
        return None
    if c.op in _OP_WORD and isinstance(c.value, int | float) and not isinstance(c.value, bool):
        return True, f"{label} {actual} (기준 {_num(c.value)}{fd.unit or ''} {_OP_WORD[c.op]})"
    if c.op in ("eq", "in"):
        return False, f"{label}: {actual}"
    return None


def designated_reason(kb: KnowledgeBase, rule: Rule | None, facts: dict[str, Fact]) -> str | None:
    """결정한 규칙의 만족한 조건을 사용자의 실제 값과 기준으로 풀어 쓴 한 문장. 못 만들면 None."""
    if rule is None:
        return None
    parts: list[tuple[bool, str]] = []
    for c in _satisfied_leaves(rule.when, facts, kb):
        if c.fact in _SKIP_FACTS:
            continue
        p = _part(kb, c, facts)
        if p is not None and p not in parts:
            parts.append(p)
    # 수치 기준을 앞에 둔다(가장 알기 쉬운 이유)
    parts.sort(key=lambda p: not p[0])
    if not parts:
        return None
    return ", ".join(t for _, t in parts[:_MAX_PARTS])


def _text_for(a: DesignatedAction, code: str | None) -> str:
    """결정된 분류번호의 계열(앞 2자리)에 맞는 문장. 번호가 없거나 맞는 변형이 없으면 기본 문장."""
    family = code[:2] if code else None
    for families, text in a.variants:
        if family in families:
            return text
    return a.text


def build_designated(
    kb: KnowledgeBase, decided: Candidate | None, rule: Rule | None, effective: dict[str, Fact]
) -> DesignatedGuidance | None:
    """결정된 후보가 지정폐기물일 때만 안내를 만든다. 아니면 None."""
    if not is_designated(decided):
        return None
    assert decided is not None
    return DesignatedGuidance(
        reason=designated_reason(kb, rule, effective),
        next_actions=[
            DesignatedActionOut(
                id=a.id,
                text=_text_for(a, decided.code),
                source_id=a.source_id,
                source_title=a.source_title,
                form=a.form,
                source_ref=a.source_ref,
            )
            for a in kb.designated_actions
            if a.only_outcome is None or a.only_outcome == decided.outcome
        ],
    )


def with_warning(message: str, decided: Candidate | None) -> str:
    """지정폐기물 판정 확인 메시지의 끝에 경고 한 문장을 붙인다(이미 있으면 그대로)."""
    if not is_designated(decided) or WARNING in message:
        return message
    return f"{message.rstrip()} {WARNING}"
