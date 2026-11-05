"""소재 카탈로그(소재 우선 문진)와 판정 기록(이후 단계용 고정 형식)."""
import json
from pathlib import Path

import jsonschema
import pytest

from wastecalc.compact import compact
from wastecalc.engine import evaluate
from wastecalc.kb import ROOT, load_kb
from wastecalc.record import build_record
from wastecalc.session_state import revise_answers

KB = load_kb(as_of="2026-11-05")
SCHEMA = json.loads((ROOT / "schemas" / "assessment_record.schema.json").read_text(encoding="utf-8"))
GATE = {"material_fate": "released", "circular_resource_recognized": False, "law_exclusion": "none",
        "emission_facility": True}
CLEAN = {"designated_residue": False, "oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": False}
CAT = KB.materials["materials"]


def ev(answers, strict=False, **kw):
    return evaluate(answers, strict=strict, kb=KB, **kw)


def finish(answers, limit=15):
    """오염 확인은 모두 '아니오', 상태는 고체, 숫자는 0, 예/아니오는 '아니오'로 끝까지 답한다(번호 질문 전까지)."""
    a = dict(answers)
    for _ in range(limit):
        r = ev(a)
        q = r.get("next_question")
        if not q or q["fact"] in {"code", "general_group"}:
            return a, r
        f = KB.facts[q["fact"]]
        a[q["fact"]] = CLEAN.get(q["fact"], "solid" if q["fact"] == "physical_state" else
                                 False if f["type"] == "bool" else 0 if f["type"] == "number" else
                                 next(iter(q.get("allowed_values") or f["values"])))
    return a, ev(a)


def test_material_is_asked_first_and_offers_grouped_catalog():
    r = ev({})
    q = compact(r, KB, {})["next_question"]
    assert q["fact"] == "material"
    assert {"unlisted", "mixed_inseparable", "pp", "ferrous_scrap"} <= {c["value"] for c in q["choices"]}
    assert all(c.get("group") for c in q["choices"] if c["value"] != "UNKNOWN")
    # 폐기물 종류를 직접 답한 경우(이전 방식, MCP 등)에는 소재를 다시 묻지 않는다
    r = ev({**GATE, "waste_kind": "acid"})
    assert compact(r, KB, {**GATE, "waste_kind": "acid"})["next_question"]["fact"] != "material"


@pytest.mark.parametrize("mid", [m for m, v in CAT.items()
                                 if len((v.get("codes") or {}).get("GENERAL", [])) == 1 and len(v["codes"]["GENERAL"][0]) == 8])
def test_single_code_materials_get_code_without_picking_from_legal_list(mid):
    a, r = finish({**GATE, "material": mid})
    s4 = next((d for d in r["decided"] if d["stage"] == "S4"), None)
    if r["summary"].get("S3", "").startswith("지정폐기물") and not r["summary"]["S3"].startswith("지정폐기물 아님"):
        pytest.skip("이 답 조합에서는 지정폐기물로 감")
    assert s4 is not None, (mid, r["status"], r.get("next_question"))
    assert s4["conclusion"] == CAT[mid]["codes"]["GENERAL"][0] and not s4["user_selected"]


def test_pp_solid_vs_liquid_follows_common_rules():
    assert ev(finish({**GATE, "material": "pp", "physical_state": "solid"})[0])["summary"]["S4"].startswith("51-03-01")
    liquid = ev(finish({**GATE, "material": "pp", "physical_state": "liquid"})[0])
    assert liquid["summary"]["S4"].startswith("01-01-02")  # 지정폐기물 번호도 소재로 정해짐


def test_presets_fill_intrinsic_facts_and_conflict_is_not_overwritten():
    r = ev({**GATE, "material": "hcl"})
    assert r["answers"]["waste_kind"] == {"value": "acid", "source": "MATERIAL"}
    assert r["answers"]["physical_state"] == {"value": "liquid", "source": "MATERIAL"}
    r = ev({**GATE, "material": "hcl", "physical_state": "solid"})  # 사용자가 다르게 답함 → 충돌로 남김
    assert r["answers"]["physical_state"]["conflict"] == ["solid", "liquid"]


def test_blast_furnace_slag_preset_skips_the_slag_origin_question():
    a, r = finish({**GATE, "material": "bf_slag"})
    assert "blast_furnace_iron_slag" not in a
    assert r["summary"]["S4"].startswith("51-04-01")


def test_mixed_inseparable_does_not_invent_a_code():
    a, r = finish({**GATE, "material": "mixed_inseparable"})
    assert r["status"] == "NEED_EXPERT" and r["reason"] == "NO_MIXTURE_RULE" and "S4" not in r["summary"]


def test_unlisted_material_falls_back_to_waste_kind_question():
    r = ev({**GATE, "material": "unlisted"})
    assert compact(r, KB, {**GATE, "material": "unlisted"})["next_question"]["fact"] == "waste_kind"


def test_designation_by_contamination_follows_the_contaminant_not_the_material():
    # 폐윤활유라도 PCB가 기준 이상이면 번호는 소재(06-01-01)가 아니라 PCB 함유 폐기물(08) 쪽이다
    a = {**GATE, "material": "lube_oil", "pcb_possible": True, "pcb_mg_l": 5, "toxic_chemical_discard": False}
    r = ev(a)
    s4 = r["summary"].get("S4") or ""
    allowed = list(((r.get("next_question") or {}).get("allowed_values") or {}).keys())
    assert s4.startswith("08") or (allowed and all(c.startswith("08") for c in allowed)), (s4, allowed, r.get("reason"))
    # 고체 PP 용기에 폐유가 남아 있으면 폐유 쪽 번호로 간다(소재 번호 01-01-02로 좁히지 않음)
    b = {**GATE, "material": "pp", "physical_state": "solid", "designated_residue": True, "residue_kind": "waste_oil",
         "oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": False}
    r = ev(b)
    assert r["reason"] == "INTERPRETATION_NEEDED"  # 잔류물 규칙은 질의회신 근거라 기본은 기관 확인으로 멈춤
    r = ev(b, allow_interpretive=True)  # 번호가 어디로 가는지만 확인
    allowed = list(((r.get("next_question") or {}).get("allowed_values") or {}).keys())
    got = (r["summary"].get("S4") or "")[:2] or (allowed[0][:2] if allowed else "")
    assert got == "06", (r["summary"], allowed, r.get("reason"), r.get("message"))


def test_pp_solid_candidate_count_keeps_contamination_paths_open():
    r = ev({**GATE, "material": "pp", "physical_state": "solid"})
    c = compact(r, KB, {**GATE, "material": "pp", "physical_state": "solid"})
    assert c["candidates"]["count"] > 1  # 오염 확인 전이므로 지정(폐유 등) 가능성이 남아 있다


def test_changing_material_rechecks_dependent_answers():
    old = {**GATE, "material": "naoh_solid", "physical_state": "solid", "code": "02-02-03"}
    new, invalid = revise_answers(KB, old, {"material": "hcl"})
    assert new["material"] == "hcl" and "physical_state" not in new and "code" not in new
    assert invalid["code"] == "02-02-03"


# ---------------------------------------------------------------- 판정 기록

def _record(answers, **kw):
    r = ev(answers, strict=True, **kw)
    return build_record(KB.at(r["as_of"]), answers, r)


def test_record_matches_schema_and_hash_is_reproducible():
    a = finish({**GATE, "material": "pp"})[0]
    rec = _record(a, include_reporting=True)
    jsonschema.validate(rec, SCHEMA)
    assert rec["items"]["code"]["code"] == "51-03-01" and rec["items"]["code"]["how"] == "AUTO"
    assert rec["record_hash"] == _record(dict(reversed(list(a.items()))), include_reporting=True)["record_hash"]
    assert rec["record_hash"] != _record({**a, "physical_state": "liquid"}, include_reporting=True)["record_hash"]


def test_record_reports_item_status_and_weakest_trust_honestly():
    rec = _record(finish({**GATE, "material": "pp"})[0])
    code = rec["items"]["code"]
    # 규칙이 모두 사람 검토 전이므로 '확정'이 아니라 잠정, 신뢰 수준 low — 이유가 함께 나온다
    assert code["status"] == "PROVISIONAL" and code["trust"]["level"] == "low"
    assert "사람 검토 전 규칙" in code["trust"]["reasons"] and code["trust"]["facts"] == "USER"
    assert rec["material"]["id"] == "pp" and rec["hazards"]["physical_state"]["value"] == "solid"


def test_record_open_items_and_not_applicable_items():
    rec = _record({**GATE, "material": "pp"})
    assert rec["items"]["code"]["status"] == "OPEN" and rec["open_items"]
    assert all(i["need"] in {"USER", "DOCUMENT", "TEST", "AUTHORITY"} for i in rec["open_items"])
    rec = _record({**GATE, "material_fate": "still_used", "circular_resource_recognized": False})
    assert rec["items"]["waste_status"]["value"] == "NOT_WASTE"
    assert rec["items"]["code"]["status"] == "NOT_APPLICABLE"
    jsonschema.validate(rec, SCHEMA)


def test_record_endpoint_and_mcp_tool():
    from fastapi.testclient import TestClient

    from wastecalc import server
    from wastecalc.web.app import app

    c = TestClient(app)
    sid = c.post("/api/session", json={"answers": {**GATE, "material": "ferrous_scrap", **CLEAN}}).json()["session_id"]
    rec = c.get(f"/api/session/{sid}/record").json()
    jsonschema.validate(rec, SCHEMA)
    assert rec["items"]["code"]["code"] == "51-29-01"
    out = server.assessment_record(answers={**GATE, "material": "ferrous_scrap", **CLEAN})
    assert not out.isError and out.structuredContent["items"]["code"]["code"] == "51-29-01"

