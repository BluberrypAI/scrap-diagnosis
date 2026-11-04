import itertools
import json
import random

import pytest

from wastecalc import UNKNOWN, InputError, evaluate, load_kb, render_text
from wastecalc.engine import FALSE, TRUE, eval_stage, parse_answers

KB = load_kb()

WASTE_OK = {"no_longer_needed": True, "direct_reinput": False, "circular_resource_recognized": False}
APPLIES = {**WASTE_OK, "law_exclusion": "none"}
S2_ALL_NO = {"emission_facility": False, "public_facility": "none", "waste_facility": False,
             "designated_waste_emitted": False, "daily_avg_kg": 100, "work_type": "none"}
# S3에서 '지정폐기물 아님'이 되는 최소 사실 (금속 스크랩 등)
S3_PLAIN = {"waste_kind": "other", "physical_state": "solid", "oil_presence": "none",
            "pcb_possible": False, "toxic_chemical_discard": False}


def ev(answers, strict=False):
    return evaluate(answers, strict=strict, kb=KB)


# ---------------------------------------------------------------- 입력 경계

@pytest.mark.parametrize("answers", [
    {"no_such_fact": True},
    {"law_exclusion": "sewage"},            # 허용 값 아님
    {"no_longer_needed": "yes"},            # 문자열 bool
    {"daily_avg_kg": True},                 # bool을 숫자로
    {"daily_avg_kg": -1},
    {"daily_avg_kg": float("nan")},
    {"emission_facility": {"source": "GUESS", "value": True}},
    {"emission_facility": {"conflict": [True]}},
])
def test_rejects_values_outside_schema(answers):
    with pytest.raises(InputError):
        ev(answers)


def test_conflict_with_same_values_collapses():
    r = ev({**APPLIES, "daily_avg_kg": {"conflict": [400, 400]}})
    assert r["answers"]["daily_avg_kg"]["value"] == 400


# ---------------------------------------------------------------- 대표 흐름

def test_empty_input_asks_first_question_with_criteria():
    r = ev({})
    assert r["status"] == "NEED_INFO"
    assert r["stage"] == "S0"
    assert r["next_question"]["fact"] == "no_longer_needed"
    assert all(c["decides"] for c in r["resolution"])


def test_not_needed_is_not_waste():
    r = ev({"no_longer_needed": False, "circular_resource_recognized": False})
    assert r["status"] == "DETERMINED" and r["decided"][-1]["conclusion"] == "NOT_WASTE"


def test_circular_resource():
    r = ev({"circular_resource_recognized": True})
    assert r["decided"][-1]["conclusion"] == "CIRCULAR_RESOURCE"


def test_direct_reinput_is_interpretive_basis():
    r = ev({"direct_reinput": True, "circular_resource_recognized": False})
    assert r["decided"][-1]["conclusion"] == "NOT_WASTE"
    assert r["weak_basis"] and r["weak_basis"][0]["law_based"] is False
    strict = ev({"direct_reinput": True, "circular_resource_recognized": False}, strict=True)
    assert strict["status"] == "NEED_EXPERT" and strict["provisional"] is True


def test_wastewater_excluded():
    r = ev({**WASTE_OK, "law_exclusion": "wastewater"})
    assert r["decided"][-1]["conclusion"] == "EXCLUDED"


def test_emission_facility_makes_business_waste_then_asks_s3():
    r = ev({**APPLIES, "emission_facility": True})
    assert r["decided"][-1]["conclusion"] == "BUSINESS"
    assert r["stage"] == "S3" and r["next_question"]["fact"] == "waste_kind"
    r2 = ev({**APPLIES, "emission_facility": True, **S3_PLAIN})
    assert r2["decided"][-1]["conclusion"] == "NOT_DESIGNATED"
    assert r2["stage"] == "S4" and r2["next_question"]["fact"] == "general_group"
    r3 = ev({**APPLIES, "emission_facility": True, **S3_PLAIN, "general_group": "51-29", "code": "51-29-01"})
    assert r3["status"] == "DETERMINED" and r3["summary"]["S4"] == "51-29-01 고철"
    assert r3["summary"]["S5"] == "재활용 가능 유형: R-3-3, R-4-1, R-10"


def test_household_needs_every_business_route_false():
    r = ev({**APPLIES, **S2_ALL_NO, **S3_PLAIN})
    assert r["decided"][-1]["conclusion"] == "HOUSEHOLD"
    partial = {k: v for k, v in S2_ALL_NO.items() if k != "waste_facility"}
    r2 = ev({**APPLIES, **partial, **S3_PLAIN})
    assert r2["status"] == "NEED_INFO" and r2["next_question"]["fact"] == "waste_facility"


def test_strict_mode_marks_unreviewed_conclusion_provisional():
    r = ev({**APPLIES, "emission_facility": True, **S3_PLAIN, "general_group": "51-29", "code": "51-29-01"},
           strict=True)
    assert r["status"] == "NEED_EXPERT" and r["provisional"]
    assert r["summary"]["S4"] == "51-29-01 고철"


def test_unknown_answers_return_how_to_check_not_a_guess():
    all_unknown = {f: UNKNOWN for f in S2_ALL_NO}
    r = ev({**APPLIES, **all_unknown, **{f: UNKNOWN for f in S3_PLAIN}})
    assert r["status"] == "NEED_INFO"
    assert r["next_question"] is None
    assert r["conclusion"] is None
    states = {c["fact"]: c["state"] for c in r["resolution"]}
    assert set(states) - {"this_waste_designated"} and all(
        v == "UNKNOWN" for f, v in states.items() if f != "this_waste_designated")
    assert all(c["how_to_check"] or c["type"] == "enum" for c in r["resolution"])


def test_conflict_that_matters_needs_expert():
    answers = {**APPLIES, **S2_ALL_NO, **S3_PLAIN, "emission_facility": {"conflict": [True, False], "source": "DOCUMENT"}}
    r = ev(answers)
    assert r["status"] == "NEED_EXPERT" and r["reason"] == "FACT_CONFLICT"


def test_series_work_asks_tonnage_only_after_work_type():
    r = ev({**APPLIES, "emission_facility": False})
    assert r["next_question"]["fact"] == "work_type"
    r2 = ev({**APPLIES, "emission_facility": False, "work_type": "series"})
    assert r2["next_question"]["fact"] == "work_total_ton"


# ---------------------------------------------------------------- 경계값

@pytest.mark.parametrize("kg,business", [(299.99, False), (300, True), (300.01, True)])
def test_daily_300kg_boundary(kg, business):
    r = ev({**APPLIES, **S2_ALL_NO, **S3_PLAIN, "daily_avg_kg": kg})
    assert (r["decided"][2]["conclusion"] == "BUSINESS") is business


@pytest.mark.parametrize("work", ["construction", "series"])
@pytest.mark.parametrize("ton,business", [(4.99, False), (5, True), (5.01, True)])
def test_work_5ton_boundary(work, ton, business):
    r = ev({**APPLIES, **S2_ALL_NO, **S3_PLAIN, "work_type": work, "work_total_ton": ton})
    assert (r["decided"][2]["conclusion"] == "BUSINESS") is business


def test_tonnage_ignored_when_not_work():
    r = ev({**APPLIES, **S2_ALL_NO, **S3_PLAIN, "work_type": "none", "work_total_ton": 100})
    assert r["decided"][-1]["conclusion"] == "HOUSEHOLD"


# ---------------------------------------------------------------- 성질 테스트

S2_DOMAIN = {
    "emission_facility": [True, False, UNKNOWN],
    "public_facility": list(KB.facts["public_facility"]["values"]) + [UNKNOWN],
    "waste_facility": [True, False, UNKNOWN],
    "designated_waste_emitted": [True, False, UNKNOWN],
    "daily_avg_kg": [299.99, 300, UNKNOWN],
    "work_type": ["none", "construction", "series", UNKNOWN],
    "work_total_ton": [4.99, 5, UNKNOWN],
    "this_waste_designated": [True, False, UNKNOWN],
}


def _parse(combo):
    """파생 사실(this_waste_designated)은 사용자 입력이 아니므로 직접 Answer로 넣는다."""
    from wastecalc.engine import Answer
    derived = combo.get("this_waste_designated")
    rest = {k: v for k, v in combo.items() if k != "this_waste_designated"}
    a = parse_answers(KB, rest)
    if derived is not None and derived != UNKNOWN:
        a["this_waste_designated"] = Answer("VALUE", (derived,), "DERIVED")
    return a


def _combos(domain):
    keys = list(domain)
    for vals in itertools.product(*(domain[k] for k in keys)):
        yield dict(zip(keys, vals))


def test_s2_exhaustive_no_overlap_no_hole():
    """S2 사실 조합 전부: 두 결론이 동시에 성립하지 않고(겹침), 모르는 값이 없으면 반드시 하나로 정해진다(구멍)."""
    n = 0
    for combo in _combos(S2_DOMAIN):
        st = eval_stage(KB, "S2", _parse(combo))
        trues = [c for c, s in st["candidates"].items() if s == TRUE]
        assert len(trues) <= 1, combo
        if UNKNOWN not in combo.values():
            assert len(trues) == 1, combo
        n += 1
    expected = 1
    for vals in S2_DOMAIN.values():
        expected *= len(vals)
    assert n == expected


def test_s0_exhaustive_no_overlap_no_hole():
    domain = {"no_longer_needed": [True, False, UNKNOWN], "direct_reinput": [True, False, UNKNOWN],
              "circular_resource_recognized": [True, False, UNKNOWN]}
    for combo in _combos(domain):
        st = eval_stage(KB, "S0", parse_answers(KB, combo))
        trues = [c for c, s in st["candidates"].items() if s == TRUE]
        assert len(trues) <= 1, combo
        if UNKNOWN not in combo.values():
            assert len(trues) == 1, combo


def test_s1_every_value_decides_exactly_one():
    for v in KB.facts["law_exclusion"]["values"]:
        st = eval_stage(KB, "S1", parse_answers(KB, {"law_exclusion": v}))
        assert sum(s == TRUE for s in st["candidates"].values()) == 1, v


def test_monotonic_adding_facts_never_revives_eliminated_candidates():
    rng = random.Random(7)
    combos = list(_combos(S2_DOMAIN))
    for full in rng.sample(combos, 400):
        known = {k: v for k, v in full.items() if v != UNKNOWN}
        keys = list(known)
        rng.shuffle(keys)
        prev_false: set[str] = set()
        for i in range(len(keys) + 1):
            st = eval_stage(KB, "S2", _parse({k: known[k] for k in keys[:i]}))
            now_false = {c for c, s in st["candidates"].items() if s == FALSE}
            assert prev_false <= now_false, (keys[:i], full)
            prev_false = now_false


def test_determined_always_backed_by_a_fired_rule():
    domain = {k: v for k, v in S2_DOMAIN.items() if k != "this_waste_designated"}
    for combo in _combos(domain):
        r = ev({**APPLIES, **combo, **S3_PLAIN})
        for d in r["decided"]:
            assert d["basis"], (combo, d)
        if r["status"] == "DETERMINED":
            assert r["conclusion"]


def test_deterministic_output():
    a = {**APPLIES, "emission_facility": UNKNOWN, "daily_avg_kg": 250}
    assert json.dumps(ev(a), sort_keys=True, ensure_ascii=False) == json.dumps(ev(a), sort_keys=True, ensure_ascii=False)


def test_render_every_status():
    cases = [{}, {**APPLIES, "emission_facility": True},
             {**APPLIES, **S2_ALL_NO, "emission_facility": {"conflict": [True, False]}},
             {**APPLIES, "emission_facility": True, "waste_kind": "acid", "physical_state": "liquid"},
             {**APPLIES, "emission_facility": True, "waste_kind": "paint_solvent_mix", "paint_mixed_source": "other"},
             {**WASTE_OK, "law_exclusion": "radioactive"}]
    for c in cases:
        for strict in (True, False):
            text = render_text(ev(c, strict=strict))
            assert text.startswith("■ ")
