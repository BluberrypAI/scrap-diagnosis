import pytest
from fastapi import HTTPException

import wastecalc.web.app as web
from wastecalc import server

BASE = {"material_fate": "released", "circular_resource_recognized": False,
        "law_exclusion": "none", "emission_facility": True}
RESIN = {**BASE, "waste_kind": "synthetic_resin", "physical_state": "solid",
         "designated_residue": False, "oil_presence": "none", "pcb_possible": False,
         "toxic_chemical_discard": False, "code": "51-03-01"}


def start(answers=None):
    return web.api_start(web.StartReq(answers=answers or RESIN, strict=True))


def answer(sid, fact, value):
    return web.api_answer(sid, web.AnswerReq(fact=fact, value=value))


def test_kind_edit_requires_code_confirmation_and_preserves_independent_pcb_answer():
    sid = start()["session_id"]
    v = answer(sid, "waste_kind", "synthetic_rubber")
    facts = {a["fact"]: a["value"] for a in v["answered"]}
    assert "code" not in facts
    assert facts["pcb_possible"] is False
    assert any(a["fact"] == "code" and a["value"] == "51-03-01" for a in v["needs_review"])


def test_same_answer_is_idempotent_and_does_not_clear_code():
    sid = start()["session_id"]
    v = answer(sid, "waste_kind", "synthetic_resin")
    assert any(a["fact"] == "code" for a in v["answered"])
    assert not v["can_undo"]


def test_sessions_resume_after_memory_cache_is_cleared():
    sid = start(BASE)["session_id"]
    answer(sid, "waste_kind", "synthetic_resin")
    web.SESSIONS.clear()
    v = web.api_resume(sid)
    assert any(a["fact"] == "waste_kind" and a["value"] == "synthetic_resin" for a in v["answered"])
    assert v["result"]["next_question"]["fact"] == "physical_state"
    assert v["saved"] is True


def test_undo_restores_both_answers_and_review_state_after_restart():
    sid = start()["session_id"]
    answer(sid, "waste_kind", "synthetic_rubber")
    web.SESSIONS.clear()
    v = web.api_undo(sid)
    assert any(a["fact"] == "code" and a["value"] == "51-03-01" for a in v["answered"])
    assert not v["needs_review"]


def test_invalid_answer_never_changes_saved_state():
    sid = start()["session_id"]
    with pytest.raises(HTTPException) as error:
        answer(sid, "waste_kind", "invalid_kind")
    assert error.value.status_code == 400
    web.SESSIONS.clear()
    v = web.api_resume(sid)
    assert any(a["fact"] == "code" and a["value"] == "51-03-01" for a in v["answered"])


def test_rule_version_change_requires_explicit_restart(monkeypatch):
    sid = start()["session_id"]
    monkeypatch.setattr(web.KB, "version", "rules-different")
    with pytest.raises(HTTPException) as error:
        web.api_resume(sid)
    assert error.value.status_code == 409


def test_mcp_edit_has_same_code_invalidation_policy():
    v = server.start_assessment(RESIN)
    sid = v.structuredContent["session_id"]
    server.answer_question(sid, "waste_kind", "synthetic_rubber")
    assert "code" not in server.SESSIONS[sid]["answers"]


def test_mcp_batch_can_explicitly_reconfirm_dependent_answers():
    v = server.start_assessment(RESIN)
    sid = v.structuredContent["session_id"]
    r = server.answer_question(sid, answers={"waste_kind": "synthetic_rubber", "physical_state": "solid",
                                           "code": "51-03-02"})
    assert not r.isError
    assert server.SESSIONS[sid]["answers"]["code"] == "51-03-02"


def test_saving_failure_does_not_claim_new_answer_was_saved(monkeypatch):
    sid = start(BASE)["session_id"]
    # 테스트용 디렉터리를 DB 경로로 지정해 저장 실패를 재현한다.
    monkeypatch.setattr(web, "SESSION_DB", web.SESSION_DB.parent)
    with pytest.raises(HTTPException) as error:
        answer(sid, "waste_kind", "synthetic_resin")
    assert error.value.status_code == 503
    assert "waste_kind" not in web.SESSIONS[sid]["answers"]


def test_first_pcb_answer_preserves_independently_known_state_and_ph():
    sid = start({**BASE, "waste_kind": "acid", "physical_state": "liquid", "ph": 1})["session_id"]
    v = answer(sid, "pcb_possible", False)
    facts = {a["fact"]: a["value"] for a in v["answered"]}
    assert facts["physical_state"] == "liquid" and facts["ph"] == 1


def test_editing_pcb_gate_preserves_physical_state_but_rechecks_pcb_test():
    sid = start({**BASE, "waste_kind": "waste_oil", "physical_state": "liquid",
                 "pcb_possible": True, "pcb_mg_l": 3})["session_id"]
    v = answer(sid, "pcb_possible", False)
    facts = {a["fact"]: a["value"] for a in v["answered"]}
    assert facts["physical_state"] == "liquid" and "pcb_mg_l" not in facts


def test_mcp_legacy_fate_edit_is_not_silently_ignored():
    v = server.start_assessment({"no_longer_needed": True, "direct_reinput": False,
                                 "continuous_feedstock": False, "circular_resource_recognized": False})
    r = server.answer_question(v.structuredContent["session_id"], "no_longer_needed", False)
    assert not r.isError and r.structuredContent["decided"][-1]["label"] == "폐기물 아님"


def test_reporting_scope_and_progress_resume_after_restart():
    v = web.api_start(web.StartReq(answers=RESIN, strict=True, include_reporting=True))
    assert v["result"]["assessment_scope"] == "classification_and_reporting"
    assert v["result"]["stage"] == "S6"
    web.SESSIONS.clear()
    v = web.api_resume(v["session_id"])
    assert v["result"]["stage"] == "S6" and not v["result"]["assessment_complete"]


def test_reporting_answer_does_not_clear_confirmed_classification():
    v = web.api_start(web.StartReq(answers=RESIN, include_reporting=True))
    v = answer(v["session_id"], "reporting_shared", "none")
    assert any(a["fact"] == "code" for a in v["answered"])
    assert v["result"]["next_question"]["fact"] == "reporting_general_daily_kg"


def test_classification_edit_rechecks_reporting_quantities():
    v = start({**RESIN, "reporting_current_monthly_kg": 20, "reporting_shared": "none"})
    v = answer(v["session_id"], "physical_state", "liquid")
    facts = {a["fact"]: a["value"] for a in v["answered"]}
    assert "reporting_current_monthly_kg" not in facts
    assert facts["reporting_shared"] == "none"
