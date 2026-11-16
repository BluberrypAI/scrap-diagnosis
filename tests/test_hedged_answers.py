"""추측 답변("아마 ~일걸"): 기록은 하되 보드·결과에 표시하고, 지정폐기물 가능성을 지우는 추측은
확정 전에 한 번 다시 묻는다(app/agent/router.py confirm_guess_question).
"""

from __future__ import annotations

from datetime import date

from app.agent.golden import normalize_extract
from app.agent.llm_client import FakeLLMClient
from app.agent.orchestrator import DiagnosisSession, QuickReply
from app.agent.router import SUB_CONFIRM_GUESS
from app.domain.verdict import build_board

AS_OF = date(2026, 11, 11)
PP_SURE = {"facts": [{"key": "material", "value": "pp", "quote": "PP"}]}
PP_GUESS = {"facts": [{"key": "material", "value": "pp", "quote": "PP", "certainty": "guess"}]}
NONE_GUESS = {
    "group_answer": {"group_id": "contamination_screen", "choice": "none_all", "certainty": "guess"}
}


def _session(kb, extracts):
    ex = FakeLLMClient(by_name={"extract": [normalize_extract(e) for e in extracts]})
    s = DiagnosisSession(kb, extractor_llm=ex, case_id="c1", as_of=AS_OF)
    s.seed({"emission_facility": True})
    return s


def _to_decision(s):
    s.handle(quick_reply=QuickReply(key="scope_screen", kind="none_all"))
    return s.handle(quick_reply=QuickReply(key="physical_state", value="solid"))


def test_guessed_group_answer_is_marked_and_confirmed_once(real_kb):
    s = _session(real_kb, [PP_SURE, NONE_GUESS])
    s.handle(text="PP 필름이에요")
    s.handle(text="아마 다 해당 없을걸요")
    eff = s.store.effective()
    assert eff["oil_presence"].hedged and eff["pcb_possible"].hedged
    r = _to_decision(s)
    # 결론이 나도 확정 전에 추측한 오염 항목을 묶음으로 한 번 다시 묻는다
    assert r.branch == "ASK_FACT" and r.sub_branch == SUB_CONFIRM_GUESS
    assert r.ui.question["key"] == "contamination_screen"
    assert "추측" in r.ui.question["text"]
    # 버튼으로 "모두 해당 없음" → 추측 표시가 풀리고 결과로
    r = s.handle(quick_reply=QuickReply(key="contamination_screen", kind="none_all"))
    assert r.branch == "FINAL_REVIEW"
    assert not s.store.effective()["oil_presence"].hedged
    assert not any("추측" in a for a in r.ui.result.assumptions)
    assert s.peek().decision.branch.value == "FINAL_REVIEW"  # 확정 재검증도 같은 결론


def test_confirm_expand_retracts_guesses_and_asks_one_by_one(real_kb):
    s = _session(real_kb, [PP_SURE, NONE_GUESS])
    s.handle(text="PP 필름이에요")
    s.handle(text="아마 다 해당 없을걸요")
    _to_decision(s)
    r = s.handle(quick_reply=QuickReply(key="contamination_screen", kind="expand"))
    assert r.branch == "ASK_FACT" and r.sub_branch != SUB_CONFIRM_GUESS
    assert r.ui.question["key"] in {
        "designated_residue",
        "oil_presence",
        "pcb_possible",
        "toxic_chemical_discard",
    }


def test_guessed_material_is_shown_but_not_reasked(real_kb):
    s = _session(real_kb, [PP_GUESS])
    s.handle(text="아마 PP일걸요")
    s.handle(quick_reply=QuickReply(key="contamination_screen", kind="none_all"))
    r = _to_decision(s)
    assert r.branch == "FINAL_REVIEW"  # 소재 추측은 결론을 지우는 쪽이 아니라 다시 묻지 않음
    assert any("소재" in a and "추측" in a for a in r.ui.result.assumptions)
    board = build_board(real_kb, s.last_step, questions_asked=0, max_questions=12)
    mat = next(f for f in board.facts if f.key == "material")
    assert mat.hedged and "추측" in mat.source_label


def test_guess_state_survives_save_and_restore(real_kb):
    s = _session(real_kb, [PP_SURE, NONE_GUESS])
    s.handle(text="PP 필름이에요")
    s.handle(text="아마 다 해당 없을걸요")
    _to_decision(s)
    facts = [f.model_dump(mode="json") for f in s.store.history]
    s2 = DiagnosisSession.from_state(real_kb, s.export_state(), facts=facts)
    assert s2.state.guess_checked == s.state.guess_checked and s2.state.guess_checked
    assert s2.store.effective()["oil_presence"].hedged
