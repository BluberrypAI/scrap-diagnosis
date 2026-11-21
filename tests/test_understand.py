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


def test_spoken_contamination_clears_confirmed_once_as_group(client, llm):
    """말로 한 오염 '없음'은 항목마다 따로 묻지 않고 묶음 확인 한 번으로 받는다."""
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, PP_SCRAP[:5])
    msg = "안 묻었어 깨끗하게 세척함"
    llm.push(
        "extract",
        said(
            facts=[
                ("oil_presence", "none", "stated", "안 묻었어"),
                ("residue", "none", "stated", "깨끗하게 세척함"),
            ]
        ),
    )
    turn = text(client, cid, msg)
    q = turn["ui"]["question"]
    assert turn["sub_branch"] == "CONFIRM_GROUP" and q["key"] == "Q-CONTAMINATION"
    assert q["facts"] == ["oil_presence", "residue", "chemical_itself"]  # 기록하지 않고 같이 확인
    assert (
        q["text"].startswith("'안 묻었어'라고 하셨어요.")
        and "모두 해당 없는 게 맞나요" in q["text"]
    )
    assert "버튼으로 한 번 더" not in turn["message"]
    turn = reply(client, cid, "Q-CONTAMINATION", kind="none_all").json()  # 한 번에 끝
    assert turn["sub_branch"] is None
    assert not {"oil_presence", "residue", "chemical_itself"} & set(turn["ui"]["question"]["facts"])
    facts = {f["key"]: f["value"] for f in turn["ui"]["board"]["facts"]}
    assert facts["oil_presence"] == "none" and facts["chemical_itself"] == "no"


def group_confirm_card(client, llm):
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, PP_SCRAP[:5])
    llm.push("extract", said(facts=[("oil_presence", "none", "stated", "안 묻었어")]))
    turn = text(client, cid, "안 묻었어")
    assert turn["sub_branch"] == "CONFIRM_GROUP"
    return cid


@pytest.mark.parametrize("msg", ["응", "네 맞아요.", "없어요"])
def test_short_yes_on_group_confirm_clears_all(client, llm, msg):
    """묶음 확인에 말로 '응'이라고 하면 모두 해당 없음으로 끝난다(AI 부르지 않음, 반복 안 함)."""
    cid = group_confirm_card(client, llm)
    calls = len(llm.calls)
    turn = text(client, cid, msg)
    assert len(llm.calls) == calls  # 짧은 예/아니요는 AI로 보내지 않는다
    assert turn["sub_branch"] is None and turn["ui"]["question"]["key"] != "Q-CONTAMINATION"
    facts = {f["key"]: f["value"] for f in turn["ui"]["board"]["facts"]}
    assert facts["oil_presence"] == "none" and facts["residue"] == "none"
    assert facts["chemical_itself"] == "no"
    assert turn["message"].startswith("알겠어요. 모두 해당 없음")


def test_spoken_yes_via_ai_on_group_confirm_clears_all(client, llm):
    cid = group_confirm_card(client, llm)
    llm.push("extract", said(none_all=True))
    turn = text(client, cid, "응 그거 다 아니야")
    assert turn["sub_branch"] is None and turn["ui"]["question"]["key"] != "Q-CONTAMINATION"
    facts = {f["key"]: f["value"] for f in turn["ui"]["board"]["facts"]}
    assert facts["chemical_itself"] == "no"


@pytest.mark.parametrize("msg", ["아니", "있어요", "모르겠어요"])
def test_short_no_on_group_confirm_asks_items(client, llm, msg):
    cid = group_confirm_card(client, llm)
    turn = text(client, cid, msg)
    q = turn["ui"]["question"]
    assert turn["sub_branch"] is None and q["group"] == "Q-CONTAMINATION"  # 항목별로 묻는다
    assert "oil_presence" not in {f["key"] for f in turn["ui"]["board"]["facts"]}


def test_short_yes_on_guess_confirm(client, llm):
    cid = new_case(client)["case"]["id"]
    llm.push("extract", said(facts=[("material", "pp", "guess", "아마 PP")]))
    text(client, cid, "아마 PP일걸요")
    turn = text(client, cid, "네")
    assert turn["ui"]["question"]["key"] == "input_form"


def test_spoken_contamination_clear_from_memo_waits_for_group_turn(client, llm):
    """메모에서 미리 말한 '없음'은 앞 질문을 막지 않고, 오염 묶음 차례에 한 번 확인한다."""
    llm.push(
        "extract",
        said(
            facts=[
                ("material", "pp", "stated", "PP"),
                ("oil_presence", "none", "stated", "기름 안 묻음"),
            ]
        ),
    )
    d = new_case(client, memo="PP 자투리, 기름 안 묻음")
    turn = d["turn"]
    assert turn["sub_branch"] is None and not turn["ui"]["question"]["key"].startswith("confirm:")
    cid, answers = d["case"]["id"], dict(PP_SCRAP)
    for _ in range(10):
        key = turn["ui"]["question"]["key"]
        if key == "Q-CONTAMINATION":
            break
        turn = reply(client, cid, key, answers[key]).json()
    assert turn["sub_branch"] == "CONFIRM_GROUP"
    assert turn["ui"]["question"]["text"].startswith("'기름 안 묻음'라고 하셨어요.")


def test_spoken_none_all(client, llm):
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, PP_SCRAP[:3])
    llm.push("extract", said(none_all=True))
    turn = text(client, cid, "둘 다 아니에요")  # 발포·어망 묶음은 말로 받는다
    assert turn["ui"]["question"]["key"] == "packaging_used"
    reply(client, cid, "packaging_used", "no")
    llm.push("extract", said(none_all=True))
    turn = text(client, cid, "다 해당 없어요")  # 오염 묶음은 묶음 확인 한 번
    assert turn["ui"]["question"]["key"] == "Q-CONTAMINATION"
    assert turn["sub_branch"] == "CONFIRM_GROUP"
    assert turn["ui"]["question"]["text"].startswith("'다 해당 없어요'라고 하셨어요.")


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
