"""AI 전송 정책: 가리기·fail-closed·문서 차단·Trace 최소화 (CORP-008, OPS-010, OPS-003)."""

import json
from datetime import date

import pytest

from app.agent import redact as R
from app.agent.extractor import extract
from app.agent.golden import normalize_extract
from app.agent.llm_client import FakeLLMClient
from app.agent.orchestrator import DiagnosisSession
from app.config import Settings

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


# ---- 추출기·세션 연동 ---------------------------------------------------------


def _fake():
    return FakeLLMClient(default=lambda n, s, u: normalize_extract({}))


def _run(kb, text, llm, settings=None, source="user", recent=()):
    return extract(
        llm,
        kb,
        text,
        effective={},
        last_question=None,
        recent=list(recent),
        message_id="m1",
        prompt_version="t",
        source=source,
        settings=settings or Settings(_env_file=None),
    )


def test_llm_payload_has_no_identifiers(kb):
    llm = _fake()
    text = (
        "PP 폐기물이고 담당 010-1234-5678, 사업자 123-45-67890, kim@a.com, "
        "서울시 강남구 테헤란로 152 수분 5% 미만 51-03-01"
    )
    recent = [{"role": "user", "text": "전화는 02-345-6789"}]
    res, calls = _run(kb, text, llm, recent=recent)
    assert res.llm_blocked is None
    seen = llm.calls[0].user
    for raw in ("010-1234-5678", "123-45-67890", "kim@a.com", "테헤란로 152", "02-345-6789"):
        assert raw not in seen
    for keep in ("[전화번호]", "[사업자번호]", "[이메일]", "[주소]", "51-03-01", "5% 미만"):
        assert keep in seen
    # Trace용 호출 기록에도 원문이 없다
    dumped = json.dumps([c.model_dump() for c in calls], ensure_ascii=False)
    for raw in ("010-1234-5678", "123-45-67890", "kim@a.com", "테헤란로 152"):
        assert raw not in dumped
    assert calls[0].user_sha256 and calls[0].user_len


def test_guard_checks_masked_text_and_keeps_masked_quote(kb):
    text = "PP입니다 연락처 010-1234-5678"
    llm = FakeLLMClient(
        default=lambda n, s, u: normalize_extract(
            {"facts": [{"key": "material", "value": "PP", "quote": "PP입니다 연락처 [전화번호]"}]}
        )
    )
    res, _ = _run(kb, text, llm)
    assert not res.rejected
    f = [x for x in res.facts if x.key == "material"][0]
    assert "[전화번호]" in f.quote and "010" not in f.quote


def test_fail_closed_blocks_llm(kb, monkeypatch):
    monkeypatch.setattr(R, "_PATTERNS", [])
    llm = _fake()
    res, calls = _run(kb, "PP예요 010-1234-5678", llm)
    assert res.llm_blocked and "redaction_failed" in res.llm_blocked
    assert llm.calls == [] and calls == []


def test_session_blocked_turn_goes_on_without_llm(kb, monkeypatch):
    monkeypatch.setattr(R, "_PATTERNS", [])
    ex = _fake()
    rs = FakeLLMClient(default=lambda n, s, u: {"message": "x", "cited_basis_ids": []})
    s = DiagnosisSession(kb, extractor_llm=ex, responder_llm=rs, case_id="c1", as_of=AS_OF)
    r = s.handle(text="PP예요 010-1234-5678")
    assert r.message
    t = s.traces[-1]
    assert t.extraction["llm_blocked"].startswith("redaction_failed")
    assert ex.calls == []
    assert t.responder["used_template"] is True


def test_document_gate(kb):
    llm = _fake()
    res, calls = _run(kb, "서류 원문 PP", llm, source="document")
    assert res.llm_blocked == "document_llm_not_allowed"
    assert llm.calls == []
    cfg = Settings(_env_file=None, allow_document_llm=True)
    res, _ = _run(kb, "서류 원문 PP", llm, cfg, "document")
    assert res.llm_blocked is None and len(llm.calls) == 1


def test_trace_store_prompts_false_keeps_only_hashes(kb):
    llm = _fake()
    cfg = Settings(_env_file=None, trace_store_prompts=False)
    _, calls = _run(kb, "PP예요 010-1234-5678", llm, cfg)
    c = calls[0]
    assert c.user == "" and c.raw is None and c.parsed is None
    assert c.user_sha256 and c.user_len and c.raw_sha256


def test_session_trace_has_no_raw_identifiers(kb):
    ex = FakeLLMClient(by_name={"extract": [normalize_extract({})]})
    rs = FakeLLMClient(default=lambda n, s, u: {"message": "네", "cited_basis_ids": []})
    s = DiagnosisSession(kb, extractor_llm=ex, responder_llm=rs, case_id="c1", as_of=AS_OF)
    s.handle(text="PP예요 담당 010-1234-5678 사업자 123-45-67890")
    dumped = json.dumps(
        [[x.model_dump() for x in t.llm_calls] for t in s.traces], ensure_ascii=False
    )
    assert "010-1234-5678" not in dumped and "123-45-67890" not in dumped
    assert "[전화번호]" in dumped
