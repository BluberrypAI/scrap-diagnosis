"""질의응답 agent: 문진에 관한 질문(왜 묻는지, 용어, 기준·결과의 근거)에 자료를 찾아 답한다.

LLM이 매 단계 '도구를 쓸지, 답할지'를 고른다(어떤 자료를 몇 번 찾을지 스스로 정함).
코드가 지키는 것
- 도구는 읽기 전용(app/llm/tools.py). 판정·사실 기록은 바꾸지 않는다
- 도구 호출 상한(ASSIST_MAX_TOOL_CALLS, 기본 3). 넘으면 답만 하게 한다
- 출처 대조: 답변이 인용한 출처 id가 이번에 도구가 돌려준 결과에 있어야 한다. 없는 출처는 뺀다
- 문진과 무관한 요청은 답하지 않는다(추출 단계에서 먼저 걸러진다)
응답은 화면 계약의 assist 모양: {intent, text, sources[{id, type, ref, excerpt}], terms[], review}
"""

from __future__ import annotations

import json
from typing import Any

from app.engine.kb import KB
from app.llm.client import LLMCall, LLMClient
from app.llm.tools import Tools

TOOLS = ("search_law", "rule_basis", "lookup_term", "case_state")

SYSTEM = """당신은 폐기물 분류 문진을 돕는 설명 담당입니다. 사업장 담당자의 질문에 쉬운 말로 짧게 답합니다.
매 단계 JSON 하나로, 도구를 하나 쓰거나(action=tool) 답합니다(action=answer).

도구(모두 읽기 전용)
- rule_basis(arg): 질문·결과가 어느 규칙과 조문에서 나왔는지. arg는 current_question(지금 질문), result(지금 결과), 사실 키, 규칙 id 중 하나.
  "왜 ○○을 물어봐요?"처럼 특정 항목을 물으면 '사실 목록'에서 그 항목의 키를 찾아 arg로 넣습니다
- search_law(arg): 적재한 법령 조문을 검색어로 찾음
- lookup_term(arg): 용어의 쉬운 설명(용어집)과 질문 도움말
- case_state(arg=null): 지금까지의 답·질문·판정

규칙
- 답은 도구가 돌려준 자료에만 근거합니다. 자료에 없는 기준·수치·법 조항은 말하지 않습니다.
- source_ids에는 답에 쓴 자료의 id만 넣습니다(도구 결과의 id 그대로).
- 판정을 바꾸거나 정하지 않습니다. "결과가 바뀌나요?"에는 어떤 답이 무엇에 영향을 주는지만 설명합니다.
- 업체 추천·비용 등 문진과 무관한 요청에는 문진만 돕는다고 짧게 말합니다.
- 남은 도구 호출이 0이면 반드시 answer로 답합니다. 자료가 부족하면 모른다고 말하고 관할 기관 확인을 권합니다.
- 답은 3~5문장, 존댓말, 전문용어는 풀어서."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "tool", "arg", "answer", "source_ids", "terms"],
    "properties": {
        "action": {"type": "string", "enum": ["tool", "answer"]},
        "tool": {"type": ["string", "null"], "enum": [*TOOLS, None]},
        "arg": {"type": ["string", "null"]},
        "answer": {"type": ["string", "null"]},
        "source_ids": {"type": "array", "items": {"type": "string"}},
        "terms": {"type": "array", "items": {"type": "string"}},
    },
}


def fact_list(kb: KB) -> dict[str, str]:
    """사실 키 → 이름. agent가 rule_basis에 넣을 키를 고르는 데 쓴다."""
    out = {}
    for fid, f in kb.plan.catalog.items():
        if f["type"] == "object":
            out |= {f"{fid}.{k}": v for k, v in f["fields"].items()}
        else:
            out[fid] = f["label"]
    return out


def run_agent(
    llm: LLMClient,
    kb: KB,
    *,
    question: str,
    state: dict,
    max_tool_calls: int,
    prompt_version: str,
) -> tuple[dict | None, list[LLMCall], list[dict]]:
    """(assist 또는 None, 호출 기록, 도구 사용 기록)."""
    tools = Tools(kb, state)
    seen: dict[str, dict] = {}  # 출처 id → 결과
    steps: list[dict] = []
    calls: list[LLMCall] = []
    for _ in range(max_tool_calls + 1):
        remaining = max_tool_calls - sum(1 for s in steps if s["tool"])
        user = json.dumps(
            {
                "질문": question,
                "지금 상태 요약": {k: state.get(k) for k in ("question", "outcome", "code")},
                "사실 목록": fact_list(kb),
                "찾은 자료": steps,
                "남은 도구 호출": remaining,
            },
            ensure_ascii=False,
        )
        call = llm.complete_json(
            name="assist", system=SYSTEM, user=user, schema=SCHEMA, prompt_version=prompt_version
        )
        calls.append(call)
        p = call.parsed if not call.error and isinstance(call.parsed, dict) else None
        if p is None:
            return None, calls, steps
        if p.get("action") == "tool" and p.get("tool") in TOOLS and remaining > 0:
            results = tools.run(p["tool"], p.get("arg"))
            for r in results:
                for item in r.get("basis") or [r]:  # 규칙 결과는 안쪽 근거 조문이 출처다
                    if item.get("id"):
                        seen[item["id"]] = item
            steps.append({"tool": p["tool"], "arg": p.get("arg"), "results": results})
            continue
        text = (p.get("answer") or "").strip()
        if not text:
            return None, calls, steps
        return (
            build_assist(text, p.get("source_ids") or [], p.get("terms") or [], seen),
            calls,
            steps,
        )
    return None, calls, steps


def build_assist(text: str, source_ids: list[str], terms: list[str], seen: dict[str, dict]) -> dict:
    """출처 대조: 이번 도구 결과에 있는 id만 출처로 남긴다."""
    sources = []
    for sid in dict.fromkeys(source_ids):
        r = seen.get(sid)
        if r is None or r["type"] == "CASE":
            continue
        if r["type"] == "TERM":
            if r.get("basis") and r.get("ref"):
                sources.append(
                    {"id": r["basis"], "type": "LAW", "ref": r["ref"], "excerpt": r.get("excerpt")}
                )
            continue
        sources.append(
            {"id": r["id"], "type": r["type"], "ref": r.get("ref"), "excerpt": r.get("excerpt")}
        )
    term_rows = []
    by_term = {r["term"]: r for r in seen.values() if r["type"] == "TERM"}
    for t in dict.fromkeys(terms):
        r = by_term.get(t)
        if r:
            term_rows.append({"term": r["term"], "plain": r["plain"], "example": None})
    return {
        "intent": "question",
        "text": text,
        "sources": sources,
        "terms": term_rows,
        "review": "UNVERIFIED",
    }
