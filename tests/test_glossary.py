"""용어집: 전문용어의 쉬운 설명(knowledge/glossary.yaml)이 질문 카드와 검토 카드에 붙는다."""

from __future__ import annotations

import pytest

from app.rules.glossary import GlossaryEntry, find_terms, parse_glossary
from app.rules.loader import RuleDataError
from tools import review_kit


def test_real_glossary_loads(real_kb):
    terms = {e.term for e in real_kb.glossary}
    assert {"지정폐기물", "용출", "고형물함량", "PCB", "배출시설"} <= terms
    assert all(e.plain for e in real_kb.glossary)


def test_find_terms_uses_aliases_and_longest_match():
    g = (
        GlossaryEntry("폐유", "기름 폐기물"),
        GlossaryEntry("유기용제", "용제", aliases=("폐유기용제",)),
        GlossaryEntry("수분함량", "물 비율", aliases=("함수율",)),
    )
    found = [e.term for e in find_terms(g, "폐유기용제의 함수율")]
    assert found == ["유기용제", "수분함량"]  # '폐유기용제' 안의 '폐유'는 따로 잡지 않는다


def test_plain_is_required():
    with pytest.raises(RuleDataError, match="plain"):
        parse_glossary({"terms": {"용출": {"example": "x"}}})


def test_question_card_carries_terms(real_kb):
    from app.domain.verdict import question_view
    from app.rules.selector import QuestionChoice

    fd = real_kb.catalog["sludge_water_pct"]
    q = QuestionChoice(
        unit="fact",
        key=fd.key,
        facts=[fd.key],
        reason="test",
        question_hint=fd.question_hint,
        help=fd.help,
        value_options=[],
        score_breakdown=[],
    )
    terms = {t.term: t.plain for t in question_view(real_kb, q, {}).terms}
    assert "오니" in terms and "수분함량" in terms


def test_review_cards_have_glossary_row():
    cards = {c["unit"]: c for c in review_kit.all_cards(review_kit.Knowledge())}
    rows = dict(cards["S3-8GA-PCB-LIQUID"]["rows"])
    assert any(x.startswith("PCB: ") for x in rows["용어 풀이"])
