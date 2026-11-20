"""질의응답 agent의 도구. 모두 읽기 전용이다(사실 기록·판정을 바꾸는 도구는 없다).

- search_law(query): 적재한 조문(knowledge/law/articles)에서 찾는다
- rule_basis(target): 질문·결과가 어느 규칙과 조문에서 나왔는지(현재 질문, 결과, 사실 키, 규칙 id)
- lookup_term(term): 용어집(knowledge/flow/glossary.yaml)과 질문 도움말(plan.yaml)
- case_state(): 지금 건의 답·질문·판정(서비스가 만든 요약을 그대로)
결과의 id(조문 단위·용어)만 답변 출처로 쓸 수 있다. 출처 대조는 app/llm/assist.py가 한다.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.engine.kb import FLOW_DIR, KB, MANIFEST

EXCERPT = 600


def _bigrams(s: str) -> set[str]:
    t = re.sub(r"\s+", "", s or "").lower()
    return {t[i : i + 2] for i in range(len(t) - 1)} or ({t} if t else set())


@lru_cache
def law_units(manifest: Path = MANIFEST) -> list[dict]:
    docs = yaml.safe_load(manifest.read_text(encoding="utf-8"))["documents"]
    out = []
    for d in docs:
        body = json.loads((manifest.parent / d["file"]).read_text(encoding="utf-8"))
        for u in body["units"]:
            out.append(
                {
                    "id": f"{d['key']}/{u['id']}",
                    "ref": f"{d.get('name') or d['key']} {u['id'].replace('/', ' ')}".strip(),
                    "text": u["text"],
                }
            )
    return out


@lru_cache
def glossary(flow_dir: Path = FLOW_DIR) -> list[dict]:
    path = flow_dir / "glossary.yaml"
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")).get("terms") or []


class Tools:
    def __init__(self, kb: KB, state: dict) -> None:
        self.kb, self.state = kb, state
        self.units = {u["id"]: u for u in law_units()}

    def run(self, name: str, arg: str | None) -> list[dict]:
        fn = {
            "search_law": self.search_law,
            "rule_basis": self.rule_basis,
            "lookup_term": self.lookup_term,
            "case_state": lambda _: [self.case_state()],
        }.get(name)
        return fn(arg or "") if fn else []

    def search_law(self, query: str) -> list[dict]:
        q = _bigrams(query)
        if not q:
            return []
        scored = []
        for u in self.units.values():
            score = len(q & _bigrams(u["ref"] + " " + u["text"][:2000])) / len(q)
            if score > 0.2:
                scored.append((score, u))
        scored.sort(key=lambda x: -x[0])
        return [
            {"id": u["id"], "type": "LAW", "ref": u["ref"], "excerpt": u["text"][:EXCERPT]}
            for _, u in scored[:3]
        ]

    def _rule_out(self, rule) -> dict:
        reasons = self.kb.outcomes.get("rule_reasons") or {}
        basis = []
        for b in rule.basis:
            unit = b.get("unit") or ""
            u = self.units.get(unit)
            basis.append(
                {
                    "id": unit,
                    "type": "LAW",
                    "ref": u["ref"] if u else unit,
                    "excerpt": b.get("quote") or (u["text"][:EXCERPT] if u else ""),
                }
            )
        return {
            "rule_id": rule.id,
            "stage": rule.stage,
            "reason": reasons.get(rule.id),
            "basis": basis,
        }

    def rule_basis(self, target: str) -> list[dict]:
        """target: current_question | result | 사실 키 | 규칙 id."""
        rules = [r for s in self.kb.stages for r in s.rules]
        target = target.strip()
        if target == "result":
            rid = self.state.get("rule_id")
            return [self._rule_out(r) for r in rules if r.id == rid]
        facts = (
            set(self.state.get("question_facts") or [])
            if target == "current_question"
            else {target}
        )
        hits = [r for r in rules if r.id == target]
        if not hits:
            hits = [r for r in rules if facts & _facts_in(r.when)]
        return [self._rule_out(r) for r in hits[:5]]

    def lookup_term(self, term: str) -> list[dict]:
        t = re.sub(r"\s+", "", term).lower()
        out = []
        for g in glossary():
            names = [g["term"], *(g.get("aliases") or [])]
            if any(
                t and (re.sub(r"\s+", "", n).lower() in t or t in re.sub(r"\s+", "", n).lower())
                for n in names
            ):
                unit = self.units.get(g.get("basis") or "")
                out.append(
                    {
                        "id": f"TERM/{g['term']}",
                        "type": "TERM",
                        "term": g["term"],
                        "plain": g["plain"],
                        "basis": g.get("basis"),
                        "ref": unit["ref"] if unit else None,
                        "excerpt": unit["text"][:EXCERPT] if unit else None,
                    }
                )
        for q in self.kb.plan.questions:
            text = " ".join(str(q.get(k) or "") for k in ("text", "help"))
            if t and len(t) >= 2 and t in re.sub(r"\s+", "", text).lower():
                out.append(
                    {"id": f"HELP/{q['id']}", "type": "HELP", "ref": q["id"], "excerpt": text}
                )
        return out[:5]

    def case_state(self) -> dict:
        return {"id": "CASE/state", "type": "CASE", **self.state}


def _facts_in(cond: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(cond, dict):
        if "fact" in cond:
            out.add(cond["fact"])
        for v in cond.values():
            out |= _facts_in(v)
    elif isinstance(cond, list):
        for c in cond:
            out |= _facts_in(c)
    return out
