"""문진 세션(FakeLLM): 추출 → 엔진 → 응답 guard → 응답 스키마 → Trace."""

from datetime import date
from pathlib import Path

import pytest
import yaml

from app.agent.golden import normalize_extract, run_case
from app.agent.llm_client import FakeLLMClient
from app.agent.orchestrator import DiagnosisSession, QuickReply
from tests.conftest import DATA, REAL

AS_OF = date(2026, 11, 8)
GOLDEN = Path(__file__).resolve().parents[1] / "data" / "golden"


def session(kb, extract=None, respond=None):
    ex = FakeLLMClient(by_name={"extract": [normalize_extract(e) for e in extract or []]})
    rs = FakeLLMClient(by_name={"respond": respond}) if respond is not None else None
    return DiagnosisSession(kb, extractor_llm=ex, responder_llm=rs, case_id="c1", as_of=AS_OF)


def test_response_schema_contract(kb):
    s = session(kb, [{"facts": [{"key": "material", "value": "PP", "quote": "PP"}]}])
    r = s.handle(text="PP 폐기물이에요").model_dump()
    assert set(r) >= {
        "case_id",
        "session_id",
        "turn_id",
        "branch",
        "message",
        "verdict",
        "ui",
        "case_status",
    }
    assert set(r["verdict"]) >= {
        "status",
        "waste_code",
        "waste_name",
        "category",
        "candidates",
        "conditions",
        "rationale",
        "failure_reason",
    }
    assert set(r["ui"]) >= {"can_confirm", "suggested_replies", "requested_documents"}
    assert r["branch"] == "ASK_FACT" and r["verdict"]["status"] == "IN_PROGRESS"
    assert r["case_status"] == "DIAGNOSING"
    assert r["ui"]["suggested_replies"]  # 버튼은 코드가 만든다


def test_quick_reply_group_and_trace(kb):
    s = session(kb)
    s.seed({"material": "PP", "form": "FILM"})
    first = s.handle()
    assert first.ui.question["key"] == "contamination_screen"
    nxt = s.handle(quick_reply=QuickReply(key="contamination_screen", kind="none_all"))
    assert nxt.ui.question["key"] == "oil_content_pct"
    t = s.traces[-1]
    assert t.quick_reply["kind"] == "none_all"
    assert {f["key"] for f in t.appended_facts} == {
        "pcb_related",
        "hazardous_residue",
        "toxic_chemical",
    }
    assert t.table_version == "2026.11.0" and t.branch == "ASK_FACT"
    assert t.score_breakdown  # 질문 선택 근거
    assert s.state.questions_asked == 2


def test_final_review_confirmable_with_rationale(kb):
    s = session(kb)
    s.seed(
        {
            "material": "PP",
            "form": "FILM",
            "pcb_related": False,
            "hazardous_residue": False,
            "toxic_chemical": False,
        }
    )
    r = s.add_evidence({"oil_content_pct": 2.0}, document_id="doc-1")
    assert r.branch == "FINAL_REVIEW" and r.ui.can_confirm
    assert r.verdict.status == "CONFIRMABLE" and r.verdict.waste_code == "SAMPLE-A"
    assert r.verdict.rationale and r.verdict.rationale[0].id == "B1"
    oil = next(c for c in r.verdict.conditions if c.fact == "oil_content_pct")
    assert oil.satisfied is True and oil.evidence == "TEST_REPORT"


def test_bad_llm_response_falls_back_to_template(kb):
    bad = {"message": "SAMPLE-B일 겁니다. 맞죠? 확실하죠?", "cited_basis_ids": []}
    s = session(kb, respond=[bad, bad])
    s.seed(
        {
            "material": "PP",
            "form": "FILM",
            "pcb_related": False,
            "hazardous_residue": False,
            "toxic_chemical": False,
        }
    )
    r = s.handle()
    assert "SAMPLE-B" not in r.message
    t = s.traces[-1]
    assert t.responder["used_template"] and any("SAMPLE-B" in p for p in t.responder["problems"])
    assert len([c for c in t.llm_calls if c.name == "respond"]) == 2  # 1회 재시도


def test_good_llm_response_is_used(kb):
    good = {"message": "기름(유분) 함량이 얼마인지 알려 주시겠어요?", "cited_basis_ids": []}
    s = session(kb, respond=[good])
    s.seed(
        {
            "material": "PP",
            "form": "FILM",
            "pcb_related": False,
            "hazardous_residue": False,
            "toxic_chemical": False,
        }
    )
    r = s.handle()
    assert r.message == good["message"] and not s.traces[-1].responder["used_template"]


def test_extraction_retry_on_rejection(kb):
    bad = {"facts": [{"key": "material", "value": "PP", "quote": "폴리프로필렌"}]}
    good = {"facts": [{"key": "material", "value": "PP", "quote": "PP"}]}
    s = session(kb, [bad, good])
    s.handle(text="PP예요")
    t = s.traces[-1]
    assert t.extraction["attempts"] == 2 and t.appended_facts[0]["value"] == "PP"


def test_no_llm_accepts_exact_option_labels(kb):
    s = DiagnosisSession(kb, case_id="c", as_of=AS_OF)
    s.seed({"material": "PP", "form": "FILM"})
    s.handle()
    r = s.handle(text="모두 해당 없음")
    assert r.ui.question["key"] == "oil_content_pct"


def _golden_cases():
    out = []
    for p in sorted(GOLDEN.glob("*.yaml")):
        out += yaml.safe_load(p.read_text(encoding="utf-8"))
    return out


@pytest.fixture(scope="module")
def kbs(kb, real_kb):
    return {"sample": kb, "real": real_kb}


@pytest.mark.parametrize("case", _golden_cases(), ids=lambda c: c["id"])
def test_golden_mock_extractor(case, kbs):
    res = run_case(case, kbs[case.get("kb", "sample")], mock_extractor=True)
    bad = [(t.turn, t.mismatches) for t in res.turns if not t.ok]
    assert not bad, bad


def test_paths_exist():
    assert DATA.exists() and REAL.exists()
