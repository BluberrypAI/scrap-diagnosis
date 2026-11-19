"""사용자에게 보이는 문구: 조사, 내부 정보 노출, 근거 이름 (2026-11-10 화면 문구 점검 A1~A7)."""

import re
import sys
from pathlib import Path

import pytest
import yaml

from app.agent import templates
from app.domain.josa import josa
from tests.conftest import REAL

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from build_kb import KNOWLEDGE, basis_ref  # noqa: E402


@pytest.mark.parametrize(
    ("word", "particle", "expected"),
    [
        ("시험성적서", "을", "를"),
        ("기기 명판 사진 또는 절연유 분석 기록", "을", "을"),
        ("배출시설 설치허가증(신고증명서)", "을", "을"),  # 괄호 앞 낱말 기준
        ("물질안전보건자료(MSDS)", "을", "를"),
        ("기름 묻음·섞임, PCB 관련", "은", "은"),
        ("pH", "을", "를"),
        ("95%", "을", "를"),
        ("51-03-01", "을", "을"),  # 1 → 일
        ("02-02-00", "로", "으로"),  # 0 → 영
        ("51-03-01", "로", "로"),  # ㄹ 받침은 '로'
        ("오니", "이", "가"),
        ("수분", "과", "과"),
    ],
)
def test_josa_follows_final_sound(word, particle, expected):
    assert josa(word, particle) == expected


def test_ask_fact_keeps_questions_ending_with_parenthesis():
    # A1: 괄호로 끝나는 질문에 '을(를) 알려 주세요'를 붙이지 않는다
    q = "이 폐기물에 해당하는 것이 있나요? (기름·잔류물·PCB·유해화학물질·유기용제 혼합)"
    assert templates.ask_fact({"question": {"question": q}}) == q
    assert templates.ask_fact({"question": {"question": "배출 시 상태"}}) == (
        "배출 시 상태를 알려 주세요."
    )


def test_group_progress_uses_real_particle():
    msg = templates.ask_fact(
        {"question": {"question": "-", "already_answered": ["기름 묻음·섞임"], "items": ["PCB"]}}
    )
    assert msg.startswith("기름 묻음·섞임은 확인했습니다.")


def test_evidence_request_groups_items_by_document():
    # B2: 서류별로 나누고, 용출 항목은 묶고, 성적서가 없을 때 할 일을 말한다
    labels = [f"{x} 용출 농도" for x in ("비소", "카드뮴", "납")] + ["수분함량"]
    msg = templates.request_evidence(
        {
            "documents": [
                {"evidence_type": "FACILITY_NOTIFICATION", "fact_labels": ["고시된 오니 발생시설"]},
                {"evidence_type": "TEST_REPORT", "fact_labels": labels},
            ]
        }
    )
    assert "시험성적서 — 용출시험 3종(비소·카드뮴·납), 수분함량" in msg
    assert " / " in msg and templates.TEST_LAB_HINT in msg
    assert "카드뮴 용출 농도" not in msg


def test_unsupported_says_how_to_continue():
    # B1: 판정 불가에서 부족한 항목과 이어 가는 방법을 말한다(막다른 길 금지)
    msg = templates.unsupported(
        {
            "failure_reason": "UNDETERMINABLE",
            "open_items": ["pH", "수분함량", "납 용출 농도", "구리 용출 농도"],
            "evidence_labels": ["기기 명판 사진 또는 절연유 분석 기록"],
            "needs_test_report": True,
        }
    )
    assert "정리해 드립니다" not in msg
    assert "pH, 수분함량, 납 용출 농도 외 1개" in msg
    assert "분석 기록을 준비해 올리면 이어서 판정합니다" in msg  # 받침에 맞는 조사
    assert templates.TEST_LAB_HINT in msg
    msg = templates.unsupported(
        {
            "failure_reason": "UNDETERMINABLE",
            "open_items": ["소재"],
            "unknown_items": ["소재"],
            "unknown_hint": "재질 표시를 보세요.",
        }
    )
    assert (
        "판정 보드에서 고치면 이어서 진행합니다" in msg
        and "소재 확인 방법: 재질 표시를 보세요." in msg
    )


def test_no_code_result_gives_reason_and_next_step():
    # B4·B5: 코드 없는 결론은 이유와, 확정하면 받을 안내를 확정 전에 보여 준다
    reason = templates.outcome_reason("아직 쓴다는 답만으로는 폐기물이 아니라고 확정하지 않습니다.")
    assert reason.endswith("않습니다.")
    assert (
        templates.outcome_reason("폐유가 남은 용기·물건")
        == "판단 근거가 된 경우: 폐유가 남은 용기·물건."
    )
    assert templates.outcome_reason(None) is None
    nxt = templates.no_code_next_step("REFER_AUTHORITY")
    assert nxt == "확정하면 다음 단계에서 '관할 기관 질의 안내'로 이어집니다."
    assert templates.no_code_next_step(None) == templates.NO_CODE_NEXT_STEP
    msg = templates.final_review(
        {
            "verdict": {"code": None, "outcome": "INTERPRETATION_NEEDED", "reason": reason},
            "next_step": nxt,
        }
    )
    assert msg.index(reason) < msg.index("확정해 주세요") < msg.index("관할 기관 질의 안내")


def test_code_result_sentence_and_no_status_code():
    v = {
        "code": "51-03-01",
        "name": "폐합성수지류(폐염화비닐수지류는 제외한다)",
        "category": "GENERAL",
    }
    msg = templates.final_review({"verdict": v, "unverified": True})
    assert msg.startswith("분류번호는 51-03-01(사업장일반폐기물)입니다. 명칭: 폐합성수지류(")
    assert "제외한다)로" not in msg  # A4: 법령 명칭 뒤에 조사를 붙이지 않는다
    assert "UNVERIFIED" not in msg  # A3: 영어 상태값을 사용자 문장에 쓰지 않는다
    assert templates.code_conclusion("02-01-99", None, "DESIGNATED") == (
        "분류번호는 02-01-99(지정폐기물)입니다."
    )


def test_no_parenthesized_particles_in_templates():
    # A7: '을(를)', '은(는)' 같은 괄호 조사를 쓰지 않는다
    src = Path(templates.__file__).read_text(encoding="utf-8")
    assert not re.search(r"(을\(를\)|은\(는\)|이\(가\)|\(으\)로)", src)


def test_user_help_has_no_dev_notes():
    # A2: 질문 도움말에 개발 기록·내부 이름을 쓰지 않는다
    facts = yaml.safe_load((KNOWLEDGE / "facts.yaml").read_text(encoding="utf-8"))
    pat = re.compile(r"20\d\d-\d\d-\d\d부터|이전에는|공통 정의|SLUDGE_STATE")
    for key, fd in facts.items():
        texts = [fd.get("question") or ""]
        texts += [h.get("text", "") for h in fd.get("how_to_check") or []]
        note = fd.get("note")
        texts.append(note.get("text", "") if isinstance(note, dict) else (note or ""))
        for t in texts:
            assert not pat.search(t), (key, t)


@pytest.mark.parametrize(
    ("title", "location", "expected"),
    [
        (
            "폐기물관리법 시행령 별표 1(지정폐기물의 종류)",
            "별표 1(지정폐기물의 종류)",
            "폐기물관리법 시행령 별표 1(지정폐기물의 종류)",
        ),
        (
            "폐기물관리법 시행령 별표 1(지정폐기물의 종류)",
            "별표 1 제2호가목",
            "폐기물관리법 시행령 별표 1(지정폐기물의 종류) 제2호가목",
        ),
        ("폐기물관리법", "제2조제1호", "폐기물관리법 제2조제1호"),
        # 별표 4와 별표 4의3은 다른 별표다
        ("시행규칙 별표 4의3(x) 표", "별표 4 제1호", "시행규칙 별표 4의3(x) 표 별표 4 제1호"),
    ],
)
def test_basis_ref_does_not_repeat_annex(title, location, expected):
    assert basis_ref(title, location) == expected


def test_built_basis_refs_have_no_repeated_annex():
    # A5: 빌드된 규칙의 근거 이름에 '별표 N(…) 별표 N'이 반복되지 않는다
    seen = 0
    for f in (REAL / "rules" / "tables").glob("*.yaml"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if "ref:" in line:
                seen += 1
                assert not re.search(r"(별표 \d+(?:의\d+)?)\([^)]*\) \1(?![의\d])", line), line
    assert seen > 0
