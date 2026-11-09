"""M2 완료 조건: 샘플 시나리오의 결과·질문 수, 결정성, 순서 불변성."""

import random

import pytest
import yaml

from app.agent.simulation import simulate
from tests.conftest import DATA

SCENARIOS = {
    s["id"]: s
    for s in yaml.safe_load((DATA / "scenarios" / "basic.yaml").read_text(encoding="utf-8"))
}

EXPECT = {
    "SIM-SCREEN-NONE": ("FINAL_REVIEW", "SAMPLE-A", 4),
    "SIM-SCREEN-EXPAND": ("FINAL_REVIEW", "SAMPLE-A", 7),
    "SIM-PREFILL": ("FINAL_REVIEW", "SAMPLE-A", 2),
    "SIM-PCB": ("FINAL_REVIEW", "SAMPLE-D1", 5),
    "SIM-OUT-OF-SCOPE": ("UNSUPPORTED", None, 1),
    "SIM-REFUSE": ("UNSUPPORTED", None, 1),
    "SIM-CLAIM-RANGE": ("FINAL_REVIEW", "SAMPLE-C", 2),
    "SIM-MIXED-PROFILE": ("FINAL_REVIEW", "SAMPLE-Z", 0),
}


@pytest.mark.parametrize("sid", sorted(EXPECT))
def test_scenarios(kb, sid):
    res = simulate(kb, SCENARIOS[sid])
    assert (res.final_branch, res.final_code, res.questions_asked) == EXPECT[sid]


def test_screening_saves_questions(kb):
    none = simulate(kb, SCENARIOS["SIM-SCREEN-NONE"])
    expand = simulate(kb, SCENARIOS["SIM-SCREEN-EXPAND"])
    assert none.final_code == expand.final_code
    assert expand.questions_asked - none.questions_asked == 3


def test_simulation_is_deterministic(kb):
    a = simulate(kb, SCENARIOS["SIM-SCREEN-EXPAND"]).model_dump()
    b = simulate(kb, SCENARIOS["SIM-SCREEN-EXPAND"]).model_dump()
    assert a == b


@pytest.mark.parametrize("seed", range(5))
def test_setup_fact_order_does_not_change_transcript(kb, seed):
    sc = SCENARIOS["SIM-REFUSE"]
    items = list(sc["setup"]["facts"].items())
    random.Random(seed).shuffle(items)
    shuffled = dict(sc, setup={"facts": dict(items)})
    assert simulate(kb, sc).model_dump() == simulate(kb, shuffled).model_dump()
