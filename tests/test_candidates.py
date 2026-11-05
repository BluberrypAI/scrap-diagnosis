"""남은 분류번호 후보 수, 보기별 남는 수, 판정 근거 순서, 재활용 유형 묶음(SCRAP 문진 화면용 출력)."""
from fastapi.testclient import TestClient

from wastecalc.candidates import code_candidates
from wastecalc.compact import compact
from wastecalc.engine import evaluate
from wastecalc.kb import load_kb
from wastecalc.web.app import app

KB = load_kb()
BASE = {"material": "unlisted", "material_fate": "released", "circular_resource_recognized": False, "law_exclusion": "none",
        "emission_facility": True}
RESIN_CLEAN = {"waste_kind": "synthetic_resin", "physical_state": "solid", "designated_residue": False,
               "oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": False}


def _c(answers, strict=False):
    r = evaluate(answers, strict=strict, kb=KB)
    return r, compact(r, KB.at(r["as_of"]), answers)


def test_counts_shrink_to_one_code():
    a = dict(BASE)
    seen = []
    for f, v in [*RESIN_CLEAN.items(), ("code", "51-03-01")]:
        _, c = _c(a)
        seen.append(c["candidates"]["count"])
        q = c["next_question"]
        if q and q["fact"] == f:
            # 보기마다 미리 센 수가 실제로 그 답을 했을 때의 수와 같아야 한다
            pick = next(o for o in q["choices"] if o["value"] == v)
            assert pick["remaining"] == len(code_candidates(KB, {**a, f: v}, evaluate({**a, f: v}, strict=False, kb=KB)))
        a[f] = v
    _, c = _c(a)
    seen.append(c["candidates"]["count"])
    assert seen == sorted(seen, reverse=True) and seen[-1] == 1
    assert c["candidates"]["codes"] == [{"code": "51-03-01", "name": "폐합성수지류(폐염화비닐수지류는 제외한다)"}]


def test_no_code_conclusions_have_zero():
    for extra, concl in (({"material_fate": "still_used"}, "NOT_WASTE"), ({"law_exclusion": "radioactive"}, "EXCLUDED")):
        r, c = _c({**BASE, **extra})
        assert r["decided"][-1]["conclusion"] == concl
        assert c["candidates"]["count"] == 0 and c["candidates"]["codes"] == []


def test_waste_kind_choices_grouped_with_hints_and_counts():
    _, c = _c(BASE)
    q = c["next_question"]
    assert q["fact"] == "waste_kind"
    resin = next(o for o in q["choices"] if o["value"] == "synthetic_resin")
    assert resin["group"] == "플라스틱·고무" and "PVC" in resin["hint"]
    assert resin["remaining"] < c["candidates"]["count"]
    assert all("group" in o for o in q["choices"] if o["value"] != "UNKNOWN")


def test_physical_state_question_shows_law_quote():
    _, c = _c({**BASE, "waste_kind": "synthetic_resin"})
    q = c["next_question"]
    assert q["fact"] == "physical_state"
    assert any("고체상태의 것은 제외한다" in l["quote"] and l["evidence"] == "LAW" for l in q["law"])


def test_trail_and_recycling_groups():
    r, c = _c({**BASE, **RESIN_CLEAN, "code": "51-03-01"})
    assert r["status"] == "DETERMINED"
    assert [t["stage"] for t in c["trail"]] == ["S0", "S1", "S2", "S3", "S4", "S5"]
    s3 = c["trail"][3]
    assert s3["outcome"].startswith("지정폐기물 아님")
    assert any(a["fact"] == "physical_state" and a["value_text"] == "고체" for a in s3["answers"])
    g = c["decided"][-1]["recycling_groups"]
    free = [x["r_code"] for x in g["no_pre_analysis"]]
    need = [x["r_code"] for x in g["pre_analysis"]]
    assert free == ["R-1", "R-2", "R-3-2", "R-3-3", "R-3-4", "R-4-4", "R-9-3", "R-10"]
    assert need == ["R-8-1", "R-8-2", "R-9-1", "R-10"]  # 별표 4의3 원문대로 R-10은 양쪽 칸에 있음


def test_web_candidate_trail():
    client = TestClient(app)
    v = client.post("/api/session", json={"answers": BASE}).json()
    sid = v["session_id"]
    v = client.post(f"/api/session/{sid}/answer", json={"fact": "waste_kind", "value": "synthetic_resin"}).json()
    v = client.post(f"/api/session/{sid}/answer", json={"fact": "physical_state", "value": "solid"}).json()
    t = v["candidate_trail"]
    assert len(t) == 3 and t[0] > t[1] > t[2] == v["result"]["candidates"]["count"]
