"""설명 자료 색인: 추출 AI가 사용자 질문과 관련된 자료를 '뜻으로' 고르게 하는 짧은 목록.

AI는 이 목록의 id만 고를 수 있다(guard가 검사). 실제 내용은 코드가 id로 가져온다
(app/agent/assist.py). 단어가 겹치지 않는 질문(예: "옛날 변압기에 든 독한 기름")도 자료를 찾게 한다.
"""

from __future__ import annotations

from app.rules.model import KnowledgeBase

FACT, TOPIC, TERM = "fact:", "topic:", "term:"


def guide_index(kb: KnowledgeBase) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    facts = kb.question_guide.get("facts") or {}
    for key, g in facts.items():
        fd = kb.catalog.get(key)
        label = (fd.label if fd else None) or key
        what = str(g.get("what") or "")[:60]
        out.append({"id": FACT + key, "about": f"{label}: {what}"})
    for name, tp in (kb.question_guide.get("topics") or {}).items():
        kws = ", ".join(tp.get("keywords") or [])
        out.append({"id": TOPIC + name, "about": f"{name}" + (f" ({kws})" if kws else "")})
    for e in kb.glossary:
        alias = f" ({', '.join(e.aliases)})" if e.aliases else ""
        out.append({"id": TERM + e.term, "about": f"{e.term}{alias}"})
    return out


def index_ids(kb: KnowledgeBase) -> set[str]:
    return {x["id"] for x in guide_index(kb)}
