"""문진 보충 설명(assist): 왜 묻는지, 왜 이 결과인지, 용어 뜻, 문진 밖 요청.

설계: docs/design/agent-skill-harness.md. 판정에는 영향이 없어야 한다.
"""

from __future__ import annotations

from datetime import date

from app.agent.golden import normalize_extract
from app.agent.llm_client import FakeLLMClient
from app.agent.orchestrator import DiagnosisSession, QuickReply

AS_OF = date(2026, 11, 10)
PP = {"key": "material", "value": "pp", "quote": "PP"}


def _session(kb, extracts, respond=None):
    ex = FakeLLMClient(by_name={"extract": [normalize_extract(e) for e in extracts]})
    rs = FakeLLMClient(by_name={"respond": respond}) if respond is not None else None
    return DiagnosisSession(kb, extractor_llm=ex, responder_llm=rs, case_id="c1", as_of=AS_OF)


def _start_pp(kb, extra):
    s = _session(kb, [{"facts": [PP]}, *extra])
    s.seed({"emission_facility": True})
    first = s.handle(text="PP 필름 자투리예요")
    return s, first


def test_plain_answer_has_no_assist(real_kb):
    s, first = _start_pp(real_kb, [])
    assert first.assist is None


def test_why_question_explains_with_sources_and_keeps_question(real_kb):
    s, first = _start_pp(real_kb, [{"user_question": "왜 물어봐요?", "question_kind": "why"}])
    r = s.handle(text="이건 왜 물어봐요?")
    assert r.assist is not None and r.assist.intent == "why"
    assert r.assist.sources and r.assist.text  # 근거 조문이 붙는다(AI 없음 → 템플릿)
    assert "근거:" in r.assist.text
    # 판정·질문은 그대로
    assert r.branch == first.branch and r.ui.question["key"] == first.ui.question["key"]
    assert r.verdict.candidates == first.verdict.candidates
    t = s.traces[-1]
    assert t.responder["assist_intent"] == "why" and t.responder["skill_hash"]


def test_term_question_uses_glossary(real_kb):
    s, _ = _start_pp(real_kb, [{"user_question": "PCB가 뭐예요?", "question_kind": "term"}])
    r = s.handle(text="PCB가 뭐예요?")
    assert r.assist.intent == "term"
    assert any(t.term == "PCB" for t in r.assist.terms)
    assert "PCB" in r.assist.text


def test_off_topic_is_redirected(real_kb):
    s, first = _start_pp(
        real_kb, [{"user_question": "근처 업체 추천해 줘", "question_kind": "off_topic"}]
    )
    r = s.handle(text="근처 업체 추천해 줘")
    assert r.assist.intent == "off_topic" and "문진만" in r.assist.text
    assert r.ui.question["key"] == first.ui.question["key"]


def test_answer_and_question_in_one_message(real_kb):
    s, first = _start_pp(
        real_kb,
        [
            {
                "group_answer": {"group_id": "contamination_screen", "choice": "none_all"},
                "user_question": "근데 왜 물어봐요?",
                "question_kind": "why",
            }
        ],
    )
    assert first.ui.question["key"] == "contamination_screen"
    r = s.handle(text="다 없어요, 근데 왜 물어봐요?")
    assert r.ui.question["key"] != "contamination_screen"  # 답은 기록되고 다음 질문으로
    assert r.assist is not None and r.assist.intent == "why"


def test_why_result_cites_decided_rule(real_kb):
    s, _ = _start_pp(real_kb, [{"user_question": "왜 이 번호예요?", "question_kind": "why"}])
    s.handle(quick_reply=QuickReply(key="contamination_screen", kind="none_all"))
    s.handle(quick_reply=QuickReply(key="scope_screen", kind="none_all"))
    last = s.handle(quick_reply=QuickReply(key="physical_state", value="solid"))
    assert last.branch == "FINAL_REVIEW"
    r = s.handle(text="왜 이 번호예요?")
    assert r.branch == "FINAL_REVIEW" and r.verdict.waste_code == last.verdict.waste_code
    assert r.assist.sources and any("별표 4" in x.ref for x in r.assist.sources)
    assert r.assist.review == "UNVERIFIED"


def test_llm_assist_text_with_unknown_code_falls_back_to_template(real_kb):
    bad = {
        "message": "다음 질문이에요.",
        "cited_basis_ids": [],
        "assist_text": "이건 99-99-99라서 그래요.",
        "assist_cited_ids": ["S1"],
    }
    s, _ = _start_pp(real_kb, [{"user_question": "왜요?", "question_kind": "why"}])
    s.responder_llm = FakeLLMClient(by_name={"respond": [bad, bad]})
    r = s.handle(text="왜요?")
    assert "99-99-99" not in r.assist.text and "근거:" in r.assist.text
    assert any("assist:" in p for p in s.traces[-1].responder["problems"])
