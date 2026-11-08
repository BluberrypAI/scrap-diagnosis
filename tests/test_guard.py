"""LLM 출력 검증(guard) — 추출과 응답."""

from app.agent.golden import normalize_extract
from app.agent.guard import validate_extraction, validate_response
from app.domain.facts import FactStatus
from app.domain.ranges import NumRange
from app.rules.selector import QuestionChoice, ValueOption


def q_fact(key, options=()):
    return QuestionChoice(
        unit="fact",
        key=key,
        facts=[key],
        reason="MISSING",
        question_hint=key,
        value_options=[ValueOption(label=str(o), value=o) for o in options],
        score_breakdown=[],
    )


def run(kb, extract, text, last=None):
    return validate_extraction(
        kb, normalize_extract(extract), text, last_question=last, message_id="m1"
    )


def test_valid_enum_and_bool(kb):
    r = run(
        kb,
        {
            "facts": [
                {"key": "material", "value": "PP", "quote": "PP"},
                {"key": "pcb_related", "value": False, "quote": "PCB 없어요"},
            ]
        },
        "PP이고 PCB 없어요",
    )
    assert [(f.key, f.value) for f in r.facts] == [("material", "PP"), ("pcb_related", False)]
    assert all(f.status == FactStatus.CLAIMED and f.source_ref == "m1" for f in r.facts)


def test_unknown_key_and_missing_quote_rejected(kb):
    r = run(
        kb,
        {
            "facts": [
                {"key": "color", "value": "red", "quote": "빨강"},
                {"key": "material", "value": "PP", "quote": "폴리프로필렌"},
            ]
        },
        "빨간 PP예요",
    )
    assert r.facts == []
    reasons = {x["reason"] for x in r.rejected}
    assert "카탈로그에 없는 사실 키" in reasons and "quote가 사용자 발화에 없음" in reasons


def test_invented_number_rejected(kb):
    r = run(
        kb,
        {"facts": [{"key": "oil_content_pct", "value": 3, "quote": "기름이 좀 있어요"}]},
        "기름이 좀 있어요",
    )
    assert r.facts == [] and "지어낸 숫자" in r.rejected[0]["reason"]


def test_number_and_range(kb):
    r = run(
        kb,
        {"facts": [{"key": "oil_content_pct", "value": 2.5, "quote": "2.5%"}]},
        "유분 2.5%입니다",
    )
    assert r.facts[0].value == 2.5
    r = run(
        kb,
        {
            "facts": [
                {"key": "oil_content_pct", "value": {"hi": 5, "hi_inc": False}, "quote": "5% 미만"}
            ]
        },
        "5% 미만이에요",
    )
    assert r.facts[0].value == NumRange(hi=5, hi_inc=False)


def test_vague_statement_keeps_note_without_value(kb):
    r = run(
        kb,
        {
            "facts": [
                {
                    "key": "oil_content_pct",
                    "status": "UNKNOWN",
                    "note": "조금",
                    "quote": "기름은 좀 있는데",
                }
            ]
        },
        "기름은 좀 있는데",
    )
    (f,) = r.facts
    assert f.value is None and f.status == FactStatus.UNKNOWN and f.note == "조금"


def test_declared_unknown_only_for_last_question(kb):
    ex = {"facts": [{"key": "oil_content_pct", "status": "DECLARED_UNKNOWN", "quote": "몰라"}]}
    assert run(kb, ex, "몰라").facts == []
    r = run(kb, ex, "몰라", last=q_fact("oil_content_pct"))
    assert r.facts[0].status == FactStatus.DECLARED_UNKNOWN


def test_internal_fact_only_from_offered_options(real_kb):
    ex = {"facts": [{"key": "annex4_code", "value": "09-01-00", "quote": "09-01-00"}]}
    assert (
        validate_extraction(
            real_kb, normalize_extract(ex), "09-01-00이요", last_question=None, message_id="m"
        ).facts
        == []
    )
    last = q_fact("annex4_code", ["09-02-00"])
    r = validate_extraction(
        real_kb, normalize_extract(ex), "09-01-00이요", last_question=last, message_id="m"
    )
    assert r.facts == [] and r.rejected[0]["reason"] == "제시한 선택지에 없는 값"


def test_code_claim_must_be_in_text(kb):
    assert run(kb, {"user_code_claim": "SAMPLE-A"}, "SAMPLE-A 맞죠").user_code_claim == "SAMPLE-A"
    assert run(kb, {"user_code_claim": "SAMPLE-B"}, "코드 알려줘").user_code_claim is None


def test_group_answer_only_for_last_group(kb):
    g = QuestionChoice(
        unit="group",
        key="contamination_screen",
        facts=["pcb_related", "hazardous_residue"],
        reason="MISSING",
        question_hint="?",
        value_options=[],
        score_breakdown=[],
    )
    ex = {"group_answer": {"group_id": "contamination_screen", "choice": "none_all"}}
    assert run(kb, ex, "다 없어요").group_answer is None
    assert run(kb, ex, "다 없어요", last=g).group_answer["choice"] == "none_all"


def test_response_guard():
    payload_text = '{"verdict": {"code": "51-03-01"}, "basis": [{"id": "B1"}], "pct": 5}'
    ok = validate_response(
        "분류번호는 51-03-01입니다. 기준은 5%입니다.", ["B1"], {}, payload_text, {"B1"}
    )
    assert ok == []
    bad = validate_response(
        "02-01-01일 수도 있습니다. 3% 넘나요? 맞나요?", ["B9"], {}, payload_text, {"B1"}
    )
    joined = " ".join(bad)
    assert "02-01-01" in joined and "숫자 3" in joined and "질문이 둘 이상" in joined
    assert "B9" in joined
