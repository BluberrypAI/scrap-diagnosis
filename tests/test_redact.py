"""기존 엔진 참조(복원): 가리기 단위 테스트만 남겼다(세션·추출기 테스트는 v2에서 새로 쓴다).
AI 전송 정책: 가리기·fail-closed·문서 차단·Trace 최소화 (CORP-008, OPS-010, OPS-003)."""

from datetime import date

import pytest

from app.llm import redact as R

AS_OF = date(2026, 11, 8)
RAW = [
    "123-45-67890",
    "010-1234-5678",
    "02-345-6789",
    "+82 10 1234 5678",
    "kim.cs@example.co.kr",
    "테헤란로 152",
    "880101-1234567",
    "110111-0123456",
]


@pytest.mark.parametrize(
    "src,token",
    [
        ("사업자번호 123-45-67890입니다", "[사업자번호]"),
        ("법인번호 110111-0123456", "[법인번호]"),
        ("주민번호 880101-1234567", "[주민번호]"),
        ("연락처 010-1234-5678", "[전화번호]"),
        ("01012345678로 주세요", "[전화번호]"),
        ("대표번호 02-345-6789", "[전화번호]"),
        ("031-123-4567", "[전화번호]"),
        ("+82 10-1234-5678", "[전화번호]"),
        ("메일은 kim.cs@example.co.kr", "[이메일]"),
        ("서울시 강남구 테헤란로 152", "[주소]"),
        ("경기도 안산시 단원구 공단로12번길 34 3동 201호", "[주소]"),
        ("역삼동 123-45", "[주소]"),
        ("사업자등록번호: 1234567890", "[사업자번호]"),
    ],
)
def test_masks_identifiers(src, token):
    out = R.redact(src)
    assert token in out.text
    assert not R.find_identifiers(out.text)
    for raw in RAW:
        assert raw not in out.text


@pytest.mark.parametrize(
    "src",
    [
        "분류번호 51-03-01이에요",
        "09-01-00이요",
        "02-03-01 코드",
        "PP로 5개 버려요",
        "용기로 5% 들어 있어요",
        "수분 5% 미만, pH 2.5, 납 0.3 mg/L, 10 kg/일",
        "2026-11-08에 발생, 12.5톤",
        "SAMPLE-A1 시료",
        "원료 5 mg/L 검출",
    ],
)
def test_waste_facts_survive(src):
    assert R.redact(src).text == src


def test_mixed_sentence_keeps_codes_and_measurements():
    src = "010-9999-8888 담당, 폐유 51-03-01 수분 5% 미만 납 0.3 mg/L 2026-11-08 123-45-67890"
    out = R.redact(src).text
    for keep in ("51-03-01", "5% 미만", "0.3 mg/L", "2026-11-08"):
        assert keep in out
    assert "010-9999-8888" not in out and "123-45-67890" not in out


def test_fail_closed_on_error(monkeypatch):
    class Boom:
        def subn(self, *a):
            raise ValueError("x")

    monkeypatch.setattr(R, "_PATTERNS", [("[x]", Boom())])
    with pytest.raises(R.RedactionError):
        R.redact("아무 문장")


def test_fail_closed_on_residual(monkeypatch):
    monkeypatch.setattr(R, "_PATTERNS", [])  # 가리기가 아무것도 못 하는 상황
    with pytest.raises(R.RedactionError):
        R.redact("연락처 010-1234-5678")
