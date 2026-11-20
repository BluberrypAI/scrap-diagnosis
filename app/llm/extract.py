"""추출 AI: 사용자 말에서 의도와 사실 값 후보를 뽑는다(한 턴에 한 번 호출).

LLM은 제안만 한다. 돌려준 값은 app/interview/guard.py가 카탈로그·근거 문구로 검사한 뒤에만
사실로 기록되고, 판정은 규칙 엔진이 한다. 무엇을 물을지도 여기서 정하지 않는다.

입력에 넣는 것(고정 자료를 앞에 둔다, 프롬프트 캐시용)
- 받을 수 있는 사실과 값(카탈로그에서, 서류로만 받는 사실과 자동으로 채우는 사실은 뺀다)
- 지금 화면의 질문(선택지·묶음 항목), 최근 대화 몇 줄, 사용자 말(식별 정보를 가린 것)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.engine.flow import UNASKED, lookup
from app.engine.kb import KB
from app.interview import catalog as cat
from app.llm.client import LLMCall, LLMClient

INTENTS = ("answer", "question", "off_topic", "refuse_document", "unclear")

SYSTEM = """당신은 폐기물 분류 문진의 '말 이해' 담당입니다. 사업장 담당자가 쓴 말을 읽고 아래 JSON만 돌려줍니다.
판정·분류번호·다음 질문은 정하지 않습니다. 그 일은 규칙 엔진이 합니다.

할 일
1. intent: 말의 의도
   - answer: 질문에 답하거나 폐기물에 대한 사실을 말함
   - question: 문진에 관한 질문(왜 묻는지, 용어 뜻, 결과·기준·법 근거)
   - off_topic: 문진과 무관한 요청(업체 추천, 비용, 잡담 등)
   - refuse_document: 요청한 서류(성적서 등)가 없다고 함
   - unclear: 무슨 말인지 알 수 없음
   답과 질문이 섞이면 intent는 answer로 두고 질문 부분을 question_text에 넣습니다.
2. facts: 말에서 '직접 확인되는' 사실만 [{key, value, certainty, quote}]로 냅니다.
   - key와 value는 아래 '받을 수 있는 사실'의 키와 값만 씁니다. 목록에 없는 값은 만들지 않습니다.
   - quote: 그 값을 뒷받침하는 사용자 말의 원문 일부(그대로 복사, 고치지 않음).
   - certainty: 단정하면 stated, "아마", "~일걸요", "같아요", "대충"처럼 확신이 없으면 guess.
   - 말하지 않은 것은 추측해 채우지 않습니다. 특히 오염(기름·잔류물·약품)이 '없다'는 값은
     사용자가 분명히 없다고 말했을 때만 냅니다.
   - "모르겠어요"라고 하면 그 사실의 value를 "unknown"으로 냅니다(목록에 unknown이 있을 때만).
3. group_none_all: 지금 질문이 묶음 질문이고 사용자가 "다 해당 없어요"처럼 모든 항목을 부정하면 true.
4. question_text: 질문 부분의 원문(없으면 null).

형식은 스키마를 따르고, 값이 없으면 null 또는 빈 목록을 씁니다."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "facts", "group_none_all", "question_text"],
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["key", "value", "certainty", "quote"],
                "properties": {
                    "key": {"type": "string"},
                    # 선택지 값(문자열) 또는 숫자. 숫자도 문자열로 받아 검사기에서 바꾼다
                    "value": {"type": "string"},
                    "certainty": {"type": "string", "enum": ["stated", "guess"]},
                    "quote": {"type": "string"},
                },
            },
        },
        "group_none_all": {"type": "boolean"},
        "question_text": {"type": ["string", "null"]},
    },
}


@dataclass
class Proposal:
    intent: str
    facts: list[dict] = field(default_factory=list)
    group_none_all: bool = False
    question_text: str | None = None


def fact_menu(kb: KB, facts: dict) -> list[dict]:
    """받을 수 있는 사실: 아직 정해지지 않았거나 고칠 수 있는 사용자 답 사실.

    서류로만 받는 사실(source: document)은 뺀다. 자동으로 채워진 값은 넣지 않는다.
    """
    out = []
    catalog = kb.plan.catalog
    for path in cat.all_paths(catalog):
        s = cat.spec(catalog, path) or {}
        if s.get("source") == "document":
            continue
        item: dict[str, Any] = {"key": path, "label": s.get("label", path), "type": s["type"]}
        if s["type"] == "number":
            item["unit"] = s.get("unit")
        else:
            item["values"] = cat.value_map(s)
        item["asked"] = lookup(facts, path) != UNASKED
        out.append(item)
    return out


def current_question(question: dict | None, requested_documents: list[dict]) -> dict | None:
    if requested_documents:
        return {"kind": "document_request", "documents": requested_documents}
    if not question:
        return None
    q = {"key": question["key"], "text": question["text"], "unit": question["unit"]}
    if question["unit"] == "group":
        q["items"] = question["items"]
    else:
        q["options"] = [
            {"value": o["value"], "label": o["label"]}
            for o in question["options"]
            if o["kind"] == "value"
        ]
    return q


def build_user(
    kb: KB, facts: dict, question: dict | None, docs: list[dict], recent: list[dict], text: str
) -> str:
    payload = {
        "받을 수 있는 사실": fact_menu(kb, facts),
        "지금 질문": current_question(question, docs),
        "최근 대화": recent[-6:],
        "사용자 말": text,
    }
    return json.dumps(payload, ensure_ascii=False)


def parse(call: LLMCall) -> Proposal | None:
    if call.error or not isinstance(call.parsed, dict):
        return None
    p = call.parsed
    intent = p.get("intent") if p.get("intent") in INTENTS else "unclear"
    facts = [f for f in p.get("facts") or [] if isinstance(f, dict)]
    return Proposal(
        intent=intent,
        facts=facts,
        group_none_all=bool(p.get("group_none_all")),
        question_text=p.get("question_text") or None,
    )


def extract(llm: LLMClient, user: str, prompt_version: str) -> tuple[Proposal | None, LLMCall]:
    call = llm.complete_json(
        name="extract", system=SYSTEM, user=user, schema=SCHEMA, prompt_version=prompt_version
    )
    return parse(call), call
