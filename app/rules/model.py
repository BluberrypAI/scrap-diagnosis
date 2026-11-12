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
    # referenced: enum 값 영역을 'FALSE가 아닌 규칙의 조건에 나오는 값'으로 한정
    # (예: 별표4 번호 선택)
    domain: str | None = None
    ask_last: bool = False  # 확정을 막는 다른 사실이 남아 있으면 묻지 않음
    auto_single: bool = False  # 남은 선택지가 하나면 자동으로 채움
    internal: bool = False  # LLM이 자유 진술에서 추출하지 않음(직전 질문의 선택지로만 받음)
    value_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # 2단계 질문: 상위 분류 사실 키와 '값 → 상위 분류 값' 대응(예: material → material_group).
    # 상위 분류를 모르면 상위 분류를 먼저 묻고, 알면 이 사실의 선택지를 그 분류의 값으로 줄인다.
    parent: str | None = None
    value_parent: dict[str, str] = field(default_factory=dict)
    # 대리 질문(질문 전략): 이 사실의 값 → 다른 사실의 추정값(algorithm.md 5절).
    # 예: pcb_possible "false" → {pcb_mg_l: {hi: 2}}
    #     ("PCB 관련 없음"이면 PCB 함량 기준 미만으로 본다).
    # 추정값은 저장하지 않고 평가 때마다 적용한다(출처 DERIVED, 명시된 값이 우선).
    implies: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 보수 관계(질문 전략): (대상 사실, 합계). 같은 시험이 함께 내는 두 수치의 합이 일정할 때
    # 한쪽 값으로 다른 쪽을 계산한다(예: 수분함량 + 고형물함량 = 100). 양방향, 명시된 값이 우선.
    complement: tuple[str, float] | None = None


# ---- 조건식 -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Cond:
    fact: str
    op: str
    value: Any = None
    min_status: FactStatus = FactStatus.CLAIMED
    # 값으로 거짓일 때도 이 수준의 증빙이 있어야 거짓으로 본다. 기본 CLAIMED(말로 충분).
    # 확인대상 폐기물(시행규칙 제17조의2)은 '기준 미만'도 분석결과서로 확인해야 해서 EVIDENCED.
    falsify_min_status: FactStatus = FactStatus.CLAIMED


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
    location: str | None = None  # 조문 위치(예: 별표 1 제6호). source_id와 함께 조문 키가 된다


@dataclass(frozen=True)
class Outcome:
    code: str | None
    category: str | None = None  # GENERAL | DESIGNATED | HOUSEHOLD | ...
    name: str | None = None
    # 코드 없는 결론의 사유 (NOT_WASTE, EXCLUDED, HOUSEHOLD, INTERPRETATION_NEEDED ...)
    outcome: str | None = None

    @property
    def key(self) -> str:
        """같은 결론인지 비교하는 키. 코드가 없으면 사유로 구분한다."""
        return self.code if self.code is not None else f"@{self.outcome}"


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
    source_rule: str | None = None  # knowledge/의 원본 규칙 ID(빌드가 넣음, 예: S3-6-OIL-5PCT)

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
    # 묶음 카드에 보이는 항목 문구((사실 키, 문구) 쌍). 없으면 사실의 label을 쓴다
    item_labels: tuple[tuple[str, str], ...] = ()

    def item_label(self, key: str) -> str | None:
        return dict(self.item_labels).get(key)


# ---- 코드표 ------------------------------------------------------------------------------


@dataclass(frozen=True)
class CodeEntry:
    code: str
    name: str
    category: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    note: str | None = None


# ---- 결론 → 경로추천 안내 (docs/handoff-contract.md) ---------------------------------------


@dataclass(frozen=True)
class RouteGuidance:
    """결론 종류(result_type, outcome) 하나의 경로추천 AI 안내(outcome_guidance.yaml 한 항목)."""

    result_type: str  # WASTE_CODE | NO_CODE
    outcome: str | None  # WASTE_CODE면 None
    action: str
    summary: str
    notes: tuple[str, ...] = ()


# ---- 지식 베이스 ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KnowledgeBase:
    catalog: dict[str, FactDef]
    tables: tuple[Table, ...]
    groups: tuple[QuestionGroup, ...] = ()
    codes: dict[str, CodeEntry] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    # (result_type, outcome) → 안내. load_kb는 outcome_guidance.yaml을 반드시 읽는다.
    guidance: dict[tuple[str, str | None], RouteGuidance] = field(default_factory=dict)
    glossary: tuple[Any, ...] = ()  # app.rules.glossary.GlossaryEntry (용어 쉬운 설명, 판정 무관)
    # 문진 설명용(판정 무관, docs/design/agent-skill-harness.md)
    rule_notes: dict[str, dict[str, str]] = field(
        default_factory=dict
    )  # 원본 규칙 ID → 제목·쉬운 설명
    skill_text: str | None = None  # 문진 진행 AI 지침(knowledge/skills/interviewer.md)
    # 질문 안내(knowledge/question_guide.yaml): {"facts": {...}, "topics": {...}, "groups": {...}}
    question_guide: dict[str, Any] = field(default_factory=dict)

    def tables_as_of(self, as_of: date) -> tuple[Table, ...]:
        return tuple(t for t in self.tables if t.is_effective(as_of))

    def group(self, group_id: str) -> QuestionGroup | None:
        return next((g for g in self.groups if g.group_id == group_id), None)

    def guidance_for(self, result_type: str, outcome: str | None) -> RouteGuidance:
        try:
            return self.guidance[(result_type, outcome)]
        except KeyError:
            msg = f"outcome_guidance에 ({result_type}, {outcome}) 항목이 없습니다"
            raise KeyError(msg) from None
