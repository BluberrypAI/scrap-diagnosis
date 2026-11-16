"""3값(Kleene) 규칙 평가기. LLM 의존성 없음, 결정적.

조건 평가 (docs/engine/algorithm.md 4.1~4.2절)
- 유효 사실이 없거나 상태가 UNKNOWN/DECLARED_UNKNOWN이면 → UNKNOWN
- 값으로는 만족하지만 상태가 min_status보다 낮으면 → UNKNOWN, 사유 NEEDS_EVIDENCE
- 값으로 거짓이면 → FALSE (지운 근거를 기록). 단 상태가 falsify_min_status보다 낮으면
  → UNKNOWN, 사유 NEEDS_EVIDENCE (확인대상 폐기물의 '기준 미만'은 분석결과서로만 받는다)
- 그 외 → TRUE

확정 (docs/engine/algorithm.md 4.4절)
- PRIORITY: TRUE인 최고 우선순위 규칙 r이 있고, r보다 우선순위가 높으면서(같으면 다른 코드일 때)
  r과 다른 코드를 내는 UNKNOWN 규칙이 없을 때 확정. 같은 코드를 내는 상위 UNKNOWN 규칙은 결과를
  바꾸지 못하므로 막지 않는다.
- UNIQUE: TRUE가 정확히 하나이고, 남은 UNKNOWN 규칙이 모두 같은 코드를 낼 때만 확정.

보강: blocking_facts = 확정을 실제로 막고 있는 미확인 사실. 질문 풀은 여기서만 고른다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel

from app.domain.facts import STATUS_RANK, Fact, FactStatus
from app.domain.ranges import NumRange, range_satisfies
from app.rules.model import (
    All,
    AnyOf,
    Cond,
    Expr,
    FactDef,
    KnowledgeBase,
    Not,
    Rule,
    Table,
)


class TV(StrEnum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


UnknownReason = Literal["MISSING", "NEEDS_EVIDENCE", "DECLARED_UNKNOWN"]


# ---- 출력 모델 ----------------------------------------------------------------------------


class CondResult(BaseModel):
    fact: str
    op: str
    expected: Any = None
    actual: Any = None
    actual_status: FactStatus | None = None
    min_status: FactStatus
    falsify_min_status: FactStatus = FactStatus.CLAIMED
    status: TV
    reason: UnknownReason | None = None


class RuleResult(BaseModel):
    rule_id: str
    priority: int
    code: str | None
    category: str | None
    outcome: str | None = None
    status: TV
    conditions: list[CondResult]
    unknown_facts: list[str]  # 이 규칙의 결과를 바꿀 수 있는 미확인 사실
    eliminated_by: list[str]  # FALSE가 된 근거 사실 (TRUE면 성립 근거)

    @property
    def key(self) -> str:
        return self.code if self.code is not None else f"@{self.outcome}"


class Candidate(BaseModel):
    code: str | None
    category: str | None = None
    name: str | None = None
    outcome: str | None = None  # 코드 없는 결론의 사유
    rule_ids: list[str]
    status: TV  # 근거 규칙 중 가장 강한 상태 (TRUE > UNKNOWN)
    priority: int

    @property
    def key(self) -> str:
        return self.code if self.code is not None else f"@{self.outcome}"


class UnknownFact(BaseModel):
    key: str
    reason: UnknownReason
    rule_ids: list[str]
    evidence_type: str | None = None
    # 참·거짓 어느 쪽이든 증빙이 있어야 정해지는 사실(확인대상 폐기물의 시험 수치).
    # 말로 묻지 않는다.
    evidence_only: bool = False


TableStatus = Literal["SELECTED", "PENDING", "NONE", "AMBIGUOUS"]


class EvaluationResult(BaseModel):
    as_of: date
    table_status: TableStatus
    table_id: str | None = None
    table_version: str | None = None
    hit_policy: str | None = None
    rule_results: list[RuleResult] = []
    candidates: list[Candidate] = []
    live_candidates: list[Candidate] = []  # 확정 결과가 될 수 있는 후보 (PRIORITY에서 하위 제외)
    unknown_facts: list[UnknownFact] = []
    blocking_facts: list[UnknownFact] = []
    decided: Candidate | None = None
    tie: list[str] = []  # 같은 우선순위 TRUE 규칙이 서로 다른 코드를 낼 때 그 rule_id
    table_candidates: list[str] = []  # 테이블 선택 대기/모호 시 후보 테이블

    @property
    def can_confirm(self) -> bool:
        return self.decided is not None


# ---- 조건 평가 ----------------------------------------------------------------------------


def _compare(op: str, actual: Any, expected: Any, fd: FactDef | None) -> bool:
    if fd is not None and fd.type == "enum":
        actual = str(actual)
        expected = tuple(str(x) for x in expected) if isinstance(expected, tuple) else str(expected)
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "in":
        return actual in expected
    if op == "not_in":
        return actual not in expected
    if isinstance(actual, bool) or not isinstance(actual, int | float):
        raise TypeError("number 비교 대상이 아님")
    if op == "lt":
        return actual < expected
    if op == "lte":
        return actual <= expected
    if op == "gt":
        return actual > expected
    if op == "gte":
        return actual >= expected
    raise ValueError(op)


def eval_cond(c: Cond, facts: dict[str, Fact], catalog: dict[str, FactDef]) -> CondResult:
    f = facts.get(c.fact)
    base = dict(
        fact=c.fact,
        op=c.op,
        expected=c.value,
        min_status=c.min_status,
        falsify_min_status=c.falsify_min_status,
    )
    if (
        f is None
        or f.status in (FactStatus.UNKNOWN, FactStatus.DECLARED_UNKNOWN)
        or (f.value is None)
    ):
        reason: UnknownReason = "MISSING"
        if f is not None and f.status == FactStatus.DECLARED_UNKNOWN:
            reason = "DECLARED_UNKNOWN"
        return CondResult(
            **base,
            actual=None,
            actual_status=f.status if f else None,
            status=TV.UNKNOWN,
            reason=reason,
        )
    base.update(actual=f.value, actual_status=f.status)
    if c.op == "exists":
        matched = True
    else:
        try:
            if isinstance(f.value, NumRange):
                res = range_satisfies(f.value, c.op, c.value)
                if res is None:  # 구간이 임계값에 걸침 → 더 정확한 값이 필요
                    return CondResult(**base, status=TV.UNKNOWN, reason="MISSING")
                matched = res
            else:
                matched = _compare(c.op, f.value, c.value, catalog.get(c.fact))
        except (TypeError, ValueError):
            # 타입이 맞지 않는 값은 guard가 걸러야 한다. 여기서는 판단하지 않는다.
            return CondResult(**base, status=TV.UNKNOWN, reason="MISSING")
    if not matched:
        if STATUS_RANK[f.status] < STATUS_RANK[c.falsify_min_status]:
            # 확인대상 폐기물: '기준 미만'이라는 말만으로는 지정 후보를 지우지 않는다.
            return CondResult(**base, status=TV.UNKNOWN, reason="NEEDS_EVIDENCE")
        return CondResult(**base, status=TV.FALSE)
    if STATUS_RANK[f.status] < STATUS_RANK[c.min_status]:
        return CondResult(**base, status=TV.UNKNOWN, reason="NEEDS_EVIDENCE")
    return CondResult(**base, status=TV.TRUE)


# ---- Kleene 조합 -------------------------------------------------------------------------


@dataclass
class _Node:
    tv: TV
    open: list[CondResult]  # 결과를 바꿀 수 있는 미확인 조건
    support: list[CondResult]  # 결과(TRUE/FALSE)를 결정한 조건


def kleene_all(values: list[TV]) -> TV:
    if any(v == TV.FALSE for v in values):
        return TV.FALSE
    if all(v == TV.TRUE for v in values):
        return TV.TRUE
    return TV.UNKNOWN


def kleene_any(values: list[TV]) -> TV:
    if any(v == TV.TRUE for v in values):
        return TV.TRUE
    if all(v == TV.FALSE for v in values):
        return TV.FALSE
    return TV.UNKNOWN


def kleene_not(v: TV) -> TV:
    return {TV.TRUE: TV.FALSE, TV.FALSE: TV.TRUE, TV.UNKNOWN: TV.UNKNOWN}[v]


def _eval(
    expr: Expr, facts: dict[str, Fact], catalog: dict[str, FactDef], leaves: list[CondResult]
) -> _Node:
    if isinstance(expr, Cond):
        r = eval_cond(expr, facts, catalog)
        leaves.append(r)
        if r.status == TV.UNKNOWN:
            return _Node(TV.UNKNOWN, [r], [])
        return _Node(r.status, [], [r])
    if isinstance(expr, Not):
        n = _eval(expr.item, facts, catalog, leaves)
        return _Node(kleene_not(n.tv), n.open, n.support)
    children = [_eval(x, facts, catalog, leaves) for x in expr.items]
    tvs = [c.tv for c in children]
    if isinstance(expr, All):
        tv = kleene_all(tvs)
        decisive = TV.FALSE
    elif isinstance(expr, AnyOf):
        tv = kleene_any(tvs)
        decisive = TV.TRUE
    else:  # pragma: no cover
        raise TypeError(expr)
    if tv == TV.UNKNOWN:
        return _Node(tv, [o for c in children if c.tv == TV.UNKNOWN for o in c.open], [])
    if tv == decisive:
        return _Node(tv, [], [s for c in children if c.tv == decisive for s in c.support])
    return _Node(tv, [], [s for c in children for s in c.support])


def eval_expr(expr: Expr, facts: dict[str, Fact], catalog: dict[str, FactDef]) -> TV:
    return _eval(expr, facts, catalog, []).tv


def eval_rule(rule: Rule, facts: dict[str, Fact], catalog: dict[str, FactDef]) -> RuleResult:
    leaves: list[CondResult] = []
    node = _eval(rule.when, facts, catalog, leaves)
    return RuleResult(
        rule_id=rule.rule_id,
        priority=rule.priority,
        code=rule.then.code,
        category=rule.then.category,
        outcome=rule.then.outcome,
        status=node.tv,
        conditions=leaves,
        unknown_facts=sorted({c.fact for c in node.open}),
        eliminated_by=sorted({c.fact for c in node.support}),
    )


# ---- 테이블 평가 --------------------------------------------------------------------------


def _unknown_facts(results: list[RuleResult], catalog: dict[str, FactDef]) -> list[UnknownFact]:
    agg: dict[str, dict] = {}
    for rr in results:
        if rr.status != TV.UNKNOWN:
            continue
        open_keys = set(rr.unknown_facts)
        for c in rr.conditions:
            if c.fact not in open_keys or c.status != TV.UNKNOWN:
                continue
            fd = catalog.get(c.fact)
            reason = c.reason or "MISSING"
            if reason == "DECLARED_UNKNOWN" and fd is not None and fd.evidence_type:
                reason = "NEEDS_EVIDENCE"
            e = agg.setdefault(c.fact, {"reasons": set(), "rule_ids": set(), "strict": True})
            e["reasons"].add(reason)
            e["rule_ids"].add(rr.rule_id)
            e["strict"] = e["strict"] and (
                c.min_status == FactStatus.EVIDENCED
                and c.falsify_min_status == FactStatus.EVIDENCED
            )
    out = []
    for key in sorted(agg):
        reasons = agg[key]["reasons"]
        # 한 사실의 상태는 하나라 사유도 대부분 하나다. 섞이면 MISSING을 우선한다(물어야 함).
        reason = next(r for r in ("MISSING", "NEEDS_EVIDENCE", "DECLARED_UNKNOWN") if r in reasons)
        fd = catalog.get(key)
        out.append(
            UnknownFact(
                key=key,
                reason=reason,
                rule_ids=sorted(agg[key]["rule_ids"]),
                evidence_type=fd.evidence_type if fd else None,
                evidence_only=bool(agg[key]["strict"] and fd is not None and fd.evidence_type),
            )
        )
    return out


def _candidates(results: list[RuleResult], rules: dict[str, Rule]) -> list[Candidate]:
    by_code: dict[str, Candidate] = {}
    for rr in results:
        if rr.status == TV.FALSE:
            continue
        cand = by_code.get(rr.key)
        if cand is None:
            by_code[rr.key] = Candidate(
                code=rr.code,
                category=rr.category,
                name=rules[rr.rule_id].then.name,
                outcome=rr.outcome,
                rule_ids=[rr.rule_id],
                status=rr.status,
                priority=rr.priority,
            )
        else:
            cand.rule_ids.append(rr.rule_id)
            if rr.status == TV.TRUE:
                cand.status = TV.TRUE
            cand.priority = max(cand.priority, rr.priority)
    return sorted(by_code.values(), key=lambda c: (-c.priority, c.key))


def _is_ready(r: RuleResult, catalog: dict[str, FactDef]) -> bool:
    """남은 미확인 사실이 모두 ask_last(예: 별표4 번호 선택)뿐인 규칙. 사실상 성립한 것으로 본다."""
    return (
        r.status == TV.UNKNOWN
        and bool(r.unknown_facts)
        and all(f in catalog and catalog[f].ask_last for f in r.unknown_facts)
    )


def _priority_floor(results: list[RuleResult], catalog: dict[str, FactDef]) -> int | None:
    """확정 후보가 될 수 있는 가장 높은 우선순위: TRUE 규칙과 번호 선택만 남은 규칙 중 최댓값."""
    ps = [r.priority for r in results if r.status == TV.TRUE or _is_ready(r, catalog)]
    return max(ps, default=None)


def _decide_priority(results: list[RuleResult], catalog: dict[str, FactDef]):
    trues = [r for r in results if r.status == TV.TRUE]
    unknowns = [r for r in results if r.status == TV.UNKNOWN]
    floor = _priority_floor(results, catalog)
    if floor is None:
        return None, unknowns, []
    if not trues or max(r.priority for r in trues) < floor:
        # 가장 높은 후보가 번호 선택만 남음 → 번호 선택 자체와, 선택지를 늘릴 수 있는
        # (아직 선택지에 없는 결론을 내는) 그 대역 이상의 미확인 규칙만 막는다.
        ready = [r for r in unknowns if r.priority >= floor and _is_ready(r, catalog)]
        ready_keys = {r.key for r in ready}
        others = [
            r
            for r in unknowns
            if r.priority >= floor and not _is_ready(r, catalog) and r.key not in ready_keys
        ]
        return None, ready + others, []
    top_p = max(r.priority for r in trues)
    top = [r for r in trues if r.priority == top_p]
    top_keys = {r.key for r in top}
    if len(top_keys) > 1:
        return None, unknowns, sorted(r.rule_id for r in top)
    (key,) = top_keys
    blockers = [r for r in unknowns if r.key != key and r.priority >= top_p]
    if blockers:
        return None, blockers, []
    return top[0], [], []


def _decide_unique(results: list[RuleResult]):
    trues = [r for r in results if r.status == TV.TRUE]
    unknowns = [r for r in results if r.status == TV.UNKNOWN]
    keys = {r.key for r in trues}
    if len(keys) > 1:
        return None, unknowns, sorted(r.rule_id for r in trues)
    if not trues:
        return None, unknowns, []
    (key,) = keys
    blockers = [r for r in unknowns if r.key != key]
    if blockers:
        return None, blockers, []
    return trues[0], [], []


def evaluate_table(
    table: Table, facts: dict[str, Fact], catalog: dict[str, FactDef], as_of: date
) -> EvaluationResult:
    rules = table.rules_as_of(as_of)
    rule_map = {r.rule_id: r for r in rules}
    results = [eval_rule(r, facts, catalog) for r in rules]
    candidates = _candidates(results, rule_map)
    if table.hit_policy == "PRIORITY":
        winner, blockers, tie = _decide_priority(results, catalog)
        floor = _priority_floor(results, catalog)
        live = [c for c in candidates if floor is None or c.priority >= floor]
    else:
        winner, blockers, tie = _decide_unique(results)
        live = list(candidates)
    unknown = _unknown_facts(results, catalog)
    blocking = _unknown_facts(blockers, catalog)
    decided = None
    if winner is not None:
        decided = next(c for c in candidates if c.key == winner.key)
        status_of = {r.rule_id: r.status for r in results}
        decided = decided.model_copy(
            update={
                "rule_ids": [winner.rule_id]
                + [
                    rid
                    for rid in decided.rule_ids
                    if rid != winner.rule_id and status_of[rid] == TV.TRUE
                ]
            }
        )
    return EvaluationResult(
        as_of=as_of,
        table_status="SELECTED",
        table_id=table.table_id,
        table_version=table.version,
        hit_policy=table.hit_policy,
        rule_results=results,
        candidates=candidates,
        live_candidates=live,
        unknown_facts=unknown,
        blocking_facts=blocking,
        decided=decided,
        tie=tie,
    )


# ---- 진입점: 테이블 선택 + 평가 -------------------------------------------------------------


def evaluate(kb: KnowledgeBase, facts: dict[str, Fact], as_of: date) -> EvaluationResult:
    """유효 사실로 적용 테이블을 고르고 평가한다.

    - applies_when이 TRUE인 테이블이 하나면 그 테이블을 평가한다(SELECTED).
    - TRUE가 둘 이상이면 AMBIGUOUS, 모두 FALSE면 NONE(지원 범위 밖).
    - 아직 정할 수 없으면 PENDING: 선택 조건의 미확인 사실을 질문 대상으로 내고,
      후보는 아직 가능한 테이블들의 후보를 합친다.
    """
    # 대리 질문의 추정(implies)을 먼저 적용한다.
    # 선택기의 가정 평가도 여기를 지나므로 정보가치가 맞다.
    from app.rules.implications import apply_implications  # 순환 import 방지

    facts = apply_implications(kb, facts)
    tables = kb.tables_as_of(as_of)
    statuses: list[tuple[Table, TV, list[CondResult]]] = []
    for t in tables:
        if t.applies_when is None:
            statuses.append((t, TV.TRUE, []))
            continue
        leaves: list[CondResult] = []
        node = _eval(t.applies_when, facts, kb.catalog, leaves)
        statuses.append((t, node.tv, node.open))
    selected = [t for t, tv, _ in statuses if tv == TV.TRUE]
    pending = [(t, op) for t, tv, op in statuses if tv == TV.UNKNOWN]
    if len(selected) == 1:
        return evaluate_table(selected[0], facts, kb.catalog, as_of)
    if len(selected) > 1:
        return EvaluationResult(
            as_of=as_of,
            table_status="AMBIGUOUS",
            table_candidates=sorted(t.table_id for t in selected),
        )
    if not pending:
        return EvaluationResult(as_of=as_of, table_status="NONE")
    # PENDING: 테이블 선택 사실을 먼저 묻는다.
    merged: dict[str | None, Candidate] = {}
    for table, _ in pending:
        # 선택 전에는 후보 목록만 쓴다. 각 테이블의 확정·질문·증빙 집계까지
        # 만들지 않아도 후보와 우선순위는 동일하며, 아직 어떤 판정도 확정하지 않는다.
        rules = table.rules_as_of(as_of)
        candidates = _candidates(
            [eval_rule(rule, facts, kb.catalog) for rule in rules],
            {rule.rule_id: rule for rule in rules},
        )
        for c in candidates:
            if c.key not in merged:
                merged[c.key] = c.model_copy(update={"status": TV.UNKNOWN})
    agg: dict[str, set[str]] = {}
    for t, open_conds in pending:
        for c in open_conds:
            agg.setdefault(c.fact, set()).add(f"{t.table_id}:applies_when")
    selection_unknown = []
    for key in sorted(agg):
        f = facts.get(key)
        reason: UnknownReason = "MISSING"
        if f is not None and f.status == FactStatus.DECLARED_UNKNOWN:
            reason = "DECLARED_UNKNOWN"
        fd = kb.catalog.get(key)
        selection_unknown.append(
            UnknownFact(
                key=key,
                reason=reason,
                rule_ids=sorted(agg[key]),
                evidence_type=fd.evidence_type if fd else None,
            )
        )
    cands = sorted(merged.values(), key=lambda c: (-c.priority, c.key))
    return EvaluationResult(
        as_of=as_of,
        table_status="PENDING",
        candidates=cands,
        live_candidates=cands,
        unknown_facts=selection_unknown,
        blocking_facts=selection_unknown,
        table_candidates=sorted(t.table_id for t, _ in pending),
    )
