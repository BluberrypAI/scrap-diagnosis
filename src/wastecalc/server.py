"""폐기물 법적 지위 계산기 MCP 서버.

도구 결과는 두 가지를 함께 돌려준다.
- structuredContent: 에이전트·웹 화면이 읽는 JSON
- text: 엔진이 정해진 틀로 만든 안내문(LLM 없이도 같은 안내가 보이도록)
대화 도구는 기본으로 간략 응답(다음 질문에 필요한 것만)을 돌려준다. 근거 원문·경우의 수 전체는 explain으로 받는다.
실행: python -m wastecalc.server   (stdio)
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from .compact import compact, render_compact
from .engine import InputError, evaluate, parse_answers
from .kb import load_kb
from .render import render_text
from .session_state import revise_answers

mcp = FastMCP("wastecalc")
KB = load_kb()
SESSIONS: dict[str, dict[str, Any]] = {}


def _result(payload: dict, text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], structuredContent=payload)


def _error(msg: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=f"입력 오류: {msg}")],
                          structuredContent={"error": msg}, isError=True)


def _run(answers: dict, strict: bool, session_id: str | None = None, as_of: str | None = None,
         detail: bool = False, include_reporting: bool = False) -> CallToolResult:
    try:
        r = evaluate(answers, strict=strict, kb=KB, as_of=as_of, include_reporting=include_reporting)
    except InputError as e:
        return _error(str(e))
    if detail:
        payload, text = r, render_text(r, glossary=KB.glossary)
    else:
        payload = compact(r, KB.at(r["as_of"]), answers)
        text = render_compact(payload)
    if session_id:
        payload = {"session_id": session_id, **payload}
        text = f"세션 {session_id}\n" + text
    return _result(payload, text)


@mcp.tool()
def list_facts() -> CallToolResult:
    """계산기가 받는 사실 목록과 허용 값. 자유 서술을 이 값으로 바꾼 뒤 사용자에게 확인받고 넣으세요."""
    facts = {
        fid: {k: f[k] for k in ("label", "question", "type", "cost", "values", "unit") if k in f
              and not (k == "values" and f.get("values_from"))}  # 분류번호 목록은 질문의 보기로 받는다
        for fid, f in KB.facts.items() if not f.get("derived_from")
    }
    payload = {"facts": facts, "unknown_token": "UNKNOWN",
               "value_forms": ["값", "\"UNKNOWN\"", {"value": "값", "source": "USER|DOCUMENT|TEST"},
                               {"conflict": ["값1", "값2"], "source": "DOCUMENT"}],
               "rule_db_version": KB.version}
    return _result(payload, json.dumps(payload, ensure_ascii=False, indent=1))


@mcp.tool()
def start_assessment(answers: dict | None = None, strict: bool = True, as_of: str | None = None,
                     detail: bool = False, include_reporting: bool = False) -> CallToolResult:
    """판정을 시작한다. 처음 설명에서 알 수 있는 사실을 모두 넣는다(모르면 "UNKNOWN").
    결과(간략): 상태, 지금까지 결론, 다음 질문(보기·왜 묻는지), 그 밖에 아직 답하지 않은 질문, 모름 항목의 확인 방법.
    근거 원문까지 필요하면 detail=true 또는 explain.
    strict=True면 사람이 검토하지 않은 규칙으로 나온 결론은 잠정(NEED_EXPERT)으로 표시한다.
    as_of(YYYY-MM-DD, 기본 오늘)는 판정 기준일 — 그날 시행 중인 법령의 규칙만 쓴다."""
    try:
        parse_answers(KB, answers or {})
        as_of = KB.at(as_of).as_of
    except (InputError, ValueError) as e:
        return _error(str(e))
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = {"answers": dict(answers or {}), "strict": strict, "as_of": as_of, "include_reporting": include_reporting}
    return _run(SESSIONS[sid]["answers"], strict, sid, as_of, detail, include_reporting)


@mcp.tool()
def answer_question(session_id: str, fact: str | None = None, value: Any = None,
                    answers: dict | None = None, detail: bool = False) -> CallToolResult:
    """세션에 답한다(이미 답한 사실이면 고친다). 하나는 fact+value, 여러 개는 answers={사실: 값}로 한 번에.
    value는 값, "UNKNOWN", 또는 {"value": 값, "source": "DOCUMENT"} / {"conflict": [값1, 값2]}."""
    s = SESSIONS.get(session_id)
    if s is None:
        return _error(f"없는 세션 {session_id!r}. start_assessment로 시작하세요.")
    new = dict(answers or {})
    if fact is not None:
        new[fact] = value
    if not new:
        return _error("fact+value 또는 answers가 필요합니다.")
    try:
        trial, invalidated = revise_answers(KB, s["answers"], new)
    except InputError as e:
        return _error(str(e))
    s["answers"] = trial
    reviews = {**s.get("needs_review", {}), **invalidated}
    s["needs_review"] = {f: v for f, v in reviews.items() if f not in new}
    out = _run(trial, s["strict"], session_id, s.get("as_of"), detail, s.get("include_reporting", False))
    out.structuredContent["needs_review"] = s["needs_review"]
    return out


@mcp.tool()
def evaluate_facts(answers: dict, strict: bool = True, as_of: str | None = None,
                   detail: bool = False, include_reporting: bool = False) -> CallToolResult:
    """세션 없이 한 번에 판정한다(같은 입력·같은 기준일이면 항상 같은 결과). as_of는 YYYY-MM-DD, 기본 오늘.
    기본은 간략 응답, detail=true면 근거 원문까지 전체."""
    return _run(answers, strict, None, as_of, detail, include_reporting)


@mcp.tool()
def explain(session_id: str | None = None, answers: dict | None = None, strict: bool = True,
            as_of: str | None = None, include_reporting: bool = False) -> CallToolResult:
    """전체 결과: 단계별 이유, 근거 원문, 모든 경우의 수, 용어 풀이. 결론이 났을 때나 사용자가 '왜?'라고 물을 때 쓴다."""
    if session_id:
        s = SESSIONS.get(session_id)
        if s is None:
            return _error(f"없는 세션 {session_id!r}")
        return _run(s["answers"], s["strict"], session_id, s.get("as_of"), detail=True, include_reporting=s.get("include_reporting", False))
    return _run(answers or {}, strict, None, as_of, detail=True, include_reporting=include_reporting)


@mcp.tool()
def assessment_record(session_id: str | None = None, answers: dict | None = None, strict: bool = True,
                      as_of: str | None = None, include_reporting: bool = False) -> CallToolResult:
    """판정 기록: 이후 단계(시설 추천·수거 등)가 읽는 고정 형식. 항목별 상태·값·근거·쓰인 사실의 출처·신뢰 수준,
    남은 확인 사항, 기준일·규칙 버전·record_hash. status가 DETERMINED이고 trust.level이 기준 이상인 항목만 자동으로 쓴다."""
    from .record import build_record

    if session_id:
        s = SESSIONS.get(session_id)
        if s is None:
            return _error(f"없는 세션 {session_id!r}")
        answers, strict, as_of = s["answers"], s["strict"], s.get("as_of")
        include_reporting = s.get("include_reporting", False)
    try:
        r = evaluate(answers or {}, strict=strict, kb=KB, as_of=as_of, include_reporting=include_reporting)
    except InputError as e:
        return _error(str(e))
    rec = build_record(KB.at(r["as_of"]), answers or {}, r)
    return _result(rec, json.dumps(rec, ensure_ascii=False, indent=1))


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
