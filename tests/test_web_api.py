"""개발용 세션 API·사실 목록 API·로컬 화면 경로. 엔진은 LLM을 쓰지 않는다."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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


def test_status_says_engine_uses_no_llm():
    st = client.get("/api/status").json()
    assert st["llm"]["enabled"] is False
    for path in ("/api/extract", "/api/map", "/api/help", "/api/classification/extract"):
        assert client.post(path, json={"text": "x"}).status_code in (404, 405)


def test_fact_catalog_api_for_external_proposers():
    d = client.get("/api/classification/facts").json()
    f = d["facts"]
    assert "material" in f and "pp" in f["material"]["values"] and f["material"]["value_groups"]
    assert "this_waste_designated" not in f  # 엔진이 스스로 정하는 사실은 내보내지 않음
    assert d["unknown_token"] == "UNKNOWN" and d["rule_db_version"] == KB.version
