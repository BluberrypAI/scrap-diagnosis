"""말 이해: 추출 AI(가짜) → 검사기 → 기록·확인 버튼. 실제 AI는 부르지 않는다."""

import pytest
from conftest import headers
from test_api import PP_SCRAP, new_case, reply, run_answers

from app.llm.client import FakeLLMClient

H = headers()


def said(intent="answer", facts=(), none_all=False, question=None):
    return {
        "intent": intent,
        "facts": [{"key": k, "value": v, "certainty": c, "quote": q} for k, v, c, q in facts],
        "group_none_all": none_all,
        "question_text": question,
    }


@pytest.fixture
def llm(client):
    fake = FakeLLMClient()
    client.app.state.llm = fake
    return fake


def text(client, cid, msg):
    res = client.post(f"/internal/v1/cases/{cid}/diagnosis/messages", json={"text": msg}, headers=H)
    assert res.status_code == 200, res.text
    return res.json()


def test_memo_facts_skip_first_questions(client, llm):
    llm.push(
        "extract",
        said(
            facts=[("material", "pp", "stated", "PP"), ("input_form", "scrap", "stated", "자투리")]
        ),
    )
    d = new_case(client, memo="PP 사출하고 남은 자투리예요")
    turn = d["turn"]
    assert turn["ui"]["question"]["key"] == "Q-PLASTIC-KIND"
    assert turn["message"].startswith("알겠어요.")
    facts = {f["key"]: f for f in turn["ui"]["board"]["facts"]}
    assert facts["material"]["quote"] == "PP" and facts["input_form"]["value"] == "scrap"


def test_fabricated_quote_is_rejected(client, llm):
    cid = new_case(client)["case"]["id"]
    llm.push("extract", said(facts=[("material", "pe", "stated", "PE")]))
    turn = text(client, cid, "PP예요")
    assert turn["ui"]["question"]["key"] == "material"  # 기록되지 않음
    events = client.get(f"/internal/v1/cases/{cid}/trace", headers=H).json()["events"]
    understand = next(e for e in events if e["kind"] == "UNDERSTAND")
    assert understand["payload"]["rejected"][0]["reason"] == "근거 문구가 말에 없음"


def test_value_outside_catalog_and_document_fact_rejected(client, llm):
    cid = new_case(client)["case"]["id"]
    llm.push(
        "extract",
        said(
            facts=[
                ("material", "wood", "stated", "나무"),
                ("oil_pct_evidenced", "2", "stated", "2%"),
            ]
        ),
    )
    text(client, cid, "나무고 기름 2%예요")
    events = client.get(f"/internal/v1/cases/{cid}/trace", headers=H).json()["events"]
    understand = next(e for e in events if e["kind"] == "UNDERSTAND")
    reasons = {r["key"]: r["reason"] for r in understand["payload"]["rejected"]}
    assert reasons == {"material": "선택지 밖 값", "oil_pct_evidenced": "서류로만 받는 값"}


def test_guess_is_confirmed_with_buttons(client, llm):
    cid = new_case(client)["case"]["id"]
    llm.push("extract", said(facts=[("material", "pp", "guess", "아마 PP")]))
    turn = text(client, cid, "아마 PP일걸요")
    q = turn["ui"]["question"]
    assert turn["sub_branch"] == "CONFIRM_GUESS" and q["key"] == "confirm:material"
    assert [o["kind"] for o in q["options"]] == ["value", "expand", "unknown"]
    turn = reply(client, cid, "confirm:material", "pp").json()  # 예
    assert turn["ui"]["question"]["key"] == "input_form"
    fact = next(f for f in turn["ui"]["board"]["facts"] if f["key"] == "material")
    assert fact["status"] == "CLAIMED" and fact["quote"] == "아마 PP"


def test_guess_rejected_returns_to_original_question(client, llm):
    cid = new_case(client)["case"]["id"]
    llm.push("extract", said(facts=[("material", "pp", "guess", "아마 PP")]))
    text(client, cid, "아마 PP일걸요")
    turn = reply(client, cid, "confirm:material", kind="expand").json()  # 아니요
    assert turn["ui"]["question"]["key"] == "material" and turn["sub_branch"] is None


def test_spoken_contamination_clear_needs_button(client, llm):
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, PP_SCRAP[:4])
    llm.push("extract", said(facts=[("oil_presence", "none", "stated", "기름은 안 묻었어요")]))
    turn = text(client, cid, "기름은 안 묻었어요")
    assert turn["ui"]["question"]["key"] == "confirm:oil_presence"
    assert turn["ui"]["question"]["text"].startswith("확인할게요.")
    turn = reply(client, cid, "confirm:oil_presence", "none").json()
    assert "oil_presence" not in turn["ui"]["question"]["facts"]


def test_spoken_none_all(client, llm):
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, PP_SCRAP[:2])
    llm.push("extract", said(none_all=True))
    turn = text(client, cid, "둘 다 아니에요")  # 발포·어망 묶음은 말로 받는다
    assert turn["ui"]["question"]["key"] == "packaging_used"
    reply(client, cid, "packaging_used", "no")
    llm.push("extract", said(none_all=True))
    turn = text(client, cid, "다 해당 없어요")  # 오염 묶음은 버튼으로 다시 확인
    assert turn["ui"]["question"]["key"] == "Q-CONTAMINATION"
    assert "버튼으로 한 번 더" in turn["message"]


def test_identifiers_are_masked_before_ai(client, llm):
    cid = new_case(client)["case"]["id"]
    llm.push("extract", said(facts=[("material", "pp", "stated", "PP")]))
    text(client, cid, "PP예요. 연락은 010-1234-5678로 주세요")
    sent = next(c for c in reversed(llm.calls) if c.name == "extract").user
    assert "010-1234-5678" not in sent and "[전화번호]" in sent
    events = client.get(f"/internal/v1/cases/{cid}/trace", headers=H).json()["events"]
    call = next(e for e in events if e["kind"] == "LLM")["payload"]
    assert call["user"] == "" and call["user_sha256"]  # 기본은 프롬프트 원문을 남기지 않는다


def test_off_topic_and_failure(client, llm):
    cid = new_case(client)["case"]["id"]
    llm.push("extract", said(intent="off_topic"))
    turn = text(client, cid, "근처 업체 추천해 줘")
    assert "문진만" in turn["message"] and turn["ui"]["question"]["key"] == "material"
    llm.push("extract", lambda s, u: {"intent": 1})  # 형식이 깨진 응답
    turn = text(client, cid, "??")
    assert turn["ui"]["question"]["key"] == "material"


def test_without_llm_buttons_still_work(client):
    cid = new_case(client)["case"]["id"]
    turn = text(client, cid, "PP예요")
    assert "버튼" in turn["message"] and turn["ui"]["question"]["key"] == "material"


def test_question_phrasing_changes_message_only(client, llm):
    from app.llm import phrase

    phrase._cache.clear()
    llm.push("phrase", {"text": "어떤 재질로 만든 건가요? 제품 표시를 보면 알 수 있어요."})
    llm.push("extract", said(facts=[]))
    cid = new_case(client)["case"]["id"]
    turn = text(client, cid, "음")
    q = turn["ui"]["question"]
    assert q["text"] == "어떤 재질인가요?"  # 카드 문장은 고정
    assert "어떤 재질로 만든 건가요?" in turn["message"]


def test_phrasing_with_new_numbers_is_dropped(client, llm):
    from app.llm import phrase

    phrase._cache.clear()
    cid = new_case(client)["case"]["id"]
    llm.push("extract", said(facts=[("material", "pp", "stated", "PP")]))
    llm.push("phrase", {"text": "기름성분이 3% 넘나요?"})  # 원문에 없는 숫자
    turn = text(client, cid, "PP예요")
    assert "3%" not in turn["message"]
