"""기존 엔진 소재별 판정표 4281행과의 회귀 비교.

기존 STOP 행(INTERPRETATION_NEEDED·CODE_NEEDS_TEST·NO_MIXTURE_RULE)은 새 엔진에서 코드 없는 결론
(FINAL_REVIEW, outcome = 사유)으로 오며, 사유가 같으면 MATCH다.

허용하는 차이(data/real/conversion_report.md '의도한 차이'):
- FEWER_CHOICES: 지정 사유가 여럿일 때 사유별로 번호를 좁혀 선택지가 기존보다 적다.
- 산·알칼리가 지정 기준 미만이면 기존은 일반 그룹·번호를 물었지만
  새 엔진은 코드 없는 결론 NO_GENERAL_CODE(FINAL_REVIEW @NO_GENERAL_CODE)로 안내한다.
- 산·알칼리 + 유해화학물질: 법이 제9호를 제외하므로, 새 엔진은 제외를 먼저 적용해 산·알칼리 번호
  하나로 확정한다(기존은 제외 전 사유로 좁히기를 판단해 선택지 여러 개).
"""

import pytest

from tools.legacy_regression import run

ACID_ALKALI = {
    "hcl",
    "h2so4",
    "hno3",
    "hf",
    "acid_lcd_semi",
    "acid_other",
    "caustic_solution",
    "ammonia_solution",
    "alkali_other",
}


@pytest.fixture(scope="module")
def result(real_kb):
    return run(real_kb)


def test_codes_and_stops_match_exactly(result):
    kinds = result["by_kind"]
    assert kinds.get("CODE/MATCH") == 2332 and "CODE/DIFF" not in kinds
    assert kinds.get("STOP/MATCH") == 233 and "STOP/DIFF" not in kinds


def test_code_choice_matches_or_has_fewer_options(result):
    kinds = result["by_kind"]
    assert (
        kinds.get("CODE_CHOICE/MATCH", 0)
        + kinds.get("CODE_CHOICE/FEWER_CHOICES", 0)
        + kinds.get("CODE_CHOICE/DIFF", 0)
        == 1716
    )


def test_remaining_diffs_are_known_acid_alkali_cases(result):
    for line in result["diffs"]:
        mid = line.split("#")[0]
        assert mid in ACID_ALKALI, line
        assert ("NO_GENERAL_CODE" in line) or ("FINAL_REVIEW 02-0" in line), line
    assert len(result["diffs"]) == 36


def test_extra_questions_are_rare(result):
    # 기존 엔진이 묻지 않고 끝낸 사실을 새 엔진이 더 묻는 행: 잔류물 해석 사례(질의회신 근거)뿐
    extra = result["extra_questions"]
    assert set(extra) <= {0, 1}
    assert extra.get(1, 0) <= 200
