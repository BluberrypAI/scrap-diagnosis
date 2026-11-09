"""정보가치 기반 질문 선택기 (docs/engine/algorithm.md 5절).

1. 질문 풀 = blocking_facts 중 사유가 MISSING인 것 (확정을 실제로 막는 사실만)
2. 값 영역: enum → values, bool → {true,false}, number → 규칙 임계값으로 나눈 구간
3. 값마다 평가기를 돌려 남는 후보 수 n_v (확정되면 1)
4. gain = log N − Σ p_v · log max(n_v, 1)   (p_v: 카탈로그 prior, 없으면 균등)
5. cost = ask_cost
6. score = legal_priority × gain / cost (× 사용자 코드 주장 가중치)
   gain이 모두 0이면 결과를 바꾸지 못하는 질문이므로, 규칙 해소 정도(resolve)로만 고른다.
   동점이면 legal_priority, 그다음 key 사전순.
묶음 질문(question_groups)도 하나의 질문 단위로 같은 식으로 점수를 매긴다.

2단계 질문(카탈로그의 parent/value_parent, 예: 소재 → 소재 분류)
- 상위 분류를 모르면 세부 사실 대신 상위 분류를 묻는다. 선택지는 세부 값이 하나라도 남은 분류.
  점수는 세부 값 가정의 결과를 분류별로 합쳐 계산한다(분류 확률 = 세부 값 확률의 합,
  남는 후보 = 세부 값별 후보의 합집합). 분류가 하나뿐이면 묻지 않고 세부 사실을 바로 묻는다.
- 상위 분류를 알면 세부 사실의 선택지를 그 분류의 값으로 줄인다. 해당 값이 없으면 줄이지 않는다.
- 상위 분류를 '모름'이라 답했으면 세부 사실을 전체 선택지로 묻는다.
- 세부 값을 직접 말하면 상위 분류와 달라도 세부 값이 이긴다(상위 분류는 규칙이 참조하지 않음).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from app.domain.facts import Fact, FactStatus
from app.domain.ranges import NumRange, range_satisfies
from app.rules.evaluator import TV, EvaluationResult, UnknownFact, evaluate
from app.rules.model import NUMERIC_OPS, FactDef, KnowledgeBase, QuestionGroup, Table, iter_conds

FOCUS_WEIGHT = 1.5
UNKNOWN_LABEL = "모름"


@dataclass(frozen=True)
class SelectionContext:
    """질문 선택에 필요한 세션 상태."""

    expanded_groups: frozenset[str] = frozenset()
    focus_codes: frozenset[str] = frozenset()  # 사용자가 주장한 코드
    exclude_keys: frozenset[str] = frozenset()  # 묻지 않을 사실(증빙으로 한꺼번에 받을 사실 등)


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


def table_of(kb: KnowledgeBase, ev: EvaluationResult | None) -> Table | None:
    if ev is None or ev.table_id is None:
        return None
    return next((t for t in kb.tables if t.table_id == ev.table_id), None)


def numeric_segments(
    kb: KnowledgeBase, key: str, base: EvaluationResult | None = None
) -> list[NumRange]:
    """규칙에 나오는 임계값으로 수직선을 나누고, 모든 조건의 참거짓이 같은 조각끼리 합친다.

    적용 테이블이 정해졌으면 그 테이블의 임계값만 쓴다.
    """
    t = table_of(kb, base)
    tables = [t] if t is not None else list(kb.tables)
    conds = [
        c
        for tb in tables
        for r in tb.rules
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


def referenced_values(kb: KnowledgeBase, base: EvaluationResult | None, key: str) -> list[str]:
    """적용 테이블에서 이 사실 때문에 확정이 막힌 규칙의 조건(eq/in)에 나오는 값.

    막는 규칙이 없으면 확정 후보가 될 수 있는(live) FALSE가 아닌 규칙에서 찾는다. 순서는 첫 등장 순.
    """
    t = table_of(kb, base)
    if t is None or base is None:
        return []
    blocking = next((u for u in base.blocking_facts if u.key == key), None)
    if blocking is not None:
        alive = set(blocking.rule_ids)
    else:
        live = {c.key for c in base.live_candidates}
        alive = {r.rule_id for r in base.rule_results if r.status != TV.FALSE and r.key in live}
    out: dict[str, None] = {}
    for r in t.rules:
        if r.rule_id not in alive:
            continue
        for c in iter_conds(r.when):
            if c.fact != key:
                continue
            if c.op == "eq":
                out[str(c.value)] = None
            elif c.op == "in":
                for v in c.value:
                    out[str(v)] = None
    return list(out)


def parent_value(fd: FactDef, facts: dict[str, Fact] | None) -> str | None:
    """세부 사실(fd)의 상위 분류 값. 상위 분류가 없거나 아직 모르면 None."""
    if fd.parent is None or not facts:
        return None
    f = facts.get(fd.parent)
    return str(f.value) if f is not None and f.is_known else None


def values_under_parent(fd: FactDef, keys: list[str], facts: dict[str, Fact] | None) -> list[str]:
    """상위 분류를 알면 그 분류의 값만 남긴다. 남는 값이 없으면(분류와 맞지 않음) 줄이지 않는다."""
    pv = parent_value(fd, facts)
    if pv is None:
        return keys
    kept = [k for k in keys if fd.value_parent.get(k) == pv]
    return kept or keys


def parent_to_ask(kb: KnowledgeBase, fd: FactDef, facts: dict[str, Fact]) -> FactDef | None:
    """세부 사실 대신 먼저 물을 상위 분류. 이미 알거나 '모름'이라 답했으면 None."""
    if fd.parent is None:
        return None
    f = facts.get(fd.parent)
    if f is not None and (f.is_known or f.status == FactStatus.DECLARED_UNKNOWN):
        return None
    return kb.catalog[fd.parent]


def implied_child(kb: KnowledgeBase, facts: dict[str, Fact], base: EvaluationResult) -> Fact | None:
    """상위 분류에 속한 세부 값이 하나뿐이면 그 값을 채운다(출처 DERIVED).

    예: 소재 분류 '여러 소재가 섞여 나누기 어려운 것' → 소재 '혼합물'.
    """
    for u in base.blocking_facts:
        if u.reason != "MISSING":
            continue
        fd = kb.catalog[u.key]
        pv = parent_value(fd, facts)
        if pv is None:
            continue
        vals = [k for k in (fd.values or ()) if fd.value_parent.get(k) == pv]
        if len(vals) != 1:
            continue
        pfd = kb.catalog[fd.parent]
        return Fact(
            key=fd.key,
            value=vals[0],
            status=FactStatus.CLAIMED,
            source_type="DERIVED",
            source_ref="parent_single",
            note=f"'{pfd.value_labels.get(pv, pv)}'에 해당하는 값이 하나라 자동으로 정함",
        )
    return None


def value_domain(
    kb: KnowledgeBase,
    fd: FactDef,
    base: EvaluationResult | None = None,
    facts: dict[str, Fact] | None = None,
) -> list[tuple[ValueOption, float]]:
    """질문 선택지와 확률. facts를 주면 상위 분류로 선택지를 줄인다."""
    if fd.type == "enum":
        if fd.domain == "referenced":
            keys = referenced_values(kb, base, fd.key)
        else:
            keys = list(fd.values or ())
        keys = values_under_parent(fd, keys, facts)
        opts = [ValueOption(label=fd.value_labels.get(k, k), value=k) for k in keys]
    elif fd.type == "bool":
        keys = ["true", "false"]
        opts = [ValueOption(label="예", value=True), ValueOption(label="아니오", value=False)]
    else:
        segs = numeric_segments(kb, fd.key, base)
        keys = [s.label(fd.unit) for s in segs]
        opts = [ValueOption(label=s.label(fd.unit), value=s.model_dump()) for s in segs]
    if not opts:
        return []
    return list(zip(opts, _probabilities(fd, keys), strict=True))


# ---- 가정 평가 -------------------------------------------------------------------------


def _outcome_keys(ev: EvaluationResult) -> frozenset[str]:
    if ev.decided is not None:
        return frozenset({ev.decided.key})
    return frozenset(c.key for c in ev.live_candidates)


def _outcome_size(ev: EvaluationResult) -> int:
    return len(_outcome_keys(ev))


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


@dataclass(frozen=True)
class _Hypo:
    """선택지 하나를 가정했을 때의 결과."""

    label: str
    p: float
    keys: frozenset[str]  # 남는 후보(확정이면 그 하나)
    resolve: float  # 해소되는 규칙 수


def _run_hypotheses(
    kb: KnowledgeBase,
    facts: dict[str, Fact],
    base: EvaluationResult,
    as_of: date,
    hypotheses: list[tuple[str, dict[str, Any], float]],
) -> list[_Hypo]:
    open0 = _unknown_rules(base)
    out = []
    for label, assignment, p in hypotheses:
        hypo = dict(facts)
        for k, v in assignment.items():
            hypo[k] = _hypo_fact(k, v)
        ev = evaluate(kb, hypo, as_of)
        if ev.decided is not None or ev.table_status != base.table_status:
            resolve = max(len(open0), 1)
        else:
            resolve = len(open0 - _unknown_rules(ev))
        out.append(_Hypo(label=label, p=p, keys=_outcome_keys(ev), resolve=resolve))
    return out


def _merge_by_parent(
    child: FactDef, parent: FactDef, domain: list[tuple[ValueOption, float]], runs: list[_Hypo]
) -> list[tuple[str, _Hypo]]:
    """세부 값 가정 결과를 상위 분류 값별로 합친다. 순서는 상위 분류의 값 순서."""
    by_parent: dict[str, list[_Hypo]] = {}
    for (opt, _), h in zip(domain, runs, strict=True):
        by_parent.setdefault(child.value_parent[str(opt.value)], []).append(h)
    out = []
    for pv in parent.values or ():
        hs = by_parent.get(pv)
        if not hs:
            continue
        p = sum(h.p for h in hs)
        merged = _Hypo(
            label=parent.value_labels.get(pv, pv),
            p=p,
            keys=frozenset().union(*(h.keys for h in hs)),
            resolve=sum(h.p * h.resolve for h in hs) / p if p > 0 else 0.0,
        )
        out.append((pv, merged))
    return out


def _entry(
    base: EvaluationResult,
    unit: str,
    key: str,
    hypos: list[_Hypo],
    legal_priority: float,
    cost: float,
    focus: float,
) -> ScoreEntry:
    n0 = max(_outcome_size(base), 1)
    exp_log = sum(h.p * math.log(max(len(h.keys), 1)) for h in hypos)
    resolve = sum(h.p * h.resolve for h in hypos)
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
        outcomes={h.label: len(h.keys) for h in hypos},
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
    # ask_last 사실(예: 별표4 번호 선택)은 확정을 막는 다른 사실이 모두 풀린 뒤에만 묻는다.
    others = [u for u in base.blocking_facts if not kb.catalog[u.key].ask_last]
    if others:
        pool_items = [u for u in pool_items if not kb.catalog[u.key].ask_last]
    pool_items = [u for u in pool_items if u.key not in ctx.exclude_keys]
    pool = {u.key for u in pool_items}
    if not pool:
        return None
    entries: list[ScoreEntry] = []
    choices: dict[tuple[str, str], QuestionChoice] = {}

    for u in sorted(pool_items, key=lambda x: x.key):
        fd = kb.catalog[u.key]
        domain = value_domain(kb, fd, base, facts)
        if not domain:
            continue
        hyps = [(opt.label, {u.key: opt.value}, p) for opt, p in domain]
        runs = _run_hypotheses(kb, facts, base, as_of, hyps)
        focus = _focus(kb, {u.key}, ctx)
        pfd = parent_to_ask(kb, fd, facts)
        merged = _merge_by_parent(fd, pfd, domain, runs) if pfd is not None else []
        if pfd is not None and len(merged) >= 2 and ("fact", pfd.key) not in choices:
            # 상위 분류를 먼저 묻는다(예: 소재 97개 대신 소재 분류 13개).
            entries.append(
                _entry(
                    base,
                    "fact",
                    pfd.key,
                    [h for _, h in merged],
                    pfd.legal_priority,
                    pfd.ask_cost,
                    focus,
                )
            )
            choices[("fact", pfd.key)] = QuestionChoice(
                unit="fact",
                key=pfd.key,
                facts=[pfd.key],
                reason=u.reason,
                question_hint=pfd.question_hint,
                help=pfd.help,
                value_options=[ValueOption(label=h.label, value=pv) for pv, h in merged]
                + [ValueOption(label=UNKNOWN_LABEL, kind="unknown")],
                score_breakdown=[],
            )
            continue
        e = _entry(base, "fact", u.key, runs, fd.legal_priority, fd.ask_cost, focus)
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
            dom = value_domain(kb, fd, base, facts)
            keys = [value_key(o.value) if fd.type != "number" else o.label for o, _ in dom]
            probs = dict(zip(keys, _probabilities(fd, keys), strict=True))
            p_none *= probs.get(value_key(fd.none_value), 1 / max(len(keys), 1))
        hyps = [(g.none_label, none_assign, p_none), (g.expand_label, {}, 1 - p_none)]
        lp = max(kb.catalog[k].legal_priority for k in members)
        e = _entry(
            base,
            "group",
            g.group_id,
            _run_hypotheses(kb, facts, base, as_of, hyps),
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
