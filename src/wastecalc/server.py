"""폐기물 법적 지위 계산기 MCP 서버.

도구 결과는 두 가지를 함께 돌려준다.
- structuredContent: 에이전트·웹 화면이 읽는 JSON
- text: 엔진이 정해진 틀로 만든 안내문(LLM 없이도 같은 안내가 보이도록)
실행: python -m wastecalc.server   (stdio)
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from .engine import InputError, evaluate, parse_answers
from .kb import load_kb
from .render import render_text

mcp = FastMCP("wastecalc")
KB = load_kb()
SESSIONS: dict[str, dict[str, Any]] = {}


def _result(payload: dict, text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], structuredContent=payload)


def _error(msg: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=f"입력 오류: {msg}")],
                          structuredContent={"error": msg}, isError=True)


def _run(answers: dict, strict: bool, session_id: str | None = None) -> CallToolResult:
    try:
        r = evaluate(answers, strict=strict, kb=KB)
    except InputError as e:
        return _error(str(e))
    if session_id:
        r = {"session_id": session_id, **r}
    return _result(r, render_text(r))


@mcp.tool()
def list_facts() -> CallToolResult:
    """계산기가 받는 사실 목록과 허용 값. 자유 서술을 이 값으로 바꾼 뒤 사용자에게 확인받고 넣으세요."""
    facts = {
        fid: {k: f[k] for k in ("question", "type", "cost", "values", "unit") if k in f}
        for fid, f in KB.facts.items()
    }
    payload = {"facts": facts, "unknown_token": "UNKNOWN",
               "value_forms": ["값", "\"UNKNOWN\"", {"value": "값", "source": "USER|DOCUMENT|TEST"},
                               {"conflict": ["값1", "값2"], "source": "DOCUMENT"}],
               "rule_db_version": KB.version}
    return _result(payload, json.dumps(payload, ensure_ascii=False, indent=1))


@mcp.tool()
def start_assessment(answers: dict | None = None, strict: bool = True) -> CallToolResult:
    """판정을 시작한다. 아는 사실만 넣어도 된다(모르면 "UNKNOWN").
    결과: 상태(DETERMINED/NEED_INFO/NEED_TEST/NEED_EXPERT/OUT_OF_SCOPE), 단계별 결론과 근거 조문,
    모르는 항목을 가르는 기준과 확인 방법(resolution), 다음 질문.
    strict=True면 사람이 검토하지 않은 규칙으로 나온 결론은 잠정(NEED_EXPERT)으로 표시한다."""
    try:
        parse_answers(KB, answers or {})
    except InputError as e:
        return _error(str(e))
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = {"answers": dict(answers or {}), "strict": strict}
    return _run(SESSIONS[sid]["answers"], strict, sid)


@mcp.tool()
def answer_question(session_id: str, fact: str, value: Any) -> CallToolResult:
    """세션에 사실 하나를 답한다(이미 답한 사실이면 고친다). value는 값, "UNKNOWN", 또는
    {"value": 값, "source": "DOCUMENT"} / {"conflict": [값1, 값2]}."""
    s = SESSIONS.get(session_id)
    if s is None:
        return _error(f"없는 세션 {session_id!r}. start_assessment로 시작하세요.")
    trial = {**s["answers"], fact: value}
    try:
        parse_answers(KB, trial)
    except InputError as e:
        return _error(str(e))
    s["answers"] = trial
    return _run(trial, s["strict"], session_id)


@mcp.tool()
def evaluate_facts(answers: dict, strict: bool = True) -> CallToolResult:
    """세션 없이 한 번에 판정한다(같은 입력이면 항상 같은 결과)."""
    return _run(answers, strict)


@mcp.tool()
def get_rule(rule_id: str) -> CallToolResult:
    """규칙 한 행의 조건·근거 조문 원문·법령 판·검토 상태를 돌려준다. 에이전트 답변의 조문 재확인용."""
    rule = next((r for r in KB.rules if r.id == rule_id), None)
    if rule is None:
        return _error(f"없는 규칙 {rule_id!r}")
    src = KB.sources[rule.source]
    payload = {
        "id": rule.id, "stage": rule.stage, "concludes": rule.concludes,
        "when": [{"fact": c.fact, "op": c.op, "value": c.value} for c in rule.when],
        "complement_of": rule.complement_of,
        "source": {"id": rule.source, "title": src["title"], "version": src["version"],
                   "effective_on": src["effective_on"], "evidence": src["evidence"]},
        "location": rule.location, "quote": rule.quote, "review": rule.review,
        "supporting": rule.supporting,
    }
    return _result(payload, json.dumps(payload, ensure_ascii=False, indent=1))


@mcp.tool()
def allowed_recycling_types(code: str) -> CallToolResult:
    """별표 4 분류번호 하나의 재활용 가능 유형(시행규칙 별표 4의3)과 사전 분석·확인 필요 여부를 조회한다.
    금지·제한 판정은 폐기물 사실에 따라 달라지므로 전체 판정은 evaluate_facts를 쓰세요."""
    row = next((r for r in KB.annex43["rows"] if r["code"] == code), None)
    if row is None and code not in {c["id"] for c in KB.annex4["codes"]}:
        return _error(f"별표 4에 없는 번호 {code!r}")
    defs = KB.r_codes["codes"]
    cells = [] if row is None else [
        {"prohibited": c["prohibited"], "pre_analysis": c["pre_analysis"],
         "types": [{"r_code": rc, "definition": defs.get(rc)} for rc in c["r_codes"]]} for c in row["cells"]]
    payload = {"code": code, "listed": bool(cells), "cells": cells,
               "note": None if cells else KB.s5_rules["notes"]["not_listed"]["quote"],
               "source": KB.sources["RULE-A43"]["title"], "version": KB.sources["RULE-A43"]["version"]}
    return _result(payload, json.dumps(payload, ensure_ascii=False, indent=1))


@mcp.tool()
def r_code_definition(r_code: str) -> CallToolResult:
    """재활용 유형 코드(R-x-x)의 정의(시행규칙 별표 4의2 원문)."""
    d = KB.r_codes["codes"].get(r_code)
    if d is None:
        return _error(f"없는 재활용 유형 {r_code!r}")
    payload = {"r_code": r_code, "definition": d, "source": KB.sources["RULE-A42"]["title"],
               "version": KB.sources["RULE-A42"]["version"]}
    return _result(payload, json.dumps(payload, ensure_ascii=False, indent=1))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
