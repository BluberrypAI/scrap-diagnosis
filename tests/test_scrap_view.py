"""scrap-web 문진 화면용 API(/api/classification/*) — 화면이 고른 보기의 answers만 돌려보내는 흐름."""
import os
import tempfile

import pytest

os.environ.setdefault("WASTECALC_STATE_DB", os.path.join(tempfile.mkdtemp(), "sessions.sqlite3"))

from fastapi.testclient import TestClient  # noqa: E402

from wastecalc.web.app import app  # noqa: E402

C = TestClient(app)
NO = {"아니오", "기름이 묻거나 섞이지 않음", "해당 없음"}


def start(answers=None):
    v = C.post("/api/classification/sessions", json={"waste_id": "w1", "answers": answers or {}}).json()
    assert v["phase"] == "question"
    return v


def pick(v, label=None, pred=None):
    opts = v["question"]["options"]
    o = next(o for o in opts if (pred(o) if pred else o["label"].startswith(label)))
    return C.post(f"/api/classification/sessions/{v['session_id']}/answer", json={"answers": o["answers"]}).json()


def run(v, script, default_no=True, limit=20):
    """script: 질문 제목 일부 → 고를 보기 앞부분. 없으면 '아니오'류, 그것도 없으면 첫 보기."""
    for _ in range(limit):
        if v["phase"] != "question":
            return v
        q = v["question"]
        lab = next((ans for key, ans in script.items() if key in q["title"]), None)
        if lab:
            v = pick(v, lab)
        elif default_no and any(o["label"] in NO for o in q["options"]):
            v = pick(v, pred=lambda o: o["label"] in NO)
        else:
            v = pick(v, pred=lambda o: True)
    return v


def test_view_shape_matches_survey_screen():
    v = start()
    q, p = v["question"], v["panel"]
    assert set(v["step"]) == {"index", "total"} and v["step"]["total"] == 6
    assert q["title"] and q["options"] and all({"id", "label", "answers"} <= set(o) for o in q["options"])
    assert {"count", "start", "trail", "excluded"} <= set(p) and p["count"] == p["start"]
    assert q["kind"] == "group"  # 소재 묶음 → 소재, 두 질문으로 나눔(화면은 라디오 한 단계)


def test_pp_flow_reaches_code_with_screen_result_shape():
    v = start()
    v = pick(v, "플라스틱")
    assert v["question"]["kind"] == "back_to_group"
    v = run(pick(v, "PP("), {"어떻게 하나요": "내보낸다", "배출시설": "예", "상태": "고체"})
    assert v["phase"] == "result"
    r = v["result"]
    assert r["kind"] == "code" and r["code"] == "51-03-01" and r["name"].startswith("폐합성수지류")
    assert r["badges"] == ["사업장일반폐기물", "배출시설 운영 사업장"]
    assert r["provisional"] and "잠정" in r["note"]
    assert ["R-1", "원형 그대로 재사용"] in r["recycle"]["free"] and ["R-9-1", "고형연료제품 제조"] in r["recycle"]["analysis"]
    assert r["treatment"] == {"waste_code": "51-03-01", "material": "PP", "material_label": "PP(폴리프로필렌)"}
    ev = r["evidence"]
    assert ev and all({"num", "title", "cite", "quote", "outcome", "reason"} <= set(e) for e in ev)
    assert "{" not in " ".join(e["reason"] for e in ev)  # 소재에서 채운 값도 사람이 읽는 말로
    assert v["panel"]["trail"][0] == 272 and v["panel"]["count"] == 1


# 국가법령정보센터 시행규칙 제60호 별표 4 및 시행령 별표 1 대조 사례.
SITE_CLEAN = {"material_fate": "released", "circular_resource_recognized": False,
              "law_exclusion": "none", "emission_facility": True, "designated_residue": False,
              "oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": False}


@pytest.mark.parametrize(("material", "extra", "code", "route_material"), [
    ("pp", {"physical_state": "solid", "resin_stream": "ordinary_resin"}, "51-03-01", "PP"),
    ("pp", {"physical_state": "solid", "resin_stream": "discarded_packaging"}, "51-03-07", "PP"),
    ("pp", {"physical_state": "liquid"}, "01-01-02", None),
    ("pp", {"physical_state": "semisolid"}, "01-01-02", None),
    ("pe", {"physical_state": "solid", "resin_stream": "ordinary_resin"}, "51-03-01", "PE"),
    ("pe", {"physical_state": "solid", "resin_stream": "discarded_packaging"}, "51-03-07", "PE"),
    ("pet", {"physical_state": "solid", "resin_stream": "discarded_packaging"}, "51-03-07", "PET"),
    ("pvc", {"physical_state": "solid"}, "51-03-03", None),
    ("metal_can", {"can_scope": "covered_aluminium"}, "51-29-03", "aluminium"),
    ("metal_can", {"can_scope": "covered_steel"}, "51-29-03", None),
    ("metal_can", {"can_scope": "covered_unknown"}, "51-29-03", None),
    ("metal_can", {"can_scope": "other_container"}, "51-29-04", None),
    ("ferrous_scrap", {}, "51-29-01", None),
    ("paper", {}, "51-28-02", None),
    ("machine_oil", {}, "06-01-03", None),
])
def test_official_annex4_classification_cases(material, extra, code, route_material):
    response = C.post("/api/classification/evaluate", json={
        "answers": {**SITE_CLEAN, "material": material, **extra}, "as_of": "2026-11-06",
    })
    assert response.status_code == 200
    view = response.json()
    assert view["phase"] == "result"
    result = view["result"]
    assert result["code"] == code
    assert result["treatment"]["material"] == route_material
    assert result["provisional"]
    if code == "51-03-01":
        assert "R-3-2" in {item[0] for item in result["recycle"]["free"]}
    elif code == "51-03-07":
        assert "R-3-2" not in {item[0] for item in result["recycle"]["free"]}
        assert "R-3-5" in {item[0] for item in result["recycle"]["analysis"]}


def test_annex4_scope_questions_do_not_assume_a_code():
    answers = {**SITE_CLEAN, "material": "pp", "physical_state": "solid"}
    before = C.post("/api/classification/evaluate", json={"answers": answers}).json()
    assert before["question"]["fact"] == "resin_stream" and before["panel"]["count"] == 2
    unknown = C.post("/api/classification/evaluate", json={
        "answers": {**answers, "resin_stream": "UNKNOWN"},
    }).json()
    assert "code" not in unknown["result"]
    can = C.post("/api/classification/evaluate", json={"answers": {**SITE_CLEAN, "material": "metal_can"}}).json()
    assert can["question"]["fact"] == "can_scope"


def test_oil_contaminated_solid_pp_does_not_default_to_general_resin():
    answers = {**SITE_CLEAN, "material": "pp", "physical_state": "solid",
               "resin_stream": "ordinary_resin", "oil_presence": "present"}
    def evaluate_oil(pct):
        return C.post("/api/classification/evaluate", json={
            "answers": {**answers, "oil_content_pct": pct},
        }).json()

    assert evaluate_oil(4.99)["result"]["code"] == "51-03-01"
    above = evaluate_oil(5)
    assert above.get("result", {}).get("code") != "51-03-01"
    assert above.get("question", {}).get("fact") == "code"
    assert all(option["answers"]["code"].startswith("06") for option in above["question"]["options"]
               if option["answers"].get("code") not in {None, "UNKNOWN"})


def test_undo_from_group_items_returns_to_group_question():
    v = pick(start(), "금속")
    assert v["question"]["kind"] == "back_to_group"
    v = C.post(f"/api/classification/sessions/{v['session_id']}/undo").json()
    assert v["question"]["kind"] == "group"


def test_number_question_becomes_range_options_and_is_recorded():
    v = start({"material": "hcl", "material_fate": "released", "circular_resource_recognized": False,
               "law_exclusion": "none", "emission_facility": True})
    for _ in range(8):
        if v["phase"] != "question" or v["question"]["kind"] == "range":
            break
        v = run(v, {}, limit=1)
    q = v["question"]
    assert [o["label"] for o in q["options"]][:2] == ["2 이하", "2 초과"] and q["options"][-1]["label"] == "모름"
    v = pick(v, "2 이하")
    assert v["phase"] == "result" and v["result"]["code"] == "02-01-01"
    rec = C.get(f"/api/classification/sessions/{v['session_id']}/record").json()
    assert rec["range_answers"] == {"ph": "2 이하"} and rec["items"]["code"]["code"] == "02-01-01"


def test_test_report_question_and_exceed_follow_up():
    v = start({"material": "dust_other", "material_fate": "released", "circular_resource_recognized": False,
               "law_exclusion": "none", "emission_facility": True})
    for _ in range(10):
        if v["phase"] != "question" or v["question"]["kind"] == "report":
            break
        q = v["question"]
        v = pick(v, "예") if "대기오염 방지시설" in q["title"] else run(v, {}, limit=1)
    assert v["question"]["kind"] == "report" and len(v["question"]["options"]) == 3
    v = pick(v, "기준을 넘는 항목이 있어요")
    assert v["question"]["kind"] == "report_item"
    v = pick(v, pred=lambda o: True)
    assert v["phase"] == "result" and v["result"]["code"] == "03-02-00"


def test_report_without_certificate_stops_with_tests():
    v = start({"material": "dust_other", "material_fate": "released", "circular_resource_recognized": False,
               "law_exclusion": "none", "emission_facility": True})
    for _ in range(10):
        if v["phase"] != "question" or v["question"]["kind"] == "report":
            break
        q = v["question"]
        v = pick(v, "예") if "대기오염 방지시설" in q["title"] else run(v, {}, limit=1)
    v = pick(v, "성적서가 아직 없어요")
    assert v["phase"] == "result" and v["result"]["kind"] == "test" and v["result"]["to_check"]


def test_results_without_code_have_their_own_kind():
    v = run(start({"material": "pp"}), {"어떻게 하나요": "제품이나 원료로 계속"})
    assert v["result"]["kind"] == "not_applicable" and v["result"]["title"] == "폐기물이 아니에요"
    v = run(start({"material": "sludge_ww_unknown", "material_fate": "released", "circular_resource_recognized": False,
                   "law_exclusion": "none", "emission_facility": True}), {})
    assert v["result"]["kind"] == "test" and v["result"]["required_test"]["item"].startswith("오니 성분")


def test_stateless_evaluate_matches_session_view():
    ans = {"material": "ferrous_scrap", "material_fate": "released", "circular_resource_recognized": False,
           "law_exclusion": "none", "emission_facility": True, "designated_residue": False, "oil_presence": "none",
           "pcb_possible": False, "toxic_chemical_discard": False}
    a = C.post("/api/classification/evaluate", json={"answers": ans}).json()
    sid = C.post("/api/classification/sessions", json={"answers": ans}).json()["session_id"]
    b = C.get(f"/api/classification/sessions/{sid}").json()
    assert a["phase"] == b["phase"] == "result" and a["result"]["code"] == b["result"]["code"] == "51-29-01"
    assert C.post("/api/classification/evaluate", json={"answers": {"nope": 1}}).status_code == 400


def test_stateless_apply_lets_server_keep_state():
    # 서버 흐름: 저장해 둔 state + 화면이 보낸 보기 answers → 새 state와 화면 응답
    st = {}
    v = C.post("/api/classification/evaluate", json={"answers": {}}).json()
    assert v["contract"] == "classification-view-v1"
    for label in ["금속", "고철", "내보낸다", "해당 없음", "예"]:
        o = next(o for o in v["question"]["options"] if o["label"].startswith(label))
        out = C.post("/api/classification/apply", json={"state": st, "patch": o["answers"]}).json()
        st, v = out["state"], out["view"]
    assert "__ui" not in st["answers"] and st["answers"]["material"] == "ferrous_scrap"
    while v["phase"] == "question":
        o = next((o for o in v["question"]["options"] if o["label"] in NO), v["question"]["options"][0])
        out = C.post("/api/classification/apply", json={"state": st, "patch": o["answers"]}).json()
        st, v = out["state"], out["view"]
    assert v["result"]["code"] == "51-29-01"
    rec = C.post("/api/classification/record", json={"state": st}).json()
    assert rec["items"]["code"]["code"] == "51-29-01" and len(rec["record_hash"]) == 64
    # 앞 답(소재)을 고치면 영향받는 답은 빠지고 needs_review로 돌아온다
    out = C.post("/api/classification/apply", json={"state": st, "patch": {"material": "nonferrous_scrap"}}).json()
    assert out["state"]["answers"]["material"] == "nonferrous_scrap"
