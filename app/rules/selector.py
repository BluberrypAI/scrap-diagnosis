"""정보가치 기반 질문 선택기 (md 7절 + 보강).

1. 질문 풀 = blocking_facts 중 사유가 MISSING인 것 (확정을 실제로 막는 사실만)
2. 값 영역: enum → values, bool → {true,false}, number → 규칙 임계값으로 나눈 구간
3. 값마다 평가기를 돌려 남는 후보 수 n_v (확정되면 1)
4. gain = log N − Σ p_v · log max(n_v, 1)   (p_v: 카탈로그 prior, 없으면 균등)
5. cost = ask_cost
6. score = legal_priority × gain / cost (× 사용자 코드 주장 가중치)
   gain이 모두 0이면 결과를 바꾸지 못하는 질문이므로, 규칙 해소 정도(resolve)로만 고른다.
   동점이면 legal_priority, 그다음 key 사전순.
묶음 질문(question_groups)도 하나의 질문 단위로 같은 식으로 점수를 매긴다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from app.domain.facts import Fact, FactStatus
from app.domain.ranges import NumRange, range_satisfies
from app.rules.evaluator import TV, EvaluationResult, UnknownFact, evaluate
from app.rules.model import NUMERIC_OPS, FactDef, KnowledgeBase, QuestionGroup, iter_conds

FOCUS_WEIGHT = 1.5
UNKNOWN_LABEL = "모름"


@dataclass(frozen=True)
class SelectionContext:
    """질문 선택에 필요한 세션 상태."""

    expanded_groups: frozenset[str] = frozenset()
    focus_codes: frozenset[str] = frozenset()  # 사용자가 주장한 코드


class ValueOption(BaseModel):
    label: str
    value: Any = None
    kind: Literal["value", "unknown", "none_all", "expand"] = "value"


class ScoreEntry(BaseModel):
    unit: Literal["fact", "group"]
    key: str
    legal_priority: float
    gain: float
    resolve: float
    cost: float
    focus: float
    score: float
    outcomes: dict[str, int]  # 선택지 라벨 → 남는 후보 수


class QuestionChoice(BaseModel):
    unit: Literal["fact", "group"]
    key: str
    facts: list[str]
    reason: str
    question_hint: str
    help: str | None = None
    value_options: list[ValueOption]
    score_breakdown: list[ScoreEntry]
    fallback: bool = False  # gain이 모두 0이라 해소 정도로 고름


# ---- 값 영역 ---------------------------------------------------------------------------


def value_key(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _probabilities(fd: FactDef, keys: list[str]) -> list[float]:
    given = {k: p for k, p in fd.prior.items() if k in keys}
    rest = [k for k in keys if k not in given]
    remaining = max(0.0, 1.0 - sum(given.values()))
    share = remaining / len(rest) if rest else 0.0
    probs = [given.get(k, share) for k in keys]
    total = sum(probs)
    return [p / total for p in probs] if total > 0 else [1 / len(keys)] * len(keys)


def numeric_segments(kb: KnowledgeBase, key: str) -> list[NumRange]:
    """규칙에 나오는 임계값으로 수직선을 나누고, 모든 조건의 참거짓이 같은 조각끼리 합친다."""
    conds = [
        c
        for t in kb.tables
        for r in t.rules
        for c in iter_conds(r.when)
        if c.fact == key and c.op in NUMERIC_OPS | {"eq", "ne"}
    ]
    thresholds = sorted({float(c.value) for c in conds})
    if not thresholds:
        return []
    pieces: list[NumRange] = [NumRange(lo=None, hi=thresholds[0], hi_inc=False)]
    for i, t in enumerate(thresholds):
        pieces.append(NumRange(lo=t, lo_inc=True, hi=t, hi_inc=True))
        nxt = thresholds[i + 1] if i + 1 < len(thresholds) else None
        pieces.append(NumRange(lo=t, lo_inc=False, hi=nxt, hi_inc=False))

    def signature(p: NumRange) -> tuple:
        return tuple(range_satisfies(p, c.op, c.value) for c in conds)

    merged: list[tuple[NumRange, tuple]] = []
    for p in pieces:
        sig = signature(p)
        if merged and merged[-1][1] == sig:
            prev = merged[-1][0]
            merged[-1] = (NumRange(lo=prev.lo, lo_inc=prev.lo_inc, hi=p.hi, hi_inc=p.hi_inc), sig)
        else:
            merged.append((p, sig))
    return [m for m, _ in merged]


def value_domain(kb: KnowledgeBase, fd: FactDef) -> list[tuple[ValueOption, float]]:
    if fd.type == "enum":
        keys = list(fd.values or ())
        opts = [ValueOption(label=fd.value_labels.get(k, k), value=k) for k in keys]
    elif fd.type == "bool":
        keys = ["true", "false"]
        opts = [ValueOption(label="예", value=True), ValueOption(label="아니오", value=False)]
    else:
        segs = numeric_segments(kb, fd.key)
        keys = [s.label(fd.unit) for s in segs]
        opts = [ValueOption(label=s.label(fd.unit), value=s.model_dump()) for s in segs]
    if not opts:
        return []
    return list(zip(opts, _probabilities(fd, keys), strict=True))


# ---- 가정 평가 -------------------------------------------------------------------------


def _outcome_size(ev: EvaluationResult) -> int:
    if ev.decided is not None:
        return 1
    return len({c.code for c in ev.live_candidates})


def _unknown_rules(ev: EvaluationResult) -> set[str]:
    return {r.rule_id for r in ev.rule_results if r.status == TV.UNKNOWN}


def _hypo_fact(key: str, value: Any) -> Fact:
    if isinstance(value, dict):
        value = NumRange(**value)
    return Fact(
        key=key,
        value=value,
        status=FactStatus.CLAIMED,
        source_type="SIMULATION",
        source_ref="selector",
    )


@dataclass
class _Scored:
    entry: ScoreEntry
    choice_base: dict = field(default_factory=dict)


def _score(
    kb: KnowledgeBase,
    facts: dict[str, Fact],
    base: EvaluationResult,
    as_of: date,
    unit: str,
    key: str,
    hypotheses: list[tuple[str, dict[str, Any], float]],
    legal_priority: float,
    cost: float,
    focus: float,
) -> ScoreEntry:
    n0 = max(_outcome_size(base), 1)
    open0 = _unknown_rules(base)
    exp_log, resolve = 0.0, 0.0
    outcomes: dict[str, int] = {}
    for label, assignment, p in hypotheses:
        hypo = dict(facts)
        for k, v in assignment.items():
            hypo[k] = _hypo_fact(k, v)
        ev = evaluate(kb, hypo, as_of)
        n = _outcome_size(ev)
        outcomes[label] = n
        exp_log += p * math.log(max(n, 1))
        if ev.decided is not None or ev.table_status != base.table_status:
            resolve += p * max(len(open0), 1)
        else:
            resolve += p * len(open0 - _unknown_rules(ev))
    gain = max(0.0, math.log(n0) - exp_log)
    score = legal_priority * gain / cost * focus
    return ScoreEntry(
        unit=unit,
        key=key,
        legal_priority=legal_priority,
        gain=round(gain, 6),
        resolve=round(resolve, 6),
        cost=cost,
        focus=focus,
        score=round(score, 6),
        outcomes=outcomes,
    )


def _focus(kb: KnowledgeBase, keys: set[str], ctx: SelectionContext) -> float:
    if not ctx.focus_codes:
        return 1.0
    for t in kb.tables:
        for r in t.rules:
            if r.then.code in ctx.focus_codes and r.facts() & keys:
                return FOCUS_WEIGHT
    return 1.0


def eligible_groups(
    kb: KnowledgeBase, pool: set[str], ctx: SelectionContext
) -> list[tuple[QuestionGroup, list[str]]]:
    out = []
    for g in kb.groups:
        if g.group_id in ctx.expanded_groups:
            continue
        open_members = [k for k in g.facts if k in pool]
        if len(open_members) >= 2:
            out.append((g, open_members))
    return out


def select_question(
    kb: KnowledgeBase,
    facts: dict[str, Fact],
    base: EvaluationResult,
    as_of: date,
    ctx: SelectionContext | None = None,
) -> QuestionChoice | None:
    ctx = ctx or SelectionContext()
    pool_items: list[UnknownFact] = [u for u in base.blocking_facts if u.reason == "MISSING"]
    pool = {u.key for u in pool_items}
    if not pool:
        return None
    entries: list[ScoreEntry] = []
    choices: dict[tuple[str, str], QuestionChoice] = {}

    for u in sorted(pool_items, key=lambda x: x.key):
        fd = kb.catalog[u.key]
        domain = value_domain(kb, fd)
        if not domain:
            continue
        hyps = [(opt.label, {u.key: opt.value}, p) for opt, p in domain]
        e = _score(
            kb,
            facts,
            base,
            as_of,
            "fact",
            u.key,
            hyps,
            fd.legal_priority,
            fd.ask_cost,
            _focus(kb, {u.key}, ctx),
        )
        entries.append(e)
        choices[("fact", u.key)] = QuestionChoice(
            unit="fact",
            key=u.key,
            facts=[u.key],
            reason=u.reason,
            question_hint=fd.question_hint,
            help=fd.help,
            value_options=[opt for opt, _ in domain]
            + [ValueOption(label=UNKNOWN_LABEL, kind="unknown")],
            score_breakdown=[],
        )

    for g, members in eligible_groups(kb, pool, ctx):
        none_assign = {k: kb.catalog[k].none_value for k in members}
        p_none = 1.0
        for k in members:
            fd = kb.catalog[k]
            dom = value_domain(kb, fd)
            keys = [value_key(o.value) if fd.type != "number" else o.label for o, _ in dom]
            probs = dict(zip(keys, _probabilities(fd, keys), strict=True))
            p_none *= probs.get(value_key(fd.none_value), 1 / max(len(keys), 1))
        hyps = [(g.none_label, none_assign, p_none), (g.expand_label, {}, 1 - p_none)]
        lp = max(kb.catalog[k].legal_priority for k in members)
        e = _score(
            kb,
            facts,
            base,
            as_of,
            "group",
            g.group_id,
            hyps,
            lp,
            g.ask_cost,
            _focus(kb, set(members), ctx),
        )
        entries.append(e)
        choices[("group", g.group_id)] = QuestionChoice(
            unit="group",
            key=g.group_id,
            facts=members,
            reason="MISSING",
            question_hint=g.title,
            help=g.help,
            value_options=[
                ValueOption(label=g.none_label, value=none_assign, kind="none_all"),
                ValueOption(label=g.expand_label, kind="expand"),
            ],
            score_breakdown=[],
        )

    if not entries:
        return None
    ranked = sorted(entries, key=lambda e: (-e.score, -e.legal_priority, e.key))
    fallback = ranked[0].score <= 0
    if fallback:
        # 결과를 바꾸는 질문이 없지만 아직 확정할 수 없다 → 규칙을 가장 많이 해소하는 질문
        ranked = sorted(
            entries,
            key=lambda e: (
                -(e.legal_priority * e.resolve / e.cost * e.focus),
                -e.legal_priority,
                e.key,
            ),
        )
    best = ranked[0]
    choice = choices[(best.unit, best.key)]
    return choice.model_copy(update={"score_breakdown": ranked, "fallback": fallback})
