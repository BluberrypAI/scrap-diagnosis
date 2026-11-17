"""기존 엔진 소재별 판정표 4281행과의 회귀 비교.

기존 STOP 행(INTERPRETATION_NEEDED·CODE_NEEDS_TEST·NO_MIXTURE_RULE)은 새 엔진에서 코드 없는 결론
(FINAL_REVIEW, outcome = 사유)으로 오며, 사유가 같으면 MATCH다.

허용하는 차이(data/real/conversion_report.md '의도한 차이'):
- FEWER_CHOICES: 지정 사유가 여럿일 때 사유별로 번호를 좁혀 선택지가 기존보다 적다.
- 산·알칼리가 지정 기준 미만이면 기존은 일반 그룹·번호를 물었지만
  새 엔진은 코드 없는 결론 NO_GENERAL_CODE(FINAL_REVIEW @NO_GENERAL_CODE)로 안내한다.
- 산의 pH가 2.0 이하가 아니면 결론 전에 유기용제 혼합 여부를 묻는다
  (2026-11-10, 원주청 질의회신 사례 56). 기존 판정표에는 이 사실이 없어
  그 행은 ASK_FACT organic_solvent_mixed에서 멈춘다.
- 산·알칼리 + 유해화학물질: 법이 제9호를 제외하므로, 새 엔진은 제외를 먼저 적용해 산·알칼리 번호
  하나로 확정한다(기존은 제외 전 사유로 좁히기를 판단해 선택지 여러 개).
- 폐이차전지(docs/rule-changes/d6-secondary-battery.md): 판정표에는 전지 종류가 없어
  새 엔진은 종류를 묻는다(ASK_FACT battery_type). 손상 규칙은 이차전지에만 적용하므로
  일차전지·양극재·연료전지의 '손상' 행은 해석 필요 대신 일반 번호가 된다.
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
# 유기성·무기성 모름 오니(2026-11-13, 별표 5 40% 기준): 기존은 '시험 필요'로 멈췄지만 이제
# 유기성물질 함량 성적서를 요청한다(docs/rule-changes/organic-sludge-40.md). 30행
ORGANIC_UNKNOWN = {"sludge_ww_unknown", "sludge_proc_unknown"}
BATTERY_ASKS_TYPE = {"battery_ev", "battery_drive", "battery_secondary_other"}
NOT_SECONDARY = {"battery_primary", "battery_cathode", "battery_fuel_cell"}


@pytest.fixture(scope="module")
def result(real_kb):
    return run(real_kb)


def test_codes_and_stops_match_exactly(result):
    kinds = result["by_kind"]
    # 전지(종류 질문 15행, 손상 6행)와 유기성·무기성 모름 오니(30행)만 다르다
    assert kinds.get("CODE/MATCH") == 2317 and kinds.get("CODE/DIFF") == 15
    assert kinds.get("STOP/MATCH") == 197 and kinds.get("STOP/DIFF") == 36


def test_code_choice_matches_or_has_fewer_options(result):
    kinds = result["by_kind"]
    assert (
        kinds.get("CODE_CHOICE/MATCH", 0)
        + kinds.get("CODE_CHOICE/FEWER_CHOICES", 0)
        + kinds.get("CODE_CHOICE/DIFF", 0)
        == 1716
    )


def test_remaining_diffs_are_known_cases(result):
    acid = battery = sludge = 0
    for line in result["diffs"]:
        mid = line.split("#")[0]
        if mid in ORGANIC_UNKNOWN:
            assert "CODE_NEEDS_TEST" in line and "REQUEST_EVIDENCE" in line, line
            sludge += 1
        elif mid in BATTERY_ASKS_TYPE:
            assert "ASK_FACT battery_type" in line, line
            battery += 1
        elif mid in NOT_SECONDARY:
            assert '"battery_damaged": true' in line and "FINAL_REVIEW 51-41-" in line, line
            battery += 1
        else:
            assert mid in ACID_ALKALI, line
            assert (
                ("NO_GENERAL_CODE" in line)
                or ("FINAL_REVIEW 02-0" in line)
                or ("ASK_FACT organic_solvent_mixed" in line)
            ), line
            acid += 1
    assert (acid, battery, sludge) == (36, 21, 30)
    asked = [x for x in result["diffs"] if "ASK_FACT organic_solvent_mixed" in x]
    assert len(asked) == 18
    alkali = {"caustic_solution", "ammonia_solution", "alkali_other"}
    assert all(x.split("#")[0] in ACID_ALKALI - alkali for x in asked)


def test_extra_questions_are_rare(result):
    # 기존 엔진이 묻지 않고 끝낸 사실을 새 엔진이 더 묻는 행: 잔류물 해석 사례(질의회신 근거)뿐
    extra = result["extra_questions"]
    assert set(extra) <= {0, 1}
    assert extra.get(1, 0) <= 200
