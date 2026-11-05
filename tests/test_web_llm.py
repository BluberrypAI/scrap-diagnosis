"""시험 화면 API와 LLM 어댑터 안전장치(가짜 LLM 응답으로 검사)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wastecalc import llm
from wastecalc.web.app import KB, app

client = TestClient(app)
BASE = {"material": "unlisted", "no_longer_needed": True, "direct_reinput": False, "continuous_feedstock": False,
        "circular_resource_recognized": False, "law_exclusion": "none", "emission_facility": True}


def test_session_answer_undo_delete():
    v = client.post("/api/session", json={"answers": BASE}).json()
    sid = v["session_id"]
    assert v["result"]["next_question"]["fact"] == "waste_kind"
    v = client.post(f"/api/session/{sid}/answer", json={"fact": "waste_kind", "value": "acid"}).json()
    assert v["result"]["next_question"]["fact"] == "physical_state" and v["can_undo"]
    v = client.post(f"/api/session/{sid}/undo", json={}).json()
    assert v["result"]["next_question"]["fact"] == "waste_kind"
    v = client.post(f"/api/session/{sid}/answer", json={"fact": "emission_facility", "value": None}).json()
    assert "emission_facility" not in {a["fact"] for a in v["answered"]}


def test_bad_value_rejected():
    sid = client.post("/api/session", json={"answers": {}}).json()["session_id"]
    r = client.post(f"/api/session/{sid}/answer", json={"fact": "waste_kind", "value": "고철"})
    assert r.status_code == 400


def test_llm_off_returns_clear_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "")
    r = client.post("/api/extract", json={"text": "철 스크랩"})
    assert r.status_code == 400 and "LLM" in r.json()["detail"]


def test_extract_keeps_only_grounded_valid_facts(monkeypatch):
    text = "대기 배출시설 신고가 되어 있고 절삭유가 묻은 철 칩이 나옵니다."
    fake = {"facts": {"emission_facility": True, "oil_presence": "present", "waste_kind": "other",
                      "pcb_possible": False, "physical_state": "gas", "code": "51-29-01"},
            "evidence": {"emission_facility": "대기 배출시설 신고가 되어 있고", "oil_presence": "절삭유가 묻은",
                         "waste_kind": "철 칩", "pcb_possible": "PCB는 없습니다",  # 원문에 없는 근거 → 버림
                         "physical_state": "칩", "code": "철 칩"}}
    monkeypatch.setattr(llm, "_chat_json", lambda s, u: fake)
    got = {p["fact"]: p["value"] for p in llm.extract_facts(KB, text)}
    assert got == {"emission_facility": True, "oil_presence": "present", "waste_kind": "other"}
    # pcb_possible: 근거가 원문에 없음 / physical_state: 허용 값 아님 / code: 직접 고르는 항목이라 제외


def test_map_answer_falls_back_to_unknown_on_invalid(monkeypatch):
    monkeypatch.setattr(llm, "_chat_json", lambda s, u: {"value": "maybe", "reason": "?"})
    assert llm.map_answer(KB, "emission_facility", "아마도")["value"] == "UNKNOWN"
    monkeypatch.setattr(llm, "_chat_json", lambda s, u: {"value": True, "reason": "신고증 있음"})
    assert llm.map_answer(KB, "emission_facility", "신고증이 있어요")["value"] is True


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "src/wastecalc/web/scrap/SCRAP.html").exists(),
                    reason="로컬 시험 화면 파일은 저장소에 넣지 않음")
def test_scrap_page_and_test_page_are_separate():
    html = client.get("/").text
    assert "window.__ENGINE_SURVEY||v.createRoot" in html and "/scrap-engine/survey.js" in html
    assert "폐기물 판정 시험 화면" in client.get("/test").text
    assert client.get("/scrap-engine/survey.js").status_code == 200
    assert client.get("/scrap-engine/berry.png").headers["content-type"] == "image/png"
    assert client.get("/scrap-engine/app.py").status_code == 404


def test_session_accepts_strict():
    v = client.post("/api/session", json={"answers": {**BASE, "waste_kind": "synthetic_resin", "physical_state": "solid",
                                                      "designated_residue": False, "oil_presence": "none",
                                                      "pcb_possible": False, "toxic_chemical_discard": False,
                                                      "code": "51-03-01"}, "strict": True}).json()
    r = v["result"]
    assert r["provisional"] and r["status"] == "NEED_EXPERT" and r["trail"][-1]["stage"] == "S5"
