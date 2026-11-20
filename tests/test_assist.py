"""질의응답 agent(가짜 모델): 도구 선택 반복, 호출 상한, 출처 대조. 판정은 바뀌지 않는다."""

import json

import pytest
from conftest import headers
from test_api import PP_SCRAP, new_case, run_answers
from test_understand import said, text

from app.engine.kb import load_kb
from app.llm.client import FakeLLMClient
from app.llm.tools import Tools

H = headers()


def tool(name, arg=None):
    return {
        "action": "tool",
        "tool": name,
        "arg": arg,
        "answer": None,
        "source_ids": [],
        "terms": [],
    }


def answer(text_, ids=(), terms=()):
    return {
        "action": "answer",
        "tool": None,
        "arg": None,
        "answer": text_,
        "source_ids": list(ids),
        "terms": list(terms),
    }


@pytest.fixture
def llm(client):
    fake = FakeLLMClient()
    client.app.state.llm = fake
    return fake


def to_contamination(client):
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, PP_SCRAP[:5])
    return cid


def test_agent_picks_tools_and_cites_only_found_sources(client, llm):
    cid = to_contamination(client)
    llm.push("extract", said(intent="question", question="기름 5% 넘으면 어떻게 돼요?"))
    llm.push("assist", tool("rule_basis", "current_question"))
    llm.push("assist", tool("search_law", "폐유 기름성분 5퍼센트"))
    llm.push(
        "assist",
        answer(
            "기름성분이 5% 이상이면 폐유(지정폐기물)에 해당할 수 있어요.",
            ids=["DEC-WASTE/별표1제6호", "MADE-UP/제99조"],
        ),
    )
    turn = text(client, cid, "기름 5% 넘으면 어떻게 돼요?")
    a = turn["assist"]
    assert a["text"].startswith("기름성분이 5% 이상")
    assert [s["id"] for s in a["sources"]] == ["DEC-WASTE/별표1제6호"]  # 지어낸 출처는 빠진다
    assert a["review"] == "UNVERIFIED"
    assert turn["ui"]["question"]["key"] == "Q-CONTAMINATION"  # 질문 카드는 그대로
    assert not any(f["key"] == "oil_presence" for f in turn["ui"]["board"]["facts"])
    conv = client.get(f"/internal/v1/cases/{cid}", headers=H).json()["conversation"]
    assert conv[-1]["assist"] == a
    events = client.get(f"/internal/v1/cases/{cid}/trace", headers=H).json()["events"]
    used = next(e for e in events if e["kind"] == "ASSIST")["payload"]["tools"]
    assert [u["tool"] for u in used] == ["rule_basis", "search_law"]


def test_tool_call_cap_forces_answer(client, llm):
    cid = to_contamination(client)
    llm.push("extract", said(intent="question", question="왜요?"))
    for _ in range(4):
        llm.push("assist", tool("search_law", "기름"))
    turn = text(client, cid, "왜요?")
    assist_calls = [c for c in llm.calls if c.name == "assist"]
    assert len(assist_calls) == 4  # 도구 3번 + 답할 기회 1번
    assert json.loads(assist_calls[-1].user)["남은 도구 호출"] == 0
    assert turn["assist"] is None and "자료를 찾지 못했어요" in turn["message"]


def test_term_question_returns_plain_explanation(client, llm):
    cid = to_contamination(client)
    llm.push("extract", said(intent="question", question="노말헥산이 뭐예요?"))
    llm.push("assist", tool("lookup_term", "노말헥산"))
    llm.push(
        "assist",
        answer(
            "성적서에서 기름성분을 재는 항목이에요.",
            ids=["TERM/노말헥산 추출물질"],
            terms=["노말헥산 추출물질"],
        ),
    )
    a = text(client, cid, "노말헥산이 뭐예요?")["assist"]
    assert a["terms"][0]["term"] == "노말헥산 추출물질"
    assert a["sources"] == []  # 적재한 법령에 정의가 없는 용어는 법 출처를 붙이지 않는다


def test_answer_and_question_in_one_message(client, llm):
    cid = new_case(client)["case"]["id"]
    llm.push(
        "extract",
        said(facts=[("material", "pp", "stated", "PP")], question="근데 재질은 왜 물어봐요?"),
    )
    llm.push("assist", tool("rule_basis", "COD-RESIN-NONPACKAGING"))
    llm.push(
        "assist", answer("재질에 따라 분류번호가 달라져요.", ids=["RULE-WASTE/별표4/51-03-01"])
    )
    turn = text(client, cid, "PP예요. 근데 재질은 왜 물어봐요?")
    assert turn["ui"]["question"]["key"] == "input_form"  # 답은 기록되고 다음 질문
    assert turn["assist"]["sources"][0]["id"] == "RULE-WASTE/별표4/51-03-01"


def test_tools_are_read_only_lookups():
    kb = load_kb()
    t = Tools(kb, {"question_facts": ["oil_presence"], "rule_id": "COD-RESIN-NONPACKAGING"})
    law = t.search_law("기름성분 5퍼센트 폐유")
    assert law[0]["id"] == "DEC-WASTE/별표1제6호"
    rules = {r["rule_id"] for r in t.rule_basis("current_question")}
    assert {"DES-OIL-UNKNOWN", "DES-OIL-NO-EVIDENCE"} <= rules
    assert t.rule_basis("result")[0]["basis"][0]["id"] == "RULE-WASTE/별표4/51-03-01"
    terms = t.lookup_term("성적서")
    assert terms[0]["term"] == "시험성적서" and terms[0]["basis"] == "RULE-WASTE/제17조의2"
    assert t.run("unknown_tool", "x") == []
