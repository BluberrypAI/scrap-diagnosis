"""판정 흐름 실행기 단위 테스트(도메인 규칙과 무관한 합성 규칙 사용)."""

from pathlib import Path

import pytest
import yaml

from app.engine.flow import STAGES, TV, FlowError, compare, evaluate, load_flow, run


def write_flow(tmp: Path, stages: dict[str, dict]) -> list:
    for i, name in enumerate(STAGES):
        doc = {"stage": name, "order": (i + 1) * 10, "on_no_match": "continue", "rules": []}
        doc.update(stages.get(name, {}))
        (tmp / f"{name}.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return load_flow(tmp)


def test_compare_three_valued():
    assert compare("eq", "pp", "pp") is TV.TRUE
    assert compare("eq", None, "pp") is TV.UNKNOWN
    assert compare("eq", "unknown", "pp") is TV.UNKNOWN
    assert compare("eq", "unknown", "unknown") is TV.TRUE
    assert compare("eq", "pp", "unknown") is TV.FALSE
    assert compare("gte", 300, 300) is TV.TRUE
    assert compare("gte", 299, 300) is TV.FALSE
    assert compare("exists", None, True) is TV.FALSE
    assert compare("eq", "yes", True) is TV.TRUE  # YAML 불리언 yes


def test_kleene_all_any_not():
    f = {"a": "x"}
    u: set[str] = set()
    assert (
        evaluate({"all": [{"fact": "a", "eq": "x"}, {"fact": "b", "eq": "y"}]}, f, u) is TV.UNKNOWN
    )
    assert evaluate({"all": [{"fact": "a", "eq": "z"}, {"fact": "b", "eq": "y"}]}, f, u) is TV.FALSE
    assert evaluate({"any": [{"fact": "a", "eq": "x"}, {"fact": "b", "eq": "y"}]}, f, u) is TV.TRUE
    assert evaluate({"not": {"fact": "b", "eq": "y"}}, f, u) is TV.UNKNOWN
    assert u == {"b"}


def test_first_true_rule_and_continue(tmp_path):
    flow = write_flow(
        tmp_path,
        {
            "10_is_waste": {
                "rules": [
                    {
                        "id": "S1",
                        "when": {"fact": "a", "eq": "no"},
                        "then": {"outcome": "NOT_WASTE"},
                    }
                ]
            },
            "70_code": {
                "rules": [
                    {
                        "id": "C1",
                        "when": {"fact": "m", "eq": "pp"},
                        "then": {"outcome": "GENERAL", "code": "11-11-11"},
                    }
                ]
            },
        },
    )
    assert run(flow, {"a": "no"}).outcome == "NOT_WASTE"
    r = run(flow, {"a": "yes", "m": "pp"})
    assert (r.outcome, r.code) == ("GENERAL", "11-11-11")


def test_unknown_before_true_blocks(tmp_path):
    flow = write_flow(
        tmp_path,
        {
            "10_is_waste": {
                "rules": [
                    {
                        "id": "S1",
                        "when": {"fact": "a", "eq": "no"},
                        "then": {"outcome": "NOT_WASTE"},
                    }
                ]
            }
        },
    )
    r = run(flow, {"a": "unknown"})
    assert r.outcome == "INSUFFICIENT_INFO"
    assert r.blocking_facts == ["a"]


def test_all_stages_pass_is_insufficient(tmp_path):
    flow = write_flow(tmp_path, {})
    assert run(flow, {}).outcome == "INSUFFICIENT_INFO"


def test_duplicate_rule_id_rejected(tmp_path):
    rule = {"id": "X", "when": {"fact": "a", "eq": "1"}, "then": "continue"}
    with pytest.raises(FlowError):
        write_flow(tmp_path, {"10_is_waste": {"rules": [rule]}, "20_circular": {"rules": [rule]}})


def test_range_values_use_three_valued_comparison():
    from app.engine.flow import TV, compare

    below = {"hi": 0.5, "hi_inc": False}  # 0.5 미만(불검출 포함)
    assert compare("gte", below, 5) is TV.FALSE
    assert compare("lt", below, 5) is TV.TRUE
    straddle = {"hi": 7, "hi_inc": False}  # 7 미만: 5 이상일 수도 아닐 수도
    assert compare("gte", straddle, 5) is TV.UNKNOWN
    assert compare("gte", {"lo": 6, "lo_inc": True}, 5) is TV.TRUE
    assert compare("exists", below, True) is TV.TRUE
