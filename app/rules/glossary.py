"""용어집: 전문용어의 쉬운 설명(knowledge/glossary.yaml → data/real/glossary.yaml).

사람이 쓰고 전문가가 검토한 고정 설명이다(LLM이 만들지 않는다). 판정에는 쓰지 않고,
질문 카드(QuestionView.terms)와 검토 카드의 "용어 풀이"에 붙인다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

GLOSSARY_FILE = "glossary.yaml"


@dataclass(frozen=True)
class GlossaryEntry:
    term: str
    plain: str
    example: str | None = None
    aliases: tuple[str, ...] = ()
    source: str | None = None


def parse_glossary(raw: Any) -> tuple[GlossaryEntry, ...]:
    from app.rules.loader import RuleDataError  # 순환 import 방지

    terms = (raw or {}).get("terms") or {}
    out: list[GlossaryEntry] = []
    for term, item in terms.items():
        if not isinstance(item, dict) or not item.get("plain"):
            raise RuleDataError(f"glossary[{term}]: plain(쉬운 설명)이 필요합니다")
        out.append(
            GlossaryEntry(
                term=str(term),
                plain=str(item["plain"]).strip(),
                example=item.get("example"),
                aliases=tuple(str(a) for a in item.get("aliases") or ()),
                source=item.get("source"),
            )
        )
    return tuple(out)


def find_terms(glossary: tuple[GlossaryEntry, ...], *texts: str | None) -> list[GlossaryEntry]:
    """글에 나오는 용어(표기·별칭)를 처음 나온 순서로. 긴 표기부터 찾아 겹침을 막는다.

    예: "폐유기용제"는 '유기용제'로 잡히고 그 안의 '폐유'는 다시 잡지 않는다.
    """
    text = "\n".join(t for t in texts if t)
    if not text or not glossary:
        return []
    names = sorted(
        ((name, e) for e in glossary for name in (e.term, *e.aliases)),
        key=lambda x: -len(x[0]),
    )
    taken = [False] * len(text)
    first: dict[str, int] = {}
    entries: dict[str, GlossaryEntry] = {}
    for name, e in names:
        start = text.find(name)
        while start != -1:
            end = start + len(name)
            if not any(taken[start:end]):
                for i in range(start, end):
                    taken[i] = True
                if e.term not in first or start < first[e.term]:
                    first[e.term] = start
                entries[e.term] = e
            start = text.find(name, end)
    return [entries[t] for t in sorted(first, key=first.get)]
