"""다음 질문 계산기: knowledge/flow/plan.yaml의 순서대로 보면서 물어야 할 첫 질문을 고른다.

- 아직 묻지 않은 사실은 UNASKED로 두고 판정을 돌린다. 결론이 나면 더 묻지 않는다.
- 관련성 가지치기(relevance pruning): 어떤 사실이 '아직 결론이 정해지지 않은(모름) 규칙'의
  조건에 들어 있지 않으면, 그 사실은 어떤 값이어도 판정을 바꾸지 못하므로 묻지 않는다.
  3값 논리는 단조적이라(모름이 아닌 조건은 다른 사실이 정해져도 바뀌지 않음) 이 생략은 안전하다.
- 자동 채움(derive): 형태가 정해지면 물리 상태가 고체로 정해지는 등, 다른 답에서 값을 채운다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.engine.flow import TV, UNASKED, Result, Stage, evaluate, load_flow, lookup, run

ROOT = Path(__file__).resolve().parents[2]
FLOW_DIR = ROOT / "knowledge" / "flow"


@dataclass
class Plan:
    questions: list[dict]
    derive: list[dict]
    catalog: dict[str, dict]


@dataclass
class Next:
    """계산 결과: 끝났으면 result, 아니면 물을 질문."""

    done: bool
    result: Result
    question: dict | None = None
    facts: list[str] = field(default_factory=list)  # 이번 질문이 정할 사실(묶음이면 관련 항목만)


def load_plan(directory: Path = FLOW_DIR) -> Plan:
    doc = yaml.safe_load((directory / "plan.yaml").read_text(encoding="utf-8"))
    cat = yaml.safe_load((directory / "facts.yaml").read_text(encoding="utf-8"))["facts"]
    return Plan(doc["questions"], doc.get("derive") or [], {f["id"]: f for f in cat})


def all_fact_paths(plan: Plan) -> list[str]:
    paths = []
    for fid, f in plan.catalog.items():
        if f["type"] == "object":
            paths += [f"{fid}.{k}" for k in f["fields"]]
        else:
            paths.append(fid)
    return paths


def set_path(facts: dict, path: str, value: Any) -> None:
    base, _, sub = path.partition(".")
    if sub:
        obj = facts.get(base)
        if not isinstance(obj, dict):
            obj = facts[base] = {}
        obj[sub] = value
    else:
        facts[base] = value


def with_unasked(plan: Plan, answers: dict) -> dict:
    """답한 값 + 자동 채움 + 나머지는 UNASKED."""
    facts: dict = {}
    for path in all_fact_paths(plan):
        set_path(facts, path, UNASKED)
    for path, v in flatten(answers).items():
        set_path(facts, path, v)
    for d in plan.derive:
        if evaluate(d["when"], facts, set()) is TV.TRUE:
            for k, v in d["set"].items():
                if lookup(facts, k) == UNASKED:
                    set_path(facts, k, v)
    # 질문 조건(ask_if)이 거짓으로 정해지면 그 질문의 사실은 '해당 없음'(값 없음)이다.
    # 예: 기름이 없으면 분석서 기름 함량은 묻지 않고 값이 없는 것으로 둔다.
    # 조건이 '모름'이어도 그 원인이 '모른다고 답한' 사실뿐이면 더 물어도 정해지지 않으므로 같게 본다
    # (예: 캔 내용물을 모르면 '소용량 의약품인가'는 묻지 않는다).
    for q in plan.questions:
        if not q.get("ask_if"):
            continue
        unknowns: set[str] = set()
        tv = evaluate(q["ask_if"], facts, unknowns)
        settled = tv is TV.FALSE or (
            tv is TV.UNKNOWN and all(lookup(facts, u) != UNASKED for u in unknowns)
        )
        if settled:
            for f in question_facts(q):
                if lookup(facts, f) == UNASKED:
                    set_path(facts, f, None)
    return facts


def flatten(answers: dict) -> dict:
    out = {}
    for k, v in answers.items():
        if isinstance(v, dict):
            out |= {f"{k}.{sk}": sv for sk, sv in v.items()}
        else:
            out[k] = v
    return out


def unresolved_facts(stages: list[Stage], facts: dict) -> set[str]:
    """아직 참·거짓이 정해지지 않은 규칙이 기다리는(UNASKED인) 사실들."""
    needed: set[str] = set()
    for st in stages:
        for rule in st.rules:
            unknowns: set[str] = set()
            if evaluate(rule.when, facts, unknowns) is TV.UNKNOWN:
                needed |= {u for u in unknowns if lookup(facts, u) == UNASKED}
    return needed


def question_facts(q: dict) -> list[str]:
    if q.get("kind") == "group":
        return [i["fact"] for i in q["items"]]
    return [q["fact"]]


def next_question(stages: list[Stage], plan: Plan, answers: dict) -> Next:
    facts = with_unasked(plan, answers)
    result = run(stages, facts)
    blocked_on_unasked = any(lookup(facts, b) == UNASKED for b in result.blocking_facts)
    if result.outcome != "INSUFFICIENT_INFO" or not blocked_on_unasked:
        # 결론이 났거나, 막힌 이유가 '모른다고 답한' 사실뿐이면 끝
        return Next(True, result)
    needed = unresolved_facts(stages, facts)
    for q in plan.questions:
        if q.get("ask_if") and evaluate(q["ask_if"], facts, set()) is not TV.TRUE:
            continue
        # always: 판정에 필요 없어도 인계(업체 추천)에 필요한 질문은 묻는다(예: 형태)
        ask = [
            f
            for f in question_facts(q)
            if lookup(facts, f) == UNASKED and (f in needed or q.get("always"))
        ]
        if ask:
            return Next(False, result, q, ask)
    # 계획에 없는 사실로 막힘: 계획 누락. 막힌 사실을 하나씩 묻는다
    missing = [b for b in result.blocking_facts if lookup(facts, b) == UNASKED]
    return Next(
        False, result, {"id": "Q-UNPLANNED", "fact": missing[0], "kind": "single"}, missing[:1]
    )


def load(directory: Path = FLOW_DIR) -> tuple[list[Stage], Plan]:
    return load_flow(directory), load_plan(directory)
