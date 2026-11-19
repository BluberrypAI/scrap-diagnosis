"""지정폐기물 안내(designated): 이유·경고·다음 할 일, FINAL_REVIEW 경고 문장, KB 검증.

계약: docs/ui/ui-contract.md(result.designated), docs/handoff-contract.md(designated)
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime

import pytest
import yaml

from app.agent import templates
from app.agent.responder import build_payload, respond
from app.agent.router import Branch, SessionState, run_engine
from app.domain.designated import WARNING
from app.domain.facts import Fact, FactStatus
from app.domain.handoff import build_handoff
from app.domain.verdict import build_result
from app.rules.loader import RuleDataError, load_kb
from tests.conftest import DATA, REAL
from tools.legacy_regression import AS_OF, load_rows, row_store

META, _ = load_rows()
BASE = META["base"]
NOW = datetime(2026, 11, 18, tzinfo=UTC)

ACTION_IDS = ["licensed_only", "plan_confirm", "storage", "recheck"]
OIL = dict(
    designated_residue=False,
    oil_presence="present",
    pcb_possible=False,
    toxic_chemical_discard=False,
)
NO_OIL = dict(
    designated_residue=False, oil_presence="none", pcb_possible=False, toxic_chemical_discard=False
)


def _step(kb, material, **answers):  # noqa: ANN001, ANN202
    row = {"id": "t", "material": material, "answers": answers}
    step = run_engine(kb, row_store(kb, BASE, row), SessionState(), AS_OF)
    assert step.decision.branch == Branch.FINAL_REVIEW, step.decision.branch
    return step


def _rule_index(kb):  # noqa: ANN001, ANN202
    return {r.rule_id: r for t in kb.tables for r in t.rules}


def _result(kb, step):  # noqa: ANN001, ANN202
    return build_result(step, _rule_index(kb), kb)


def _handoff(kb, step):  # noqa: ANN001, ANN202
    ev = step.evaluation
    return build_handoff(
        kb,
        case_id="c1",
        verdict_version=1,
        decided=ev.decided,
        rule=_rule_index(kb).get(ev.decided.rule_ids[0]),
        effective=step.effective,
        table_id=ev.table_id,
        table_version=ev.table_version,
        kb_version="kb-test",
        diagnosis_started_at=NOW,
        confirmed_at=NOW,
        as_of=AS_OF,
    )


def test_designated_oil_content_result_and_handoff(real_kb):
    step = _step(
        real_kb,
        "refractory",
        annex4_code="03-04-01",
        physical_state="solid",
        oil_content_pct=7.5,
        **OIL,
    )
    res = _result(real_kb, step)
    assert res.category == "DESIGNATED" and res.designated is not None
    d = res.designated
    assert d.reason and "7.5%" in d.reason and "기준 5% 이상" in d.reason
    assert d.warning == WARNING
    assert [a.id for a in d.next_actions] == ACTION_IDS
    by_id = {a.id: a for a in d.next_actions}
    assert by_id["licensed_only"].source_id == "ACT-WASTE"
    assert by_id["licensed_only"].source_title == "폐기물관리법"
    assert by_id["plan_confirm"].form == "form12"
    assert by_id["recheck"].source_id is None and by_id["recheck"].source_title is None
    assert all(a.source_title for a in d.next_actions if a.source_id)
    # 인계 객체도 같은 내용
    h = _handoff(real_kb, step).model_dump(mode="json")
    assert h["designated"] == res.model_dump(mode="json")["designated"]


def test_designated_reason_for_other_rules(real_kb):
    # 오니: 고시된 시설 + 수분 94.9%(any 중 참인 가지만) + 납 용출
    step = _step(
        real_kb,
        "sludge_ww_inorganic",
        annex4_code="01-02-01",
        sludge_facility_notified=True,
        sludge_water_pct=94.9,
        leach_pb=4.2,
        **NO_OIL,
    )
    r = _result(real_kb, step).designated.reason
    assert "납 용출 농도 4.2mg/L (기준 3mg/L 이상)" in r and "수분함량 94.9% (기준 95% 미만)" in r
    assert "고형물함량 5.1% (기준 5% 이상)" in r  # 수분에서 계산된 값도 실제로 참이다
    # 상태 조건만 있는 규칙: 사용자의 실제 답
    step = _step(real_kb, "pp", annex4_code="01-01-02", physical_state="liquid", **NO_OIL)
    res = _result(real_kb, step)
    assert res.category == "DESIGNATED"
    # 통합된 질문 원본의 쉬운 상태 명칭을 근거 안내에도 그대로 사용한다.
    assert res.designated.reason == "배출 시 상태: 흐르는 액체"


def test_general_has_no_designated(real_kb):
    step = _step(
        real_kb, "pp", annex4_code="01-01-02", physical_state="solid", oil_content_pct=1, **OIL
    )
    res = _result(real_kb, step)
    assert res.category == "GENERAL" and res.designated is None
    assert _handoff(real_kb, step).model_dump(mode="json")["designated"] is None


def test_reason_is_null_when_rule_has_no_usable_condition(real_kb):
    # 번호만으로 정해지는 규칙(폐유기용제 등)은 이유를 만들지 않는다 → 화면은 result.reason을 쓴다
    step = _step(real_kb, "solvent_halogen", annex4_code="04-01-00", **NO_OIL)
    res = _result(real_kb, step)
    assert res.category == "DESIGNATED"
    assert res.designated.reason is None
    assert len(res.designated.next_actions) == 4


def _message(kb, step):  # noqa: ANN001, ANN202
    out, _ = respond(None, kb, step, _rule_index(kb), prompt_version="t")
    return out.message


def test_final_review_message_ends_with_warning_once(real_kb):
    step = _step(
        real_kb,
        "refractory",
        annex4_code="03-04-01",
        physical_state="solid",
        oil_content_pct=7.5,
        **OIL,
    )
    msg = _message(real_kb, step)
    assert msg.endswith(WARNING) and msg.count(WARNING) == 1
    assert "지정폐기물" in msg.split(WARNING)[0]


def test_final_review_message_for_general_has_no_warning(real_kb):
    step = _step(
        real_kb, "pp", annex4_code="01-01-02", physical_state="solid", oil_content_pct=1, **OIL
    )
    assert WARNING not in _message(real_kb, step)


def test_llm_message_gets_warning_after_guard(real_kb):
    from app.agent.llm_client import LLMCall

    class FakeLLM:
        def complete_json(self, **kw):  # noqa: ANN003, ANN202
            msg = (
                "분류번호는 01-01-02 폐폴리프로필렌(지정폐기물)로 판정됩니다. 맞으면 확정해 주세요."
            )
            return LLMCall(
                name="respond",
                model="fake",
                prompt_version="t",
                system="",
                user="",
                parsed={"message": msg, "cited_basis_ids": []},
            )

    step = _step(real_kb, "pp", annex4_code="01-01-02", physical_state="liquid", **NO_OIL)
    out, _ = respond(FakeLLM(), real_kb, step, _rule_index(real_kb), prompt_version="t")
    assert out.message.endswith(WARNING) and out.message.count(WARNING) == 1


def test_payload_has_no_designated_field_for_llm(real_kb):
    step = _step(
        real_kb,
        "refractory",
        annex4_code="03-04-01",
        physical_state="solid",
        oil_content_pct=7.5,
        **OIL,
    )
    assert "designated" not in build_payload(real_kb, step, _rule_index(real_kb))


def test_answer_prefix_fallback_makes_no_false_promise():
    text = templates.answer_prefix({"user_question": "왜요?"})
    assert "안내해 드리겠습니다" not in text and "찾지 못했어요" in text


# ---- KB 검증 -------------------------------------------------------------------------------


def test_real_kb_loads_designated_actions(real_kb):
    assert [a.id for a in real_kb.designated_actions] == [
        "licensed_only",
        "code_check",
        *ACTION_IDS[1:],
    ]
    assert real_kb.designated_actions[2].source_title == "폐기물관리법 시행규칙"


def _kb_copy(tmp_path, edit):  # noqa: ANN001, ANN202
    d = tmp_path / "kb"
    shutil.copytree(REAL, d)
    path = d / "designated_guidance.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    edit(raw)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return d


def test_unknown_source_id_fails_loudly(tmp_path):
    d = _kb_copy(tmp_path, lambda raw: raw["next_actions"][0].update(source_id="NOPE-123"))
    with pytest.raises(RuleDataError, match="NOPE-123"):
        load_kb(d)


@pytest.mark.parametrize(
    "edit",
    [
        lambda raw: raw["next_actions"][0].update(form="form99"),
        lambda raw: raw["next_actions"][0].update(text=""),
        lambda raw: raw["next_actions"][0].update(extra=1),
        lambda raw: raw["next_actions"].append(dict(raw["next_actions"][0])),  # 중복 id
        lambda raw: raw.update(next_actions=[]),
    ],
)
def test_invalid_designated_entries_rejected(tmp_path, edit):
    with pytest.raises(RuleDataError):
        load_kb(_kb_copy(tmp_path, edit))


def test_sample_kb_has_designated_file_without_sources():
    kb = load_kb(DATA)
    assert {a.id for a in kb.designated_actions} == {*ACTION_IDS, "code_check"}
    assert all(a.source_id is None for a in kb.designated_actions)


# ---- 분류번호 계열별 문장·조항 위치 ------------------------------------


def _actions(kb, material, code, **answers):  # noqa: ANN001, ANN202
    step = _step(kb, material, annex4_code=code, **answers)
    return {a.id: a for a in _result(kb, step).designated.next_actions}


def test_source_ref_and_corrected_texts(real_kb):
    acts = _actions(real_kb, "solvent_halogen", "04-01-00", **NO_OIL)
    assert acts["licensed_only"].source_ref == "제18조제1항"
    assert acts["plan_confirm"].source_ref == "제18조의2"
    assert acts["plan_confirm"].source_id == "RULE-WASTE"
    assert acts["storage"].source_ref == "제4호나목" and acts["storage"].source_id == "RULE-A5"
    assert acts["recheck"].source_ref is None
    assert "허가증" in acts["licensed_only"].text


def test_family_variants_06_and_04(real_kb):
    oil = dict(physical_state="solid", oil_content_pct=7.5, **OIL)
    acts = _actions(real_kb, "refractory", "06-01-01", **oil)
    assert "50kg 이상(같은 묶음 합계 130kg" in acts["plan_confirm"].text
    assert "45일 안에" in acts["storage"].text and "60일" not in acts["storage"].text
    acts = _actions(real_kb, "solvent_halogen", "04-01-00", **NO_OIL)
    assert "50kg 이상" in acts["plan_confirm"].text and "45일 안에" in acts["storage"].text


def test_family_variant_05_is_100kg_60days(real_kb):
    kb_rules = [r for t in real_kb.tables if t.table_id == "paint_oil" for r in t.rules]
    code = next(r.then.code for r in kb_rules if r.then.code and r.then.code.startswith("05-"))
    # 법 규칙을 직접 만족시키기 어려워 안내 문장 선택만 확인한다(판정과 무관)
    from app.domain.designated import _text_for

    plan = next(a for a in real_kb.designated_actions if a.id == "plan_confirm")
    storage = next(a for a in real_kb.designated_actions if a.id == "storage")
    assert "100kg 이상(같은 묶음 합계 200kg" in _text_for(plan, code)
    assert "60일 안에" in _text_for(storage, code)
    assert "양과 관계없이" in _text_for(plan, "08-01-00")
    assert "100kg" in _text_for(plan, "02-01-00") and "45일" in _text_for(storage, "02-01-00")


def test_mixed_family_01_and_null_code_use_default(real_kb):
    plan = next(a for a in real_kb.designated_actions if a.id == "plan_confirm")
    from app.domain.designated import _text_for

    assert _text_for(plan, "01-01-02") == plan.text == _text_for(plan, None)
    assert _text_for(plan, "03-04-01") == plan.text
    assert "한 달 평균" not in plan.text


def test_variant_validation(tmp_path):
    bad = [
        lambda raw: raw["next_actions"][2].update(variants=[{"families": ["6"], "text": "x"}]),
        lambda raw: raw["next_actions"][2].update(
            variants=[{"families": ["06"], "text": "x"}, {"families": ["06"], "text": "y"}]
        ),
        lambda raw: raw["next_actions"][2].update(variants=[{"families": ["06"], "extra": 1}]),
        lambda raw: raw["next_actions"][2].update(source_ref=""),
        lambda raw: raw["next_actions"][0].update(only_outcome="NOPE"),
    ]
    for i, edit in enumerate(bad):
        with pytest.raises(RuleDataError):
            load_kb(_kb_copy(tmp_path / str(i), edit))


# ---- 번호를 '모름'이라고 답해도 지정폐기물 결론이 막히지 않는다 ----------------------------


def _unknown_code_step(kb, material, **answers):  # noqa: ANN001, ANN202
    row = {"id": "t", "material": material, "answers": answers}
    store = row_store(kb, BASE, row)
    store.append(
        Fact(
            key="annex4_code",
            value=None,
            status=FactStatus.DECLARED_UNKNOWN,
            source_type="UTTERANCE",
            source_ref="u",
        )
    )
    return run_engine(kb, store, SessionState(), AS_OF)


@pytest.mark.parametrize(
    ("material", "answers", "family_codes"),
    [
        ("pp", dict(physical_state="solid", oil_content_pct=7.5, **OIL), "06"),
        ("solvent_halogen", NO_OIL, "04"),
        ("h2so4", dict(physical_state="liquid", ph=1, **NO_OIL), "02"),
        ("paint_oil", dict(physical_state="liquid", **NO_OIL), "05"),
    ],
)
def test_code_unknown_still_concludes_designated(real_kb, material, answers, family_codes):
    step = _unknown_code_step(real_kb, material, **answers)
    assert step.decision.branch == Branch.FINAL_REVIEW, (material, step.decision.branch)
    d = step.evaluation.decided
    assert d.code is None and d.category == "DESIGNATED"
    assert d.outcome == "DESIGNATED_CODE_NEEDED"
    res = _result(real_kb, step)
    assert res.result_type == "NO_CODE" and res.designated is not None
    ids = [a.id for a in res.designated.next_actions]
    assert ids == ["licensed_only", "code_check", "plan_confirm", "storage", "recheck"]
    by_id = {a.id: a for a in res.designated.next_actions}
    assert by_id["code_check"].text.startswith("세부 분류번호는 예전에 낸")
    assert by_id["code_check"].source_id is None
    assert "한 달 평균" not in by_id["plan_confirm"].text  # 번호가 없으니 기본 문장
    assert res.designated.warning == WARNING
    assert "지정폐기물입니다" in res.conclusion
    h = _handoff(real_kb, step).model_dump(mode="json")
    assert h["result_type"] == "NO_CODE" and h["outcome"] == "DESIGNATED_CODE_NEEDED"
    assert h["route_guidance"]["action"] == "MANUAL_CLASSIFICATION"
    assert h["designated"]["next_actions"][1]["id"] == "code_check"
    assert WARNING in _message(real_kb, step)


def test_choosing_a_code_still_gives_coded_verdict(real_kb):
    oil = dict(physical_state="solid", oil_content_pct=7.5, **OIL)
    step = _step(real_kb, "pp", annex4_code="06-01-02", **oil)
    d = step.evaluation.decided
    assert d.code == "06-01-02" and d.outcome is None
    assert not any(a.id == "code_check" for a in _result(real_kb, step).designated.next_actions)
    # 번호를 아직 안 물었을 때는 번호를 묻는다(모름이 아니므로 결론을 내지 않음)
    row = {"id": "t", "material": "pp", "answers": oil}
    ask = run_engine(real_kb, row_store(real_kb, BASE, row), SessionState(), AS_OF)
    assert ask.decision.branch == Branch.ASK_FACT and ask.decision.question.key == "annex4_code"


def test_declared_unknown_op_semantics(real_kb):
    from app.rules.evaluator import TV, eval_expr
    from app.rules.model import Cond

    c = Cond(fact="annex4_code", op="declared_unknown", value=None)
    cat = real_kb.catalog

    def F(**kw):  # noqa: ANN003, ANN202
        return {"annex4_code": Fact(key="annex4_code", **kw)}

    assert eval_expr(c, F(value=None, status=FactStatus.DECLARED_UNKNOWN), cat) == TV.TRUE
    assert eval_expr(c, F(value="06-01-01", status=FactStatus.CLAIMED), cat) == TV.FALSE
    assert eval_expr(c, {}, cat) == TV.FALSE  # 아직 묻지 않음
    assert eval_expr(c, F(value=None, status=FactStatus.UNKNOWN), cat) == TV.FALSE
