"""골든 평가 세트 실행기 (docs/engine/algorithm.md 9절).

골든 형식(YAML, 파일당 목록 또는 단일 사례)
    - id: G-001
      kb: sample | real
      description: ...
      max_questions: 12
      setup: {facts: {...}, evidenced: {...}}   # 기업 프로필·이미 확인된 값
      turns:
        - user: "내 폐기물 코드는 SAMPLE-A야"
          extract: {user_code_claim: SAMPLE-A}  # --mock-extractor에서 LLM 대신 쓸 추출 결과
          expect: {branch: ASK_FACT, ask_fact: oil_content_pct, can_confirm: false}
        - quick_reply: {key: contamination_screen, kind: none_all}
        - evidence: {oil_content_pct: 2.0}     # 문서 업로드로 확인된 값
          expect: {branch: FINAL_REVIEW, code: SAMPLE-A}
expect 키: branch, ask_fact, can_confirm, code, outcome(코드 없는 결론), documents(증빙 종류 목록),
failure_reason
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel

from app.agent.llm_client import FakeLLMClient, LLMClient
from app.agent.orchestrator import DiagnosisSession, QuickReply
from app.domain.facts import FactStatus
from app.domain.verdict import TurnResponse
from app.rules.model import KnowledgeBase

FACT_DEFAULTS = {
    "value_text": None,
    "value_number": None,
    "value_bool": None,
    "range": None,
    "status": "CLAIMED",
    "note": None,
    "certainty": "sure",
}


def normalize_extract(e: dict | None) -> dict:
    """골든에 적은 간단한 추출 결과를 스키마 모양으로 채운다."""
    e = dict(e or {})
    facts = []
    for f in e.get("facts") or []:
        item = {**FACT_DEFAULTS, **f}
        v = item.pop("value", None)
        if v is not None:
            if isinstance(v, bool):
                item["value_bool"] = v
            elif isinstance(v, int | float):
                item["value_number"] = v
            elif isinstance(v, dict):
                item["range"] = {"lo": None, "lo_inc": None, "hi": None, "hi_inc": None, **v}
            else:
                item["value_text"] = str(v)
        facts.append(item)
    ga = e.get("group_answer")
    if ga and "quote" not in ga:
        ga = {**ga, "quote": ""}
    if ga and "certainty" not in ga:
        ga = {**ga, "certainty": "sure"}
    return {
        "facts": facts,
        "group_answer": ga,
        "user_code_claim": e.get("user_code_claim"),
        "user_question": e.get("user_question"),
        "question_kind": e.get("question_kind"),
        "about": e.get("about") or [],
        "evidence_refused": bool(e.get("evidence_refused", False)),
    }


class TurnCheck(BaseModel):
    case_id: str
    turn: int
    input: str
    expect: dict
    got: dict
    ok: bool
    mismatches: list[str]
    rejected: int = 0
    extracted: int = 0
    template: bool = False


class CaseResult(BaseModel):
    case_id: str
    kb: str
    turns: list[TurnCheck]
    final_branch: str
    final_code: str | None
    questions_asked: int
    final_outcome: str | None = None

    @property
    def ok(self) -> bool:
        return all(t.ok for t in self.turns)


def summarize(resp: TurnResponse) -> dict:
    return {
        "branch": resp.branch,
        "ask_fact": (resp.ui.question or {}).get("key"),
        "can_confirm": resp.ui.can_confirm,
        "code": resp.verdict.waste_code,
        "outcome": resp.verdict.outcome,
        "documents": [d["evidence_type"] for d in resp.ui.requested_documents],
        "failure_reason": resp.verdict.failure_reason,
        "message": resp.message,
    }


def check(expect: dict, got: dict) -> list[str]:
    out = []
    for k, v in expect.items():
        g = got.get(k)
        if k == "documents":
            if sorted(v) != sorted(g or []):
                out.append(f"documents {g} != {v}")
        elif g != v:
            out.append(f"{k} {g!r} != {v!r}")
    return out


def run_case(
    case: dict,
    kb: KnowledgeBase,
    *,
    mock_extractor: bool,
    extractor_llm: LLMClient | None = None,
    responder_llm: LLMClient | None = None,
    as_of: date = date(2026, 11, 8),
) -> CaseResult:
    fake = None
    if mock_extractor:
        fake = FakeLLMClient()
        extractor_llm = fake
    s = DiagnosisSession(
        kb,
        extractor_llm=extractor_llm,
        responder_llm=responder_llm,
        case_id=case["id"],
        as_of=as_of,
        max_questions=int(case.get("max_questions", 12)),
    )
    setup = case.get("setup") or {}
    s.seed(setup.get("facts") or {})
    s.seed(setup.get("evidenced") or {}, source_type="DOCUMENT", status=FactStatus.EVIDENCED)
    checks: list[TurnCheck] = []
    resp: TurnResponse | None = None
    for i, t in enumerate(case.get("turns") or [], start=1):
        label = ""
        if "user" in t:
            label = t["user"]
            if fake is not None:
                fake.push("extract", normalize_extract(t.get("extract")))
            resp = s.handle(text=t["user"])
        elif "quick_reply" in t:
            qr = QuickReply(**t["quick_reply"])
            label = f"[버튼] {qr.key}={qr.kind}:{qr.value}"
            resp = s.handle(quick_reply=qr)
        elif "evidence" in t:
            label = f"[문서] {t['evidence']}"
            resp = s.add_evidence(t["evidence"], document_id=f"doc-{i}")
        else:
            label = "[시작]"
            resp = s.handle()
        got = summarize(resp)
        exp = t.get("expect") or {}
        mism = check(exp, got)
        trace = s.traces[-1]
        ex = trace.extraction or {}
        checks.append(
            TurnCheck(
                case_id=case["id"],
                turn=i,
                input=label,
                expect=exp,
                got=got,
                ok=not mism,
                mismatches=mism,
                rejected=len(ex.get("rejected") or []),
                extracted=len(ex.get("facts") or []),
                template=trace.responder.get("used_template", False),
            )
        )
    assert resp is not None
    return CaseResult(
        case_id=case["id"],
        kb=case.get("kb", "sample"),
        turns=checks,
        final_branch=resp.branch,
        final_code=resp.verdict.waste_code,
        final_outcome=resp.verdict.outcome,
        questions_asked=s.state.questions_asked,
    )


def metrics(results: list[CaseResult]) -> dict[str, Any]:
    turns = [t for r in results for t in r.turns if t.expect]

    def acc(key: str, pred=lambda t: True) -> tuple[int, int]:
        sel = [t for t in turns if key in t.expect and pred(t)]
        return sum(1 for t in sel if t.got.get(key) == t.expect[key]), len(sel)

    hold = [t for t in turns if t.expect.get("branch") in ("REQUEST_EVIDENCE", "UNSUPPORTED")]
    finals = [t for t in turns if "code" in t.expect and t.expect["code"]]
    final_q = [r.questions_asked for r in results if r.final_branch == "FINAL_REVIEW"]
    all_turns = [t for r in results for t in r.turns]
    extracted = sum(t.extracted for t in all_turns)
    rejected = sum(t.rejected for t in all_turns)
    b_ok, b_n = acc("branch")
    a_ok, a_n = acc("ask_fact")
    return {
        "cases": len(results),
        "cases_passed": sum(1 for r in results if r.ok),
        "branch_accuracy": f"{b_ok}/{b_n}",
        "ask_fact_accuracy": f"{a_ok}/{a_n}",
        "final_code_accuracy": f"{sum(1 for t in finals if t.got['code'] == t.expect['code'])}"
        f"/{len(finals)}",
        "hold_accuracy": f"{sum(1 for t in hold if t.got['branch'] == t.expect['branch'])}"
        f"/{len(hold)}",
        "avg_questions_to_final": round(sum(final_q) / len(final_q), 2) if final_q else None,
        "guard_rejection_rate": round(rejected / (rejected + extracted), 3)
        if (rejected + extracted)
        else 0.0,
        "template_fallback_turns": sum(1 for t in all_turns if t.template),
    }
