"""S5 재활용 가능 유형: 별표 4의3 표 추출 품질과 금지·제한 판정."""
import csv
import re

import fitz
import pytest

from wastecalc import evaluate, load_kb
from wastecalc.kb import ROOT

KB = load_kb(as_of="2026-11-05")  # 테스트 기준일 고정
BIZ = {"no_longer_needed": True, "direct_reinput": False, "circular_resource_recognized": False,
       "law_exclusion": "none", "emission_facility": True}
GATES_NO = {"oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": False}
ROWS = {r["code"]: r for r in KB.annex43["rows"]}
BLANK_IN_SOURCE = {"51-99-00"}  # 원문(24쪽)에서 재활용 유형 칸이 비어 있는 행 — 육안 확인


def ev(extra, strict=False):
    return evaluate({**BIZ, **extra}, strict=strict, kb=KB)


def s5(r):
    return next((d for d in r["decided"] if d["stage"] == "S5"), None)


# ---------------------------------------------------------------- 표 추출 품질

def test_independent_extraction_matches_codex_rendered_check():
    """Codex가 쪽 이미지로 대조해 만든 20개 번호 자료와 R코드·사전분석 여부가 모두 같아야 한다."""
    cx = {}
    with open(ROOT / "data" / "allowed_recycling.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["r_code"] != "NOT_FOUND":
                cx.setdefault(r["code"], set()).add((r["r_code"], r["condition_text"].replace(" ", "")))
    assert len(cx) >= 19
    for code, expected in cx.items():
        mine = {(rc, c["pre_analysis"] or "") for c in ROWS[code]["cells"] for rc in c["r_codes"]}
        assert mine == expected, code


def test_all_r_codes_are_defined_in_annex_4_2():
    defined = set(KB.r_codes["codes"])
    for row in KB.annex43["rows"]:
        for c in row["cells"]:
            assert set(c["r_codes"]) <= defined, row["code"]


def test_every_six_digit_row_is_a_real_annex4_code():
    ids = {c["id"] for c in KB.annex4["codes"]}
    for code in ROWS:
        if len(code) == 8:
            assert code in ids, code


def test_rows_have_either_types_or_prohibition():
    for code, row in ROWS.items():
        if len(code) == 8:
            if code in BLANK_IN_SOURCE:
                assert not row["cells"], code
                continue
            assert row["cells"], code
            for c in row["cells"]:
                assert c["prohibited"] or c["r_codes"], code


def test_r_code_definitions_match_source():
    text = re.sub(r"\s+", "", "".join(p.get_text() for p in fitz.open(ROOT / "sources/raw/170401341.pdf")))
    for rc, q in KB.r_codes["quotes"].items():
        assert re.sub(r"\s+", "", q) in text, rc


def test_s5_quotes_match_source():
    def norm(s):
        return re.sub(r"\s+", "", s)
    cache = {}
    def text(sid):
        if sid not in cache:
            cache[sid] = norm("".join(p.get_text() for p in fitz.open(ROOT / KB.sources[sid]["path"])))
        return cache[sid]
    items = [b for p in KB.s5_rules["prohibitions"] for b in p["basis"]] + KB.s5_rules["outside_types"] + \
        list(KB.s5_rules["notes"].values())
    for b in items:
        assert norm(b["quote"]) in text(b["source"]), b["quote"][:40]


# ---------------------------------------------------------------- 흐름

def test_scrap_iron_gets_allowed_types():
    r = ev({"waste_kind": "other", "physical_state": "solid", **GATES_NO, "general_group": "51-29", "code": "51-29-01"})
    d = s5(r)
    assert d["conclusion"] == "ALLOWED_TYPES"
    assert [a["r_code"] for a in d["allowed_types"]] == ["R-3-3", "R-4-1", "R-10"]
    assert all(a["pre_analysis_required"] is False for a in d["allowed_types"])


def test_plastic_packaging_has_pre_analysis_split():
    r = ev({"waste_kind": "synthetic_resin", "physical_state": "solid", **GATES_NO, "code": "51-03-07"})
    d = s5(r)
    need = {a["r_code"] for a in d["allowed_types"] if a["pre_analysis_required"]}
    assert {"R-3-5", "R-8-1", "R-9-1"} <= need
    assert any("비고 제3호" in b["location"] for b in d["basis"])


def test_acid_types_and_r10_note():
    r = ev({"waste_kind": "acid", "physical_state": "liquid", "ph": 1, **GATES_NO, "code": "02-01-01"})
    d = s5(r)
    assert "R-4-9" in {a["r_code"] for a in d["allowed_types"] if a["pre_analysis_required"]}
    assert any("비고 제4호" in b["location"] for b in d["basis"])


def test_not_listed_code_needs_environmental_assessment():
    r = ev({"waste_kind": "acid", "physical_state": "liquid", "ph": 1, **GATES_NO, "code": "02-01-04"})
    assert s5(r)["conclusion"] == "NOT_LISTED"


def test_pcb_waste_prohibited():
    r = ev({"waste_kind": "waste_oil", "physical_state": "liquid", "oil_presence": "present",
            "pcb_possible": True, "pcb_mg_l": 10, "toxic_chemical_discard": False, "code": "08-01-00"})
    assert s5(r)["conclusion"] == "PROHIBITED"


def test_asbestos_prohibited():
    r = ev({"waste_kind": "asbestos_processing", "physical_state": "solid", **GATES_NO})
    assert s5(r)["conclusion"] == "PROHIBITED"


def test_placenta_is_not_prohibited_medical():
    r = ev({"waste_kind": "medical", "physical_state": "solid", **GATES_NO, "code": "10-12-06"})
    assert s5(r)["conclusion"] == "ALLOWED_TYPES"
    r = ev({"waste_kind": "medical", "physical_state": "solid", **GATES_NO, "code": "10-12-03"})
    assert s5(r)["conclusion"] == "PROHIBITED"


def test_restricted_substance_is_restricted():
    r = ev({"waste_kind": "other", "physical_state": "liquid", "oil_presence": "none", "pcb_possible": False,
            "toxic_chemical_discard": True, "code": "09-04-00"})
    assert s5(r)["conclusion"] == "RESTRICTED"


def test_blank_pre_analysis_cell_flagged():
    r = ev({"waste_kind": "waste_oil", "physical_state": "liquid", "oil_presence": "present",
            "pcb_possible": False, "toxic_chemical_discard": False, "code": "06-02-00"})
    assert any("비어 있음" in g for g in s5(r)["gaps"])


def test_blank_row_treated_as_not_listed():
    r = ev({"waste_kind": "other", "physical_state": "solid", **GATES_NO, "general_group": "51-99",
            "code": "51-99-00", "no_specific_code_applies": True})
    assert s5(r)["conclusion"] == "NOT_LISTED"


def test_final_status_and_summary():
    r = ev({"waste_kind": "other", "physical_state": "solid", **GATES_NO, "general_group": "51-29", "code": "51-29-02"})
    assert r["status"] == "DETERMINED"
    assert set(r["summary"]) == {"S0", "S1", "S2", "S3", "S4", "S5"}
