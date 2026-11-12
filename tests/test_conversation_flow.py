"""막다른 길 없이 대화 이어 가기(2026-11-12).

- 유해화학물질: 약품이 아닌 폐기물은 "약품·시약 그 자체인가요?" 대리 질문으로
  넘어가 MSDS를 요구하지 않는다
- "서류가 없어요" 뒤에도 다시 말하면 판정 불가에 갇히지 않고 필요한 서류를 다시 안내한다
- 확인대상 폐기물의 시험 수치를 말로 답하면, 같은 안내를 반복하지 않고 왜 안 되는지와 할 일을 말한다
"""

from __future__ import annotations

from app.agent.golden import run_case
from app.rules.implications import assumption_notes

SLUDGE_START = {
    "user": "폐수처리장에서 나온 무기성 오니예요. 내보내는 폐기물이에요.",
    "extract": {
        "facts": [
            {"key": "material", "value": "sludge_ww_inorganic", "quote": "무기성 오니"},
            {"key": "material_group", "value": "sludge", "quote": "오니"},
            {"key": "material_fate", "value": "released", "quote": "내보내는"},
        ]
    },
}


def _case(turns, cid="flow"):
    return {
        "id": cid,
        "kb": "real",
        "setup": {"facts": {"emission_facility": True}},
        "turns": turns,
    }


def _turns(real_kb, turns):
    res = run_case(_case(turns), real_kb, mock_extractor=True)
    return res.turns


def test_sludge_not_a_chemical_skips_msds(real_kb):
    turns = _turns(
        real_kb,
        [
            SLUDGE_START,
            {"quick_reply": {"key": "contamination_screen", "kind": "expand"}},
            {"quick_reply": {"key": "designated_residue", "kind": "value", "value": False}},
            {"quick_reply": {"key": "oil_presence", "kind": "unknown"}},
            {"quick_reply": {"key": "pcb_possible", "kind": "value", "value": False}},
            {"quick_reply": {"key": "chemical_itself", "kind": "value", "value": False}},
            {"quick_reply": {"key": "scope_screen", "kind": "none_all"}},
            {"quick_reply": {"key": "sludge_facility_notified", "kind": "value", "value": True}},
        ],
    )
    asked = [t.got.get("ask_fact") for t in turns]
    assert "toxic_chemical_discard" not in asked
    last = turns[-1].got
    assert last["branch"] == "REQUEST_EVIDENCE"
    assert last["documents"] == ["TEST_REPORT"]  # MSDS는 요구하지 않는다


def test_chemical_itself_yes_asks_toxic_directly(real_kb):
    turns = _turns(
        real_kb,
        [
            {
                "user": "도금 라인에서 쓰다 남은 황산 원액이에요.",
                "extract": {
                    "facts": [{"key": "material", "value": "h2so4", "quote": "황산"}],
                },
            },
            {"quick_reply": {"key": "contamination_screen", "kind": "expand"}},
            {"quick_reply": {"key": "designated_residue", "kind": "value", "value": False}},
            {"quick_reply": {"key": "oil_presence", "kind": "value", "value": "none"}},
            {"quick_reply": {"key": "pcb_possible", "kind": "value", "value": False}},
            {"quick_reply": {"key": "chemical_itself", "kind": "value", "value": True}},
        ],
    )
    assert turns[-1].got["ask_fact"] == "toxic_chemical_discard"


def test_proxy_assumption_note_names_msds(real_kb):
    from app.domain.facts import Fact

    facts = {"chemical_itself": Fact(key="chemical_itself", value=False, status="CLAIMED")}
    from app.rules.implications import apply_implications

    notes = assumption_notes(real_kb, apply_implications(real_kb, facts))
    assert any("'아니오'(으)로 추정" in n and "MSDS" in n for n in notes)


def test_refusal_then_talk_resumes_and_explains(real_kb):
    turns = _turns(
        real_kb,
        [
            SLUDGE_START,
            {"quick_reply": {"key": "contamination_screen", "kind": "none_all"}},
            {"quick_reply": {"key": "scope_screen", "kind": "none_all"}},
            {"quick_reply": {"key": "sludge_facility_notified", "kind": "value", "value": True}},
            {"user": "서류가 없어요", "extract": {"evidence_refused": True}},
            {
                "user": "카드뮴은 0.01이에요",
                "extract": {"facts": [{"key": "leach_cd", "value": 0.01, "quote": "0.01"}]},
            },
        ],
    )
    refused, talked = turns[-2].got, turns[-1].got
    assert refused["branch"] == "UNSUPPORTED"
    # 다시 말하면 판정 불가에 갇히지 않고 서류를 다시 안내한다
    assert talked["branch"] == "REQUEST_EVIDENCE"
    assert "말씀만으로는 정할 수 없어요" in talked["message"]
    assert "카드뮴 용출 농도" in talked["message"]


def test_refusal_needs_document_words():
    from app.agent.guard import _REFUSAL

    for t in ["서류가 없어요", "성적서는 아직 없어요", "시험성적서를 못 구했어요", "MSDS 없음"]:
        assert _REFUSAL.search(t), t
    # 값을 말한 문장이나 성분이 없다는 말은 서류 거절이 아니다
    for t in ["카드뮴은 0.01이에요", "카드뮴은 없어"]:
        assert not _REFUSAL.search(t), t
