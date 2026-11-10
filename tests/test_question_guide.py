"""질문 안내(knowledge/question_guide.yaml): 모든 문진 질문·선택지에 설명이 있다.

보충 설명이 이를 쓰고, 자료가 없을 때만 웹 검색(허용 도메인, 기본 꺼짐)으로 넘어간다.
"""

from __future__ import annotations

from datetime import date

from app.agent.assist import build_context
from app.agent.golden import normalize_extract
from app.agent.llm_client import FakeLLMClient
from app.agent.orchestrator import DiagnosisSession
from app.agent.web_search import WebResult, allowed, safe_query

AS_OF = date(2026, 11, 11)
NOT_ASKED = {"material", "annex4_code"}  # 소재는 소재 목록·분류 설명, 번호는 별표 4 명칭으로 설명


def test_every_question_and_option_has_guide(real_kb):
    facts = real_kb.question_guide["facts"]
    missing, no_opt = [], []
    for key, fd in real_kb.catalog.items():
        if fd.internal or key in NOT_ASKED:
            continue
        g = facts.get(key)
        if not g or not g.get("what") or not g.get("why"):
            missing.append(key)
            continue
        opts = g.get("options") or {}
        if fd.type == "enum":
            no_opt += [f"{key}.{v}" for v in fd.values or () if v not in opts]
        elif fd.type == "bool":
            no_opt += [f"{key}.{v}" for v in ("true", "false") if v not in opts]
    assert not missing, f"설명이 없는 질문: {missing}"
    assert not no_opt, f"설명이 없는 선택지: {no_opt}"


class FakeWeb:
    def __init__(self, results):
        self.results = results
        self.queries: list[str] = []

    def search(self, query, limit=3):
        self.queries.append(query)
        return [r for r in self.results if allowed(r.url)][:limit]


def _session(kb, extracts, web=None):
    ex = FakeLLMClient(by_name={"extract": [normalize_extract(e) for e in extracts]})
    s = DiagnosisSession(kb, extractor_llm=ex, case_id="c1", as_of=AS_OF)
    s.web_search = web
    s.seed({"emission_facility": True})
    s.handle(text="PP 필름 자투리예요")
    return s


PP = {"facts": [{"key": "material", "value": "pp", "quote": "PP"}]}


def test_term_question_answers_from_guide_without_web(real_kb):
    web = FakeWeb([WebResult(title="x", url="https://www.law.go.kr/x")])
    s = _session(real_kb, [PP, {"user_question": "pH가 뭐예요?", "question_kind": "term"}], web)
    r = s.handle(text="pH가 뭐예요?")
    assert r.assist.intent == "term" and r.assist.text
    assert web.queries == []  # 용어집에 있으므로 웹 검색하지 않음
    assert s.traces[-1].responder["assist_matched"] is True
    found = s.traces[-1].responder["assist_found"]  # 찾은 자료 전체가 Trace에 남는다
    assert found["intent"] == "term" and found["terms"]


def test_web_search_only_when_no_material_and_only_allowed_domains(real_kb):
    web = FakeWeb(
        [
            WebResult(title="블로그", url="https://blog.example.com/a", snippet="광고"),
            WebResult(title="법령", url="https://www.law.go.kr/법령/폐기물관리법", snippet="…"),
        ]
    )
    q = {"user_question": "폐기물 보관 창고는 몇 평이어야 해요?", "question_kind": "term"}
    s = _session(real_kb, [PP, q], web)
    r = s.handle(text="폐기물 보관 창고는 몇 평이어야 해요?")
    assert web.queries  # 준비된 자료가 없어 검색함
    webs = [x for x in r.assist.sources if x.type == "WEB"]
    assert [x.url for x in webs] == ["https://www.law.go.kr/법령/폐기물관리법"]
    assert "공식 자료" in r.assist.text
    assert s.traces[-1].responder["assist_web"] is True
    assert r.ui.question["key"] == "contamination_screen"  # 판정·질문은 그대로


def test_guide_context_has_options_and_faq(real_kb):
    s = _session(real_kb, [PP])
    step = s.peek()
    ctx = build_context(real_kb, step, s.rule_index, "term", "어떤 기름이 해당돼요?")
    labels = {g["label"] for g in ctx.guide}
    assert "기름 묻음·섞임" in labels  # 묶음 질문의 구성 사실마다 안내가 붙는다
    oil = next(g for g in ctx.guide if g["label"] == "기름 묻음·섞임")
    assert oil["options"] and oil["what"]


def test_safe_query_blocks_identifiers():
    assert safe_query("PCB 변압기 처리") == "PCB 변압기 처리"
    assert safe_query("010-1234-5678로 연락 주세요") is None or "1234" not in safe_query(
        "010-1234-5678로 연락 주세요"
    )


def test_ai_chosen_material_answers_question_without_shared_words(real_kb):
    """단어가 겹치지 않는 질문도 추출 AI가 뜻으로 고른 자료 id로 답한다(목록 밖 id는 버림)."""
    q = "옛날 전기 설비에 든 독한 기름 있잖아요, 그거 뭐예요?"
    web = FakeWeb([WebResult(title="x", url="https://www.law.go.kr/x")])
    ex = {"user_question": q, "question_kind": "term", "about": ["topic:PCB", "topic:없는주제"]}
    s = _session(real_kb, [PP, ex], web)
    r = s.handle(text=q)
    found = s.traces[-1].responder["assist_found"]
    assert found["chosen"] == ["topic:PCB"]
    assert any(t["topic"] == "PCB" for t in found["topics"])
    assert web.queries == []  # 자료를 찾았으므로 웹 검색 안 함
    assert s.traces[-1].extraction["about_dropped"] == ["topic:없는주제"]  # 재시도 없이 버림
    assert r.assist.text


def test_guide_index_covers_facts_topics_terms(real_kb):
    from app.rules.guide_index import guide_index

    ids = {x["id"] for x in guide_index(real_kb)}
    assert "fact:pcb_possible" in ids and "topic:MSDS" in ids and "term:용출" in ids
