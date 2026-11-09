"""규칙 빌드(tools/build_kb.py).

data/real/이 knowledge/로 만든 결과와 같은지, 생성 규칙에 원본 추적 필드가 있는지 본다.
원본 형식 2판(조건 중첩·공통 정의·규칙 안 예외·조건별 증빙 수준·결론 방식)도 여기서 본다.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_kb  # noqa: E402
from kb_review import units_from  # noqa: E402

from app.rules.loader import load_kb  # noqa: E402


def test_generated_data_matches_knowledge():
    """data/real/을 손으로 고쳤거나 knowledge/를 고치고 다시 빌드하지 않았으면 실패한다."""
    assert build_kb.check(build_kb.KNOWLEDGE, build_kb.OUT) == []


def test_every_rule_points_to_its_source_rule(real_kb):
    rules = [r for t in real_kb.tables for r in t.rules]
    assert rules and all(r.source_rule for r in rules)
    oil = [r for r in rules if r.source_rule == "S3-6-OIL-5PCT"]
    assert len({r.rule_id.split(":")[0] for r in oil}) == 87  # 원본 1개 → 소재 테이블 87개
    assert {(b.source_id, b.location) for b in oil[0].basis} >= {("DEC-A1", "별표 1 제6호")}


def test_every_basis_has_a_location(real_kb):
    rules = [r for t in real_kb.tables for r in t.rules]
    missing = [(r.rule_id, b.ref) for r in rules for b in r.basis if not b.location]
    assert missing == []


# ---- 원본 형식 2판: 조건 접기 ------------------------------------------------------------------

A = {"fact": "a", "op": "eq", "value": 1}
B = {"fact": "b", "op": "eq", "value": True}
C = {"fact": "c", "op": "gte", "value": 5}


def fold(e, preset=None, defs=None):
    refs: set[str] = set()
    return build_kb.fold_expr(e, preset or {}, defs or {}, refs), refs


def test_flat_list_folds_like_before():
    assert fold([A, B], {"a": 1}) == (B, set())  # 참인 조건은 빠진다
    assert fold([A, B], {"a": 2})[0] is False  # 거짓 하나면 전체가 거짓
    assert fold([A], {"a": 1})[0] is True  # 모두 접히면 참(소재 조건으로 바뀜)
    assert fold([A, B, C])[0] == {"all": [A, B, C]}  # 순서 유지


def test_any_and_not_fold_with_kleene_logic():
    assert fold({"any": [A, C]}, {"a": 1})[0] is True
    assert fold({"any": [A, C]}, {"a": 2})[0] == C
    assert fold({"any": [A, B]}, {"a": 2, "b": False})[0] is False
    assert fold({"not": A}, {"a": 1})[0] is False
    assert fold([{"not": A}, C], {"a": 2})[0] == C
    assert fold([B, {"any": [A, C]}])[0] == {"all": [B, {"any": [A, C]}]}


def test_ref_expands_definition_and_is_recorded():
    defs = {"STATE": {"when": {"any": [A, C]}}}
    reduced, refs = fold([B, {"ref": "STATE"}], {"b": True}, defs)
    assert reduced == {"any": [A, C]} and refs == {"STATE"}
    with pytest.raises(SystemExit, match="정의되지 않은"):
        fold([{"ref": "NOPE"}])
    with pytest.raises(SystemExit, match="min_status"):
        fold([{**A, "min_status": "MAYBE"}])


# ---- 원본 형식 2판: 빌드 결과 ----------------------------------------------------------------


@pytest.fixture
def knowledge(tmp_path) -> Path:
    src = tmp_path / "knowledge"
    shutil.copytree(build_kb.KNOWLEDGE, src)
    return src


def _edit_rule(src: Path, rule_id: str, **fields) -> None:
    """designated.yaml의 한 규칙에 필드를 더하거나 바꾼다(테스트용 복사본)."""
    path = src / "law_rules" / "designated.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for r in data["rules"]:
        if r["id"] == rule_id:
            r.update(fields)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _table(out: Path, mid: str) -> dict[str, dict]:
    rules = yaml.safe_load((out / "rules" / "tables" / f"{mid}.yaml").read_text(encoding="utf-8"))
    return {r["rule_id"]: r for r in rules["rules"]}


def test_definition_ref_builds_or_condition_and_review_unit(knowledge, tmp_path):
    defs_path = knowledge / "definitions.yaml"
    defs = yaml.safe_load(defs_path.read_text(encoding="utf-8"))["definitions"] or {}
    defs_path.write_text(
        yaml.safe_dump(
            {
                "definitions": {
                    **defs,  # 기존 정의(예: SLUDGE_STATE)는 그대로 둔다
                    "OIL_STATE": {
                        "title": "기름 함유 상태",
                        "when": {
                            "any": [
                                {"fact": "oil_presence", "op": "eq", "value": "present"},
                                {"fact": "oil_content_pct", "op": "gte", "value": 5},
                            ]
                        },
                        "source": "DEC-A1",
                        "location": "별표 1 제6호",
                    },
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    _edit_rule(
        knowledge,
        "S3-6-OIL-5PCT",
        when=[
            {
                "fact": "waste_kind",
                "op": "not_in",
                "value": ["waste_oil", "edible_oil", "adsorbent"],
            },
            {"ref": "OIL_STATE"},
        ],
    )
    out = tmp_path / "out"
    build_kb.Converter(knowledge).run(out)
    rule = _table(out, "pp")["pp:S3-6-OIL-5PCT:06-01-01"]
    assert {
        "any": [
            {"fact": "oil_presence", "op": "eq", "value": "present"},
            {"fact": "oil_content_pct", "op": "gte", "value": 5, "min_status": "EVIDENCED"},
        ]
    } in rule["when"]["all"]
    assert "def:OIL_STATE" in rule["review_units"]
    assert "def:OIL_STATE" in units_from(knowledge)
    load_kb(out)  # 엔진이 읽을 수 있다


def test_rule_exceptions_build_not_any_condition(knowledge, tmp_path):
    """예외는 규칙 안에 있고, 생성 규칙에 '아님' 조건과 검토 단위로 들어간다.

    이관 전(번호 대응표의 designated_exclusions)과 같은 결과다.
    """
    out = tmp_path / "out"
    build_kb.Converter(knowledge).run(out)
    rule = _table(out, "pp")["pp:S3-6-OIL-5PCT:06-01-01"]
    excl = [p for p in rule["when"]["all"] if "not" in p]
    assert excl and "any" in excl[0]["not"]
    assert {"S3-8GA-PCB-LIQUID", "S3-8NA-PCB-NONLIQUID"} <= set(rule["review_units"])


def test_code_map_exclusions_are_rejected(knowledge):
    path = knowledge / "code_map.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\ndesignated_exclusions:\n  - {drop: S3-6-, if_any_fired: [S3-8]}\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="exceptions"):
        build_kb.Converter(knowledge)


def test_min_status_and_interpret_conclusion(knowledge, tmp_path):
    # 서류 항목(DOCUMENT)을 원본에서 성적서·서류 필요(EVIDENCED)로, 결론은 해석 필요로
    _edit_rule(
        knowledge,
        "S3-9-TOXIC",
        when=[
            {"fact": "toxic_chemical_discard", "op": "eq", "value": True, "min_status": "EVIDENCED"}
        ],
        conclusion="interpret",
    )
    out = tmp_path / "out"
    build_kb.Converter(knowledge).run(out)
    rule = _table(out, "pp")["pp:S3-9-TOXIC"]
    assert rule["priority"] == build_kb.P_INTERPRET
    assert rule["then"]["outcome"] == "INTERPRETATION_NEEDED"
    assert rule["when"] == {
        "fact": "toxic_chemical_discard",
        "op": "eq",
        "value": True,
        "min_status": "EVIDENCED",
    }
