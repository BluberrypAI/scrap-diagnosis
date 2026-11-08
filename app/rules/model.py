"""규칙 데이터 모델: 사실 카탈로그, 조건식, 규칙 테이블, 질문 묶음, 코드표.

규칙은 코드가 아니라 데이터(YAML)다. 이 모듈은 로더가 검증을 끝낸 불변 객체만 정의한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from app.domain.facts import FactStatus

FactType = Literal["number", "enum", "bool"]
HitPolicy = Literal["UNIQUE", "PRIORITY", "COLLECT"]

OPS = ("eq", "ne", "in", "not_in", "lt", "lte", "gt", "gte", "exists")
NUMERIC_OPS = frozenset({"lt", "lte", "gt", "gte"})
LIST_OPS = frozenset({"in", "not_in"})


@dataclass(frozen=True)
class FactDef:
    key: str
    type: FactType
    question_hint: str
    label: str | None = None
    unit: str | None = None
    values: tuple[str, ...] | None = None  # enum 값 영역
    value_labels: dict[str, str] = field(default_factory=dict)
    ask_cost: float = 1.0
    evidence_cost: float | None = None
    evidence_type: str | None = None
    legal_priority: float = 1.0
    prior: dict[str, float] = field(default_factory=dict)  # 값(문자열화) → 사전확률. 비우면 균등
    help: str | None = None
    none_value: Any = None  # 묶음 질문 '모두 해당 없음'에서 넣을 값


# ---- 조건식 -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Cond:
    fact: str
    op: str
    value: Any = None
    min_status: FactStatus = FactStatus.CLAIMED


@dataclass(frozen=True)
class All:
    items: tuple[Expr, ...]


@dataclass(frozen=True)
class AnyOf:
    items: tuple[Expr, ...]


@dataclass(frozen=True)
class Not:
    item: Expr


Expr = Cond | All | AnyOf | Not


def iter_conds(expr: Expr):
    if isinstance(expr, Cond):
        yield expr
    elif isinstance(expr, All | AnyOf):
        for it in expr.items:
            yield from iter_conds(it)
    elif isinstance(expr, Not):
        yield from iter_conds(expr.item)


# ---- 규칙·테이블 ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Basis:
    type: str  # LAW | QA | GUIDE ...
    ref: str
    excerpt: str | None = None
    source_id: str | None = None


@dataclass(frozen=True)
class Outcome:
    code: str | None
    category: str | None = None  # GENERAL | DESIGNATED | HOUSEHOLD | ...
    name: str | None = None


@dataclass(frozen=True)
class Rule:
    rule_id: str
    when: Expr
    then: Outcome
    priority: int = 0
    basis: tuple[Basis, ...] = ()
    review: str | None = None  # 예: UNVERIFIED
    effective_from: date | None = None
    effective_to: date | None = None
    origin: str = ""  # 정의된 파일

    def facts(self) -> set[str]:
        return {c.fact for c in iter_conds(self.when)}


@dataclass(frozen=True)
class Table:
    table_id: str
    version: str
    hit_policy: HitPolicy
    rules: tuple[Rule, ...]
    effective_from: date | None = None
    effective_to: date | None = None
    applies_when: Expr | None = None
    title: str | None = None
    origin: str = ""

    def is_effective(self, as_of: date) -> bool:
        return _in_range(as_of, self.effective_from, self.effective_to)

    def rules_as_of(self, as_of: date) -> tuple[Rule, ...]:
        return tuple(r for r in self.rules if _in_range(as_of, r.effective_from, r.effective_to))


def _in_range(as_of: date, start: date | None, end: date | None) -> bool:
    if start and as_of < start:
        return False
    if end and as_of >= end:
        return False
    return True


# ---- 질문 묶음 -----------------------------------------------------------------------------


@dataclass(frozen=True)
class QuestionGroup:
    group_id: str
    title: str
    facts: tuple[str, ...]
    none_label: str = "모두 해당 없음"
    expand_label: str = "해당하는 게 있어요 / 잘 모르겠어요"
    help: str | None = None
    ask_cost: float = 1.0


# ---- 코드표 ------------------------------------------------------------------------------


@dataclass(frozen=True)
class CodeEntry:
    code: str
    name: str
    category: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    note: str | None = None


# ---- 지식 베이스 ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KnowledgeBase:
    catalog: dict[str, FactDef]
    tables: tuple[Table, ...]
    groups: tuple[QuestionGroup, ...] = ()
    codes: dict[str, CodeEntry] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def tables_as_of(self, as_of: date) -> tuple[Table, ...]:
        return tuple(t for t in self.tables if t.is_effective(as_of))

    def group(self, group_id: str) -> QuestionGroup | None:
        return next((g for g in self.groups if g.group_id == group_id), None)
