"""소재별 판정표 회귀 테스트.

tools/material_tables.py가 엔진으로 펼친 표가 기대값(tests/data/material_tables.json)과 같아야 한다.
규칙·카탈로그를 의도적으로 바꿨으면 `python tools/material_tables.py --update`로 기대값을 갱신하고,
docs/material-tables/의 바뀐 칸을 검토한다. 기대값은 아직 사람이 검토하지 않았다(UNVERIFIED).
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import material_tables as mt  # noqa: E402

from wastecalc.kb import load_kb  # noqa: E402

EXPECTED = json.loads(mt.EXPECTED.read_text(encoding="utf-8"))
KB = load_kb(as_of=EXPECTED["as_of"])
CODE = re.compile(r"^\d\d-\d\d-\d\d$")
# 오염 확인이 모두 '아니오'인데도 번호를 목록에서 골라야 하는 소재 — 법률 검토 대기(docs/material-tables/README.md)
KNOWN_CLEAN_CHOICE = {"hcl", "h2so4", "hno3", "hf", "acid_lcd_semi", "acid_other", "caustic_solution",
                      "ammonia_solution", "alkali_other", "ion_exchange_resin"}


@pytest.fixture(scope="module")
def tables():
    return mt.all_tables(KB)


def test_tables_match_expected(tables):
    exp = EXPECTED["tables"]
    assert set(tables) == set(exp), "카탈로그 소재 목록이 기대값과 다름 → --update 후 검토"
    changed = [mid for mid in tables if tables[mid] != exp[mid]]
    assert not changed, f"판정표가 바뀐 소재: {changed} → 의도한 변경이면 --update 후 바뀐 칸을 검토"


def test_no_table_is_truncated(tables):
    assert not [mid for mid, t in tables.items() if t["truncated"]]


def test_multiple_designation_reasons_never_silently_pick_one_code(tables):
    # 지정 사유가 여럿인데 번호 하나로 정해지면, 다른 사유의 번호가 지워졌다는 뜻(예: 액상 PP + PCB → 01-01-02)
    bad = [(mid, r["answers"]) for mid, t in tables.items() for r in t["rows"]
           if "MULTI_REASON" in r["flags"] and CODE.match(r["result"])]
    assert not bad, bad[:5]


def test_clean_path_code_choice_only_for_known_materials(tables):
    clean = {mid for mid, t in tables.items() for r in t["rows"]
             if "CODE_CHOICE" in r["flags"] and all(r["answers"].get(f, v) == v for f, v in mt.COMMON.items())}
    assert clean <= KNOWN_CLEAN_CHOICE, f"오염이 없는데도 번호를 골라야 하는 소재가 새로 생김: {clean - KNOWN_CLEAN_CHOICE}"
