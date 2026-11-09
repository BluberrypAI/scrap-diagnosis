"""전문가 규칙 검토(설계 P2).

내용 해시, 검토 기록 → 생성 규칙 review, 검토표 가져오기, 검토 카드.
"""

from __future__ import annotations

import csv
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_kb  # noqa: E402
import review_kit  # noqa: E402
from kb_review import ReviewIndex, content_hash, dump_reviews, units_from  # noqa: E402

from app.agent.router import SessionState, run_engine  # noqa: E402
from app.domain.facts import FactStore  # noqa: E402
from app.rules.answers import fact_answer, group_none_answer  # noqa: E402
from app.rules.loader import load_kb  # noqa: E402

PP_DESIGNATED = "pp:S3-1GA-SYNTHETIC_RESIN:01-01-02"


@pytest.fixture
def knowledge(tmp_path) -> Path:
    src = tmp_path / "knowledge"
    shutil.copytree(build_kb.KNOWLEDGE, src)
    return src


def _verify(src: Path, units: list[str], *, status: str = "VERIFIED", hash_of=None) -> None:
    all_units = units_from(src)
    recs = [
        {
            "unit": u,
            "content_hash": (hash_of or {}).get(u, all_units[u].hash),
            "status": status,
            "reviewer": "검토자",
            "reviewed_at": "2026-11-20",
        }
        for u in units
    ]
    dump_reviews(src / "reviews.yaml", recs)


def _build(src: Path, out: Path) -> dict[str, dict]:
    build_kb.Converter(src).run(out)
    text = (out / "rules" / "tables" / "pp.yaml").read_text(encoding="utf-8")
    rules = yaml.safe_load(text)["rules"]
    return {r["rule_id"]: r for r in rules}


def test_content_hash_ignores_key_order_and_review_field():
    a = {"id": "R1", "when": [{"fact": "x", "op": "eq", "value": 1}], "review": "UNVERIFIED"}
    b = {"review": "REVIEWED", "when": [{"value": 1, "op": "eq", "fact": "x"}], "id": "R1"}
    assert content_hash(a) == content_hash(b)
    assert content_hash(a) != content_hash({**a, "id": "R2"})


def test_units_cover_law_rules_materials_and_code_map():
    units = units_from(build_kb.KNOWLEDGE)
    kinds = {}
    for u in units.values():
        kinds[u.kind] = kinds.get(u.kind, 0) + 1
    assert kinds == {"LAW_RULE": 150, "MATERIAL": 98, "CODE_MAP": 1}


def test_committed_data_has_no_verified_rules_yet():
    idx = ReviewIndex(build_kb.KNOWLEDGE)
    assert all(idx.status(u) == "UNVERIFIED" for u in idx.units)


def test_generated_rule_is_verified_only_when_all_units_are(knowledge, tmp_path):
    deps = ["S3-1GA-SYNTHETIC_RESIN", "code_map", "material:pp"]
    _verify(knowledge, deps[:2])  # 소재는 아직
    rules = _build(knowledge, tmp_path / "a")
    assert rules[PP_DESIGNATED]["review_units"] == deps
    assert rules[PP_DESIGNATED]["review"] == "UNVERIFIED"

    _verify(knowledge, deps)
    rules = _build(knowledge, tmp_path / "b")
    assert rules[PP_DESIGNATED]["review"] == "VERIFIED"
    # 같은 소재 테이블의 다른 규칙(다른 법 규칙에 기댐)은 그대로
    assert rules["pp:S3-6-OIL-5PCT:06-01-01"]["review"] == "UNVERIFIED"


def test_review_is_lost_when_unit_changes_after_review(knowledge, tmp_path):
    deps = ["S3-1GA-SYNTHETIC_RESIN", "code_map", "material:pp"]
    # 검토 뒤 내용이 바뀐 것과 같음
    _verify(knowledge, deps, hash_of={"material:pp": "000000000000"})
    rules = _build(knowledge, tmp_path / "out")
    assert rules[PP_DESIGNATED]["review"] == "UNVERIFIED"
    assert ReviewIndex(knowledge).status("material:pp") == "STALE"


def test_needs_change_is_not_verified(knowledge, tmp_path):
    deps = ["S3-1GA-SYNTHETIC_RESIN", "code_map", "material:pp"]
    _verify(knowledge, deps, status="NEEDS_CHANGE")
    assert _build(knowledge, tmp_path / "out")[PP_DESIGNATED]["review"] == "UNVERIFIED"


def test_verified_review_reaches_engine_decision(knowledge, tmp_path):
    """PP 일반 번호(51-03-01) 판정에 쓰인 규칙의 검토가 모두 끝나면 엔진 결과가 VERIFIED다."""
    out = tmp_path / "kb"
    build_kb.Converter(knowledge).run(out)
    kb = load_kb(out)
    pp = next(t for t in kb.tables if t.table_id == "pp")
    general = next(r for r in pp.rules if r.rule_id == "pp:GENERAL")
    assert general.review == "UNVERIFIED"

    gen_units = yaml.safe_load((out / "rules/tables/pp.yaml").read_text(encoding="utf-8"))["rules"]
    deps = next(r for r in gen_units if r["rule_id"] == "pp:GENERAL")["review_units"]
    _verify(knowledge, deps)
    out2 = tmp_path / "kb2"
    build_kb.Converter(knowledge).run(out2)
    kb2 = load_kb(out2)
    store, state = FactStore(), SessionState()
    for k, v in (("emission_facility", True), ("material", "pp"), ("physical_state", "solid")):
        store.append(fact_answer(kb2, k, v))
    for g in ("contamination_screen", "scope_screen"):
        store.extend(group_none_answer(kb2, g, list(kb2.group(g).facts)))
    ev = run_engine(kb2, store, state, date(2026, 11, 9)).evaluation
    assert ev.decided is not None and ev.decided.code == "51-03-01"
    rule = next(r for t in kb2.tables for r in t.rules if r.rule_id == ev.decided.rule_ids[0])
    assert rule.review == "VERIFIED"


# ---- 검토표 가져오기 ------------------------------------------------------------------------


def _sheet(src: Path, path: Path, fill: dict[str, dict]) -> None:
    cards = review_kit.all_cards(review_kit.Knowledge(src=src))
    review_kit.write_csv(cards, path)
    rows = list(csv.reader(path.open(encoding="utf-8-sig")))
    head = rows[0]
    for row in rows[1:]:
        for col, val in fill.get(row[0], {}).items():
            row[head.index(col)] = val
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh).writerows(rows)


OK = {
    "검토 결과(맞음/고쳐야 함/틀림)": "맞음",
    "검토자": "홍길동",
    "검토일(YYYY-MM-DD)": "2026-11-20",
}


def test_import_appends_records_and_build_uses_them(knowledge, tmp_path):
    sheet = tmp_path / "sheet.csv"
    fix = {**OK, "검토 결과(맞음/고쳐야 함/틀림)": "고쳐야 함", "의견": "인용문 갱신 필요"}
    _sheet(knowledge, sheet, {"S3-6-OIL-5PCT": OK, "material:pp": fix})
    new, errors = review_kit.import_csv(sheet, knowledge)
    assert errors == []
    assert {(r["unit"], r["status"]) for r in new} == {
        ("S3-6-OIL-5PCT", "VERIFIED"),
        ("material:pp", "NEEDS_CHANGE"),
    }
    idx = ReviewIndex(knowledge)
    assert idx.status("S3-6-OIL-5PCT") == "VERIFIED" and idx.status("material:pp") == "NEEDS_CHANGE"


@pytest.mark.parametrize(
    ("fill", "message"),
    [
        ({"S3-6-OIL-5PCT": {**OK, "내용 해시": "deadbeef0000"}}, "내용이 바뀌었습니다"),
        ({"S3-6-OIL-5PCT": {**OK, "검토자": ""}}, "검토자"),
        ({"S3-6-OIL-5PCT": {**OK, "검토 결과(맞음/고쳐야 함/틀림)": "대충 맞음"}}, "검토 결과"),
        ({"S3-6-OIL-5PCT": {**OK, "검토일(YYYY-MM-DD)": "11/20"}}, "YYYY-MM-DD"),
        ({"S3-6-OIL-5PCT": {**OK, "검토 결과(맞음/고쳐야 함/틀림)": "틀림"}}, "의견"),
    ],
)
def test_import_rejects_whole_sheet_on_any_error(knowledge, tmp_path, fill, message):
    sheet = tmp_path / "sheet.csv"
    _sheet(knowledge, sheet, {**fill, "S2-HOUSEHOLD": OK})  # 정상 행이 있어도 반영하지 않는다
    before = (knowledge / "reviews.yaml").read_text(encoding="utf-8")
    new, errors = review_kit.import_csv(sheet, knowledge)
    assert errors and message in errors[0]
    assert (knowledge / "reviews.yaml").read_text(encoding="utf-8") == before


# ---- 검토 카드 ----------------------------------------------------------------------------


def test_cards_render_conditions_in_words_and_html(tmp_path):
    k = review_kit.Knowledge()
    cards = {c["unit"]: c for c in review_kit.all_cards(k)}
    oil = dict(cards["S3-6-OIL-5PCT"]["rows"])
    conds = " ".join(oil["조건(모두 만족)"])
    assert "기름성분 함량 ≥ 5% (시험성적서 필요)" in conds
    assert "oil_content_pct" not in conds  # 개발용 키는 보이지 않는다
    assert any("별표 1 제6호" in x for x in oil["근거"])
    assert cards["S3-6-OIL-5PCT"]["tables"] == 87
    review_kit.write_html(list(cards.values()), tmp_path / "c.html", "test")
    page = (tmp_path / "c.html").read_text(encoding="utf-8")
    assert "<title>규칙 검토 카드</title>" in page and page.count("<article class='card'") == 249
    assert "카드 읽는 법" in page and "data-engine='UNUSED'" in page


def test_cards_match_engine_behavior():
    """카드가 엔진 동작과 같게 보이는지: 확인 방식, 엔진 결론, 제외 규칙, 미사용, 근거 표기."""
    k = review_kit.Knowledge()
    cards = {c["unit"]: dict(c["rows"]) for c in review_kit.all_cards(k)}
    engine = {c["unit"]: c["engine"] for c in review_kit.all_cards(k)}
    pcb = cards["S3-8GA-PCB-LIQUID"]
    # 서류 항목은 말로도 받는다(엔진은 시험 수치만 성적서를 요구)
    assert any("(말로 답해도 됨" in x for x in pcb["조건(모두 만족)"])
    assert any("PCB 함량(액체) ≥ 2mg/L (시험성적서 필요)" in x for x in pcb["조건(모두 만족)"])
    # 근거 표기에 "별표 1 … 별표 1"이 겹치지 않는다
    assert all(x.count("별표 1") <= 1 for x in pcb["근거"][:1])
    # 질의회신 근거 규칙: 원본 결론은 지정폐기물이지만 엔진은 해석 필요
    paint = cards["S3-RESIDUE-PAINT"]
    assert paint["원본 결론"][0] == "지정폐기물"
    assert paint["엔진 결론"][0] == "해석 필요(관할 기관 확인)"
    # 번호 대응표의 제외 규칙이 법 규칙 카드에 보인다
    assert any("S3-8*" in x for x in cards["S3-6-OIL-5PCT"]["제외"])
    assert any("S3-2" in x for x in cards["S3-9-TOXIC"]["제외"])
    # 엔진이 쓰지 않는 규칙(그 종류의 소재 없음)
    assert engine["S3-10-MEDICAL"] == "UNUSED"
    assert "소재가 없음" in cards["S3-10-MEDICAL"]["엔진 결론"][0]
    assert engine["S2-EMISSION-FACILITY"] == "CONDITION"
    # 소재 카드: 프리셋(고체) 때문에 나오지 않는 지정 번호 후보를 따로 보여 준다
    assert any(x.startswith("01-01-08") for x in cards["material:eps"]["쓰이지 않는 후보"])
