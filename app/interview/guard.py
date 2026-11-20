"""검사기: 추출 AI가 제안한 사실을 코드로 검사한다. 통과한 값만 사실로 기록된다.

검사
1. 키가 카탈로그에 있고, 서류로만 받는 사실이 아닐 것
2. 값이 선택지 안(숫자는 범위 안)일 것
3. 근거 문구(quote)가 사용자 말에 실제로 있을 것(공백·대소문자 무시). 없으면 지어낸 값으로 본다
분류
- 바로 기록: 단정한 답(stated)
- 확인 버튼으로 한 번 더(CONFIRM_GUESS): 추측한 답(guess), 그리고 말로 한 '지정폐기물 가능성을
  지우는 답'(plan.yaml에서 confirm_text: true인 묶음의 '해당 없음' 값)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.engine.kb import KB
from app.engine.planner import question_facts
from app.interview import catalog as cat
from app.llm.extract import Proposal


@dataclass
class Candidate:
    key: str
    value: object
    certainty: str
    quote: str


@dataclass
class GuardResult:
    accepted: list[Candidate] = field(default_factory=list)  # 바로 기록
    confirm: list[Candidate] = field(default_factory=list)  # 확인 버튼으로
    rejected: list[dict] = field(default_factory=list)  # {key, value, reason}
    group_none_all: str | None = None  # 바로 적용할 묶음 '모두 해당 없음'(묶음 질문 id)
    group_needs_button: str | None = None  # 말로 한 '모두 해당 없음'을 버튼으로 확인할 묶음


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def risky_clears(kb: KB) -> dict[str, str]:
    """말로 들으면 버튼으로 다시 확인할 '해당 없음' 값: {사실: 그 값}."""
    out = {}
    for q in kb.plan.questions:
        if q.get("confirm_text") and q.get("kind") == "group":
            for item in q["items"]:
                if "none" in item:
                    out[item["fact"]] = str(cat.norm(item["none"]))
    return out


def _coerce(spec: dict, value: str) -> object:
    """스키마상 문자열로 온 값을 카탈로그 타입으로."""
    if spec["type"] == "number" and value != "unknown":
        try:
            return float(value.replace(",", "").rstrip("%").strip())
        except ValueError:
            return value
    return value


def check(
    kb: KB, proposal: Proposal, text: str, question: dict | None, plan_question: dict | None
) -> GuardResult:
    catalog = kb.plan.catalog
    res = GuardResult()
    said = _squash(text)
    risky = risky_clears(kb)
    seen: set[str] = set()
    for f in proposal.facts:
        key, raw, quote = f.get("key"), f.get("value"), f.get("quote") or ""
        spec = cat.spec(catalog, key or "")
        if spec is None:
            res.rejected.append({"key": key, "value": raw, "reason": "카탈로그에 없는 사실"})
            continue
        if spec.get("source") == "document":
            res.rejected.append({"key": key, "value": raw, "reason": "서류로만 받는 값"})
            continue
        if key in seen:
            res.rejected.append({"key": key, "value": raw, "reason": "같은 사실을 두 번 냄"})
            continue
        if not quote.strip() or _squash(quote) not in said:
            res.rejected.append({"key": key, "value": raw, "reason": "근거 문구가 말에 없음"})
            continue
        try:
            value = cat.validate(catalog, key, _coerce(spec, str(raw)))
        except cat.FactValueError as e:
            res.rejected.append({"key": key, "value": raw, "reason": e.reason})
            continue
        seen.add(key)
        c = Candidate(key, value, f.get("certainty") or "stated", quote)
        needs_button = c.certainty == "guess" or (key in risky and str(value) == risky[key])
        (res.confirm if needs_button else res.accepted).append(c)
    if proposal.group_none_all and question and question.get("unit") == "group" and plan_question:
        if plan_question.get("confirm_text"):
            res.group_needs_button = plan_question["id"]
        elif not set(question_facts(plan_question)) & seen:
            res.group_none_all = plan_question["id"]
    return res
