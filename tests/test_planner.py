"""다음 질문 계산기 테스트(실제 knowledge/flow 규칙과 문진 계획 사용)."""

from app.engine.planner import load, next_question

STAGES, PLAN = load()


def ask(answers):
    return next_question(STAGES, PLAN, answers)


def test_first_question_is_material():
    n = ask({})
    assert not n.done
    assert n.question["id"] == "Q-MATERIAL"


def test_form_asked_even_if_not_needed_for_verdict():
    n = ask({"material": "pp"})
    assert n.question["id"] == "Q-FORM"


def test_unasked_is_not_unknown():
    # 내용물 질문을 하기 전에 '내용물 모름 → 지정 가능성'으로 끝나면 안 된다
    n = ask({"material": "pp", "input_form": "scrap"})
    assert not n.done


def test_oil_pct_skipped_when_no_oil():
    answers = {
        "material": "pp",
        "input_form": "scrap",
        "foamed": "no",
        "fishery_origin": "none",
        "packaging_used": "no",
        "oil_presence": "none",
        "residue": "none",
        "chemical_itself": "no",
    }
    n = ask(answers)
    assert "oil_pct_evidenced" not in n.facts


def test_pp_scrap_full_path_ends_general():
    answers = {
        "material": "pp",
        "input_form": "scrap",
        "foamed": "no",
        "fishery_origin": "none",
        "packaging_used": "no",
        "oil_presence": "none",
        "residue": "none",
        "chemical_itself": "no",
        "discharged": "yes",
        "law_exclusion": "none",
        "circular_recognized": "no",
        "emission_facility": "yes",
    }
    n = ask(answers)
    assert n.done
    assert (n.result.outcome, n.result.code) == ("GENERAL", "51-03-01")


def test_medicine_small_not_asked_when_contents_unknown():
    answers = {"material": "aluminium", "input_form": "can", "can_contents": "unknown"}
    n = ask(answers)
    assert "medicine_small" not in n.facts
