"""기준일(as_of) 판정: 법령 판이 바뀔 때의 동작."""
import shutil

import pytest
import yaml

from wastecalc import InputError, evaluate, load_kb
from wastecalc.kb import RULES_DIR

TODAY = "2026-11-05"
BIZ = {"no_longer_needed": True, "direct_reinput": False, "continuous_feedstock": False, "circular_resource_recognized": False,
       "law_exclusion": "none", "emission_facility": True}
SCRAP = {**BIZ, "waste_kind": "other", "physical_state": "solid", "oil_presence": "none",
         "pcb_possible": False, "toxic_chemical_discard": False, "designated_residue": False, "general_group": "51-29"}


def _yaml(p):
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _dump(p, data):
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")


@pytest.fixture
def next_version_dir(tmp_path):
    """가상 개정: 2027-01-01부터 별표 4가 바뀐다(51-29-01 명칭 변경, 51-29-05 신설)."""
    d = tmp_path / "rules"
    shutil.copytree(RULES_DIR, d)
    src = _yaml(d / "sources.yaml")
    src["RULE-A4"]["effective_to"] = "2026-12-31"
    src["RULE-A4-NEXT"] = {**src["RULE-A4"], "version": "가상 개정판", "effective_on": "2027-01-01", "effective_to": None}
    _dump(d / "sources.yaml", src)
    a4 = _yaml(d / "annex4_codes.yaml")
    a4["source"] = "RULE-A4-NEXT"
    for c in a4["codes"]:
        if c["id"] == "51-29-01":
            c["name"] = "고철(가상 개정 명칭)"
    a4["codes"].append({"id": "51-29-05", "name": "가상 신설 폐금속", "section": "GENERAL"})
    _dump(d / "annex4_codes_next.yaml", a4)
    # 별표 4를 근거로 쓰는 S3 규칙도 새 판을 둔다(없으면 S3가 그날 판정 불가가 되어야 함)
    s3 = _yaml(d / "rules_s3.yaml")
    nxt = [dict(r, source="RULE-A4-NEXT") for r in s3["rules"] if r["source"] == "RULE-A4"]
    _dump(d / "rules_zz_next.yaml", {"rules": nxt})
    return d


def test_output_records_as_of_and_is_deterministic():
    kb = load_kb(as_of=TODAY)
    a = evaluate(SCRAP, kb=kb, as_of=TODAY)
    assert a["as_of"] == TODAY
    assert a == evaluate(SCRAP, kb=kb, as_of=TODAY)


def test_bad_date_rejected():
    with pytest.raises(InputError):
        evaluate({}, kb=load_kb(as_of=TODAY), as_of="2026/11/05")


def test_date_before_loaded_law_returns_no_rules_not_a_guess():
    r = evaluate(SCRAP, kb=load_kb(as_of=TODAY), as_of="2020-01-01", strict=False)
    assert r["status"] == "OUT_OF_SCOPE" and r["reason"] == "NO_RULES_FOR_DATE"
    assert r["decided"] == []


def test_old_and_new_annex4_selected_by_date(next_version_dir):
    kb = load_kb(next_version_dir, as_of=TODAY)
    old = evaluate({**SCRAP, "code": "51-29-01"}, kb=kb, as_of="2026-12-31", strict=False)
    new = evaluate({**SCRAP, "code": "51-29-01"}, kb=kb, as_of="2027-01-01", strict=False)
    assert old["summary"]["S4"] == "51-29-01 고철"
    assert new["summary"]["S4"] == "51-29-01 고철(가상 개정 명칭)"
    with pytest.raises(InputError):  # 신설 번호는 시행 전 날짜에는 없는 값
        evaluate({**SCRAP, "code": "51-29-05"}, kb=kb, as_of="2026-12-31")
    r = evaluate({**SCRAP, "code": "51-29-05", "no_specific_code_applies": True}, kb=kb, as_of="2027-01-01",
                 strict=False)
    assert r["summary"]["S4"] == "51-29-05 가상 신설 폐금속"


def test_stage_unavailable_if_a_rule_has_no_valid_version(next_version_dir):
    (next_version_dir / "rules_zz_next.yaml").unlink()  # S3 규칙의 새 판을 빠뜨림
    kb = load_kb(next_version_dir, as_of=TODAY)
    r = evaluate(SCRAP, kb=kb, as_of="2027-01-01", strict=False)
    assert r["status"] == "OUT_OF_SCOPE" and r["reason"] == "NO_RULES_FOR_DATE" and r["stage"] == "S3"


def test_abolished_rule_does_not_block_stage(next_version_dir):
    (next_version_dir / "rules_zz_next.yaml").unlink()
    s3 = _yaml(next_version_dir / "rules_s3.yaml")
    for r in s3["rules"]:
        if r["source"] == "RULE-A4":
            r["abolished"] = True  # 개정으로 의도적으로 없어진 규칙
    _dump(next_version_dir / "rules_s3.yaml", s3)
    kb = load_kb(next_version_dir, as_of=TODAY)
    r = evaluate(SCRAP, kb=kb, as_of="2027-01-01", strict=False)
    assert r["summary"]["S3"].startswith("지정폐기물 아님")


def test_overlapping_versions_rejected(next_version_dir):
    src = _yaml(next_version_dir / "sources.yaml")
    src["RULE-A4"]["effective_to"] = "2027-06-30"  # 새 판(2027-01-01~)과 겹침
    _dump(next_version_dir / "sources.yaml", src)
    with pytest.raises(ValueError):
        load_kb(next_version_dir, as_of=TODAY)


def test_pending_law_switches_on_effective_date(next_version_dir):
    kb = load_kb(next_version_dir, as_of=TODAY)
    assert kb.at("2026-12-31").annex4["source"] == "RULE-A4"
    assert kb.at("2027-01-01").annex4["source"] == "RULE-A4-NEXT"
