"""질문 문장 다듬기: 다음 질문 계산기가 고른 질문을 쉬운 말 한두 문장으로 바꾼다(턴 응답 message).

- 무엇을 묻는지와 선택지는 바꾸지 않는다. 화면 카드의 ui.question.text는 고정 문장 그대로 둔다
- 검사: 길이, 원문·선택지에 없는 숫자(기준값·조항 번호)가 새로 생기면 버리고 고정 문장을 쓴다
- 같은 질문은 한 번만 부른다(프로세스 안 캐시). 실패하면 고정 문장
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.llm.client import LLMCall, LLMClient

SYSTEM = """당신은 폐기물 분류 문진의 질문 문장을 다듬는 담당입니다.
주어진 질문을 사업장 담당자가 바로 이해할 수 있는 존댓말 한두 문장으로 바꿉니다.
- 묻는 내용과 선택지를 바꾸지 않습니다. 선택지를 다시 나열하지 않아도 됩니다.
- 새로운 기준·수치·법 조항·예시 수치를 넣지 않습니다.
- 전문용어는 쉬운 말로 풀되 뜻을 바꾸지 않습니다.
- 120자 이내."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text"],
    "properties": {"text": {"type": "string"}},
}

_cache: dict[str, str | None] = {}


def _numbers(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", s or ""))


def payload(question: dict) -> dict:
    return {
        "질문": question.get("text"),
        "도움말": question.get("help"),
        "선택지": [o["label"] for o in question.get("options", []) if o.get("kind") == "value"],
        "묶음 항목": [i["label"] for i in question.get("items", [])],
    }


def check(text: str, source: dict) -> str | None:
    text = (text or "").strip()
    if not 5 <= len(text) <= 200:
        return None
    if _numbers(text) - _numbers(json.dumps(source, ensure_ascii=False)):
        return None  # 원문에 없는 숫자(기준값 등)를 지어냄
    return text


def phrase(
    llm: LLMClient, question: dict, prompt_version: str
) -> tuple[str | None, LLMCall | None]:
    """다듬은 문장(실패하면 None)과 호출 기록(캐시면 None)."""
    src = payload(question)
    key = hashlib.sha256(
        (prompt_version + json.dumps(src, ensure_ascii=False, sort_keys=True)).encode()
    ).hexdigest()
    if key in _cache:
        return _cache[key], None
    user = json.dumps(src, ensure_ascii=False)
    try:
        call = llm.complete_json(
            name="phrase", system=SYSTEM, user=user, schema=SCHEMA, prompt_version=prompt_version
        )
    except Exception:  # 다듬기 실패는 문진을 막지 않는다(고정 문장을 쓴다)
        return None, None
    text = (
        None
        if call.error or not isinstance(call.parsed, dict)
        else check(call.parsed.get("text"), src)
    )
    _cache[key] = text
    return text, call
