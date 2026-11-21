"""법령 검색(BM25) 단위 검사와 평가셋 회귀 하한."""

import sys
from pathlib import Path

import yaml

from app.llm.law_search import LawIndex, structure_tags, tokenize
from app.llm.tools import law_units

ROOT = Path(__file__).resolve().parents[1]


def ids(query: str) -> list[str]:
    return [u["id"] for u in LawIndex(law_units()).search(query, 3)]


def test_tokenize_keeps_article_numbers_and_codes():
    toks = tokenize("폐기물관리법 제2조제1호 51-03-01 R-3-3")
    assert {"제2조", "제1호", "51-03-01", "r-3-3"} <= set(toks)


def test_tokenize_strips_endings_and_question_words():
    assert tokenize("폐기물이 뭐예요?") == tokenize("폐기물")
    assert tokenize("납") == ["납"]


def test_structure_tags_from_layout_only():
    units = {u["id"]: u for u in law_units()}
    assert structure_tags(units["ACT-WASTE/제2조제1호"]) == "정의"
    assert "분류번호" in structure_tags(units["RULE-WASTE/별표4/51-03-01"])
    assert structure_tags(units["ACT-WASTE/제3조"]) == ""


def test_definition_and_code_queries():
    assert "ACT-WASTE/제2조제1호" in ids("폐기물 정의")
    assert ids("폐합성수지류 분류번호")[0] == "RULE-WASTE/별표4/51-03-01"
    assert ids("폐유 기름성분 5퍼센트")[0] == "DEC-WASTE/별표1제6호"


def test_out_of_corpus_query_returns_nothing():
    assert ids("용출 기준") == []
    assert ids("근로기준법 연차휴가") == []


def test_dev_eval_floor():
    """dev 지표가 이 아래로 떨어지면 검색 방식이 나빠진 것. test 쪽은 여기서 보지 않는다."""
    sys.path.insert(0, str(ROOT / "tools"))
    import eval_law_search as ev

    spec = yaml.safe_load((ROOT / "knowledge/law/search_eval.yaml").read_text(encoding="utf-8"))
    row = ev.summarize(ev.evaluate(ev.current(law_units()), spec["queries"])[0])
    assert float(row["Hit@3"]) >= 0.85
    assert float(row["빈 결과 정답률"]) >= 0.8
