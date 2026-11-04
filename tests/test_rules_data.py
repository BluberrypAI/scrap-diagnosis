"""규칙 표 자체의 검증: 인용문이 원문에 그대로 있는지, 표 형식이 맞는지."""
import re

import fitz
import pytest

from wastecalc.kb import ROOT, load_kb

KB = load_kb()
_cache: dict[str, str] = {}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _text(source_id: str) -> str:
    if source_id not in _cache:
        path = ROOT / KB.sources[source_id]["path"]
        _cache[source_id] = _norm("".join(p.get_text() for p in fitz.open(path)))
    return _cache[source_id]


def _all_quotes():
    for r in KB.rules:
        yield r.id, r.source, r.quote
        for s in r.supporting:
            yield f"{r.id}/supporting", s["source"], s["quote"]
    for fid, f in KB.facts.items():
        for h in f.get("how_to_check", []):
            if "source" in h:
                yield f"{fid}/how_to_check", h["source"], h["quote"]
        note = f.get("note") or {}
        if note.get("source"):
            yield f"{fid}/note", note["source"], note["quote"]


QUOTES = list(_all_quotes())


@pytest.mark.parametrize("item,source,quote", QUOTES, ids=[q[0] for q in QUOTES])
def test_quote_matches_source(item, source, quote):
    src = KB.sources[source]
    if src["verify"] == "manual":
        assert src.get("manual_check"), f"{source}: 육안 대조 기록이 없습니다"
        pytest.skip(f"PDF 텍스트 층이 깨진 자료 — {src['manual_check']}")
    assert _norm(quote) in _text(source), f"{item}: 인용문이 {source} 원문에 없습니다"


def test_every_rule_has_quote_and_version():
    for r in KB.rules:
        assert r.quote.strip(), r.id
        assert KB.sources[r.source].get("version"), r.id


def test_only_current_sources_used_for_rules():
    for r in KB.rules:
        assert KB.sources[r.source]["version_status"] in {"CURRENT", "NOT_APPLICABLE"}, r.id
