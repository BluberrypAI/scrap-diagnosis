"""묶음 질문(관문·오염·성적서), 묶음 답 한 번에 넣기, 사업장 공통 사실, 미리 넣은 분류번호 유지."""
import os
import tempfile

os.environ.setdefault("WASTECALC_STATE_DB", os.path.join(tempfile.mkdtemp(), "sessions.sqlite3"))

from fastapi.testclient import TestClient  # noqa: E402

from wastecalc.compact import compact, question_groups  # noqa: E402
from wastecalc.engine import evaluate  # noqa: E402
from wastecalc.kb import load_kb  # noqa: E402
from wastecalc.session_state import revise_answers  # noqa: E402
from wastecalc.web.app import app  # noqa: E402

KB = load_kb()
SITE = {"circular_resource_recognized": False, "law_exclusion": "none", "emission_facility": True}
RESIN = {"material_fate": "released", **SITE, "waste_kind": "synthetic_resin", "physical_state": "solid"}


def _q(answers):
    r = evaluate(answers, strict=True, kb=KB)
    return compact(r, KB.at(r["as_of"]), answers).get("next_question"), r


def test_group_file_refers_to_real_facts():
    doc = question_groups()
    for g in doc["groups"].values():
        assert all(f in KB.facts for f in g["facts"]), g["facts"]
    assert all(f in KB.facts for f in doc["site_facts"])


def test_gates_asked_once_and_options_set_both_facts():
    q, _ = _q({"material": "pp", "material_fate": "released"})
    g = q["group"]
    assert g["kind"] == "one_of" and set(g["facts"]) == {"circular_resource_recognized", "law_exclusion"}
    none = g["options"][0]
    assert none["answers"] == {"circular_resource_recognized": False, "law_exclusion": "none"}
    radio = next(o for o in g["options"] if o["answers"].get("law_exclusion") == "radioactive")
    assert radio["answers"]["circular_resource_recognized"] is False
    # 해당 없음을 고르면 두 관문을 한 번에 지나 다음 단계(사업장) 질문으로 간다
    q2, r2 = _q({"material": "pp", "material_fate": "released", **none["answers"]})
    assert r2["stage"] == "S2" and q2["fact"] == "emission_facility"


def test_contamination_is_one_screen_and_all_no_matches_separate_answers():
    q, _ = _q(RESIN)
    g = q["group"]
    assert g["kind"] == "each"
    assert set(g["facts"]) == {"designated_residue", "oil_presence", "pcb_possible", "toxic_chemical_discard"}
    assert all(c["value"] == "UNKNOWN" for it in g["items"] for c in it["choices"][-1:])  # 항목마다 '모름' 가능
    grouped = {**RESIN, **g["all_no"]["answers"]}
    _, r = _q(grouped)
    # 한 번에 넣은 답과 하나씩 넣은 답의 판정이 같아야 한다(판정 규칙은 그대로)
    one = dict(RESIN)
    for _ in range(6):
        nq, rr = _q(one)
        if not nq or nq["fact"] not in g["all_no"]["answers"]:
            break
        one[nq["fact"]] = g["all_no"]["answers"][nq["fact"]]
    assert r["summary"] == rr["summary"] and r["stage"] == rr["stage"]
    assert r["summary"]["S3"].startswith("지정폐기물 아님")


def test_group_only_lists_facts_relevant_now():
    q, _ = _q({**RESIN, "waste_kind": "waste_oil", "physical_state": "liquid"})
    if q.get("group"):
        assert "oil_presence" not in q["group"]["facts"]  # 폐유 자체에는 '기름이 묻었나'를 묻지 않는다


def test_test_report_group_collects_leaching_values():
    a = {"material_fate": "released", **SITE, "waste_kind": "dust", "physical_state": "solid",
         "designated_residue": False, "oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": False,
         "dust_from_apc": True}
    for _ in range(8):
        q, r = _q(a)
        if q is None or q.get("group", {}).get("kind") == "report":
            break
        f = KB.facts[q["fact"]]
        a[q["fact"]] = False if f["type"] == "bool" else q["choices"][0]["value"]
    assert q and q["group"]["kind"] == "report", q
    items = q["group"]["items"]
    assert len(items) >= 2 and all(it["fact"].startswith("leach_") or KB.facts[it["fact"]]["cost"] == "TEST" for it in items)
    # 성적서가 없으면 모두 '모름' → 필요한 시험을 한 번에 안내하고 멈춘다
    _, r = _q({**a, **{it["fact"]: "UNKNOWN" for it in items}})
    assert r["status"] in {"NEED_TEST", "NEED_INFO", "NEED_EXPERT"} and "S4" not in r["summary"]


def test_new_answer_keeps_prefilled_code_but_revision_rechecks_it():
    old = {**RESIN, "code": "51-03-01"}
    new, invalid = revise_answers(KB, old, {"designated_residue": False})
    assert new["code"] == "51-03-01" and invalid == {}
    new, invalid = revise_answers(KB, {**old, "designated_residue": False}, {"waste_kind": "synthetic_rubber"})
    assert "code" not in new and invalid["code"] == "51-03-01"


def test_batch_answer_endpoint_and_site_facts_in_status():
    c = TestClient(app)
    st = c.get("/api/status").json()
    assert "emission_facility" in st["site_facts"]
    v = c.post("/api/session", json={"answers": {"material": "pp", "material_fate": "released"}, "strict": True}).json()
    sid = v["session_id"]
    g = v["result"]["next_question"]["group"]
    v = c.post(f"/api/session/{sid}/answers", json={"answers": g["options"][0]["answers"]}).json()
    assert v["result"]["next_question"]["fact"] == "emission_facility"
    assert len(v["candidate_trail"]) == 2  # 묶음 답은 한 단계로 기록(되돌리기도 한 번에)
    v = c.post(f"/api/session/{sid}/undo", json={}).json()
    assert v["result"]["next_question"]["group"]["id"] == "gates"
    assert c.post(f"/api/session/{sid}/answers", json={"answers": {"nope": 1}}).status_code == 400
