"""판정 흐름 실행기: knowledge/flow/SCHEMA.md의 형식과 평가 방식을 그대로 구현한다.

규칙 내용은 모른다. 단계 파일(stage)을 번호 순서대로 읽어, 사실(facts)에 대해
첫 참 규칙을 적용하고, 참에 닿기 전에 모름을 만나면 막힘(INSUFFICIENT_INFO)으로 끝낸다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

OUTCOMES = {
    "NOT_WASTE",
    "CIRCULAR_RESOURCE",
    "EXCLUDED",
    "HOUSEHOLD",
    "DESIGNATED_POSSIBLE",
    "OUT_OF_SCOPE",
    "GENERAL",
    "INSUFFICIENT_INFO",
}
STAGES = (
    "10_is_waste",
    "20_circular",
    "30_exclusion",
    "40_business",
    "50_designated",
    "60_scope",
    "70_code",
)
COMPARATORS = {"eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "exists"}


class TV(Enum):
    """3값 논리(Kleene)."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class FlowError(ValueError):
    """규칙 파일 형식 오류."""


def norm(v: Any) -> Any:
    """YAML 1.1은 yes/no를 불리언으로 읽는다. 사실 값 표기(문자열)로 맞춘다."""
    if v is True:
        return "yes"
    if v is False:
        return "no"
    return v


@dataclass
class Result:
    outcome: str
    code: str | None = None
    flags: list[str] = field(default_factory=list)
    blocking_facts: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)

    def key(self) -> tuple:
        return (self.outcome, self.code or None, tuple(sorted(self.flags)))


@dataclass
class Rule:
    id: str
    when: dict
    then: Any
    basis: list[dict]
    stage: str


@dataclass
class Stage:
    name: str
    order: int
    rules: list[Rule]
    on_no_match: Any


def lookup(facts: dict, path: str) -> Any:
    cur: Any = facts
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def compare(op: str, value: Any, target: Any) -> TV:
    if op == "exists":
        present = value is not None and value != "unknown"
        return TV.TRUE if present == bool(target) else TV.FALSE
    target = [norm(t) for t in target] if isinstance(target, list) else norm(target)
    # 모름을 직접 묻는 비교는 참·거짓으로 정해진다
    if op == "eq" and target == "unknown":
        return TV.TRUE if value is None or value == "unknown" else TV.FALSE
    if op == "ne" and target == "unknown":
        return TV.FALSE if value is None or value == "unknown" else TV.TRUE
    if op == "in" and "unknown" in target and (value is None or value == "unknown"):
        return TV.TRUE
    if value is None or value == "unknown":
        return TV.UNKNOWN
    value = norm(value)
    if op == "eq":
        ok = value == target
    elif op == "ne":
        ok = value != target
    elif op == "in":
        ok = value in target
    elif op == "not_in":
        ok = value not in target
    else:
        try:
            v, t = float(value), float(target)
        except (TypeError, ValueError):
            return TV.UNKNOWN
        ok = {"gt": v > t, "gte": v >= t, "lt": v < t, "lte": v <= t}[op]
    return TV.TRUE if ok else TV.FALSE


def evaluate(cond: dict, facts: dict, unknowns: set[str]) -> TV:
    if "all" in cond:
        vals = [evaluate(c, facts, unknowns) for c in cond["all"]]
        if TV.FALSE in vals:
            return TV.FALSE
        return TV.TRUE if all(v is TV.TRUE for v in vals) else TV.UNKNOWN
    if "any" in cond:
        vals = [evaluate(c, facts, unknowns) for c in cond["any"]]
        if TV.TRUE in vals:
            return TV.TRUE
        return TV.FALSE if all(v is TV.FALSE for v in vals) else TV.UNKNOWN
    if "not" in cond:
        v = evaluate(cond["not"], facts, unknowns)
        return {TV.TRUE: TV.FALSE, TV.FALSE: TV.TRUE, TV.UNKNOWN: TV.UNKNOWN}[v]
    if "fact" in cond:
        ops = [k for k in cond if k in COMPARATORS]
        if len(ops) != 1:
            raise FlowError(f"비교 연산자가 하나여야 함: {cond}")
        tv = compare(ops[0], lookup(facts, cond["fact"]), cond[ops[0]])
        if tv is TV.UNKNOWN:
            unknowns.add(cond["fact"])
        return tv
    raise FlowError(f"알 수 없는 조건식: {cond}")


def load_flow(directory: Path) -> list[Stage]:
    stages = []
    seen: set[str] = set()
    for name in STAGES:
        path = directory / f"{name}.yaml"
        if not path.exists():
            raise FlowError(f"단계 파일 없음: {path.name}")
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rules = []
        for r in doc.get("rules") or []:
            if r["id"] in seen:
                raise FlowError(f"규칙 ID 중복: {r['id']}")
            seen.add(r["id"])
            rules.append(Rule(r["id"], r["when"], r["then"], r.get("basis") or [], name))
        stages.append(
            Stage(name, int(doc.get("order", 0)), rules, doc.get("on_no_match", "continue"))
        )
    return sorted(stages, key=lambda s: s.order)


def apply_then(then: Any, trace: list[dict]) -> Result | None:
    if then == "continue" or then is None:
        return None
    if not isinstance(then, dict) or then.get("outcome") not in OUTCOMES:
        raise FlowError(f"then 형식 오류: {then}")
    return Result(then["outcome"], then.get("code"), list(then.get("flags") or []), trace=trace)


def run(stages: list[Stage], facts: dict) -> Result:
    trace: list[dict] = []
    for stage in stages:
        decided = False
        for rule in stage.rules:
            unknowns: set[str] = set()
            tv = evaluate(rule.when, facts, unknowns)
            if tv is TV.TRUE:
                trace.append(
                    {
                        "stage": stage.name,
                        "rule": rule.id,
                        "basis": [b.get("unit") for b in rule.basis],
                    }
                )
                result = apply_then(rule.then, trace)
                if result is not None:
                    return result
                decided = True
                break
            if tv is TV.UNKNOWN:
                trace.append({"stage": stage.name, "rule": rule.id, "blocked": sorted(unknowns)})
                return Result("INSUFFICIENT_INFO", blocking_facts=sorted(unknowns), trace=trace)
        if not decided:
            result = apply_then(
                stage.on_no_match, trace + [{"stage": stage.name, "rule": "on_no_match"}]
            )
            if result is not None:
                return result
    return Result("INSUFFICIENT_INFO", trace=trace + [{"error": "모든 단계를 통과함(규칙 누락)"}])
