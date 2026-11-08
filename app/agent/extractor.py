"""LLM 사실 추출 (md 9.1). LLM은 사실을 '제안'만 한다. 검증은 guard.py가 한다.

출력은 JSON Schema(strict)로 강제한다. 판정(폐기물 여부·지정 여부·분류번호 결정)은 하지 않는다.
"""

from __future__ import annotations

import json
from typing import Any

from app.agent.guard import ExtractionResult, validate_extraction
from app.agent.llm_client import LLMCall, LLMClient
from app.domain.facts import Fact
from app.rules.model import FactDef, KnowledgeBase
from app.rules.selector import QuestionChoice

_NULLABLE_NUM = {"type": ["number", "null"]}
_NULLABLE_BOOL = {"type": ["boolean", "null"]}

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value_text": {"type": ["string", "null"]},
                    "value_number": _NULLABLE_NUM,
                    "value_bool": _NULLABLE_BOOL,
                    "range": {
                        "type": ["object", "null"],
                        "properties": {
                            "lo": _NULLABLE_NUM,
                            "lo_inc": _NULLABLE_BOOL,
                            "hi": _NULLABLE_NUM,
                            "hi_inc": _NULLABLE_BOOL,
                        },
                        "required": ["lo", "lo_inc", "hi", "hi_inc"],
                        "additionalProperties": False,
                    },
                    "status": {
                        "type": "string",
                        "enum": ["CLAIMED", "DECLARED_UNKNOWN", "UNKNOWN"],
                    },
                    "note": {"type": ["string", "null"]},
                    "quote": {"type": "string"},
                },
                "required": [
                    "key",
                    "value_text",
                    "value_number",
                    "value_bool",
                    "range",
                    "status",
                    "note",
                    "quote",
                ],
                "additionalProperties": False,
            },
        },
        "group_answer": {
            "type": ["object", "null"],
            "properties": {
                "group_id": {"type": "string"},
                "choice": {"type": "string", "enum": ["none_all", "expand"]},
                "quote": {"type": "string"},
            },
            "required": ["group_id", "choice", "quote"],
            "additionalProperties": False,
        },
        "user_code_claim": {"type": ["string", "null"]},
        "user_question": {"type": ["string", "null"]},
        "evidence_refused": {"type": "boolean"},
    },
    "required": ["facts", "group_answer", "user_code_claim", "user_question", "evidence_refused"],
    "additionalProperties": False,
}

EXTRACT_SYSTEM = """너는 사업장 폐기물 문진의 '사실 추출기'다. 판정은 하지 않는다.
폐기물인지, 지정폐기물인지, 분류번호가 무엇인지 결정하거나 추측하지 마라. 그건 규칙 엔진이 한다.

해야 할 일: 사용자 발화에서 '사실 목록'에 있는 사실만 뽑아 JSON으로 낸다.

규칙
1. key는 '사실 목록'에 있는 것만 쓴다. 목록에 없는 사실은 버린다.
2. 사용자가 분명히 말한 것만 뽑는다. 추측하거나 상식으로 채우지 마라. 애매하면 뽑지 않는다.
3. 값은 허용 값만 쓴다.
   - enum: value_text에 values의 '키'(예: "pp", "solid")를 쓴다. 라벨이나 별칭(aliases)을 보고 키로 바꾼다.
   - bool: value_bool에 true/false.
   - number: value_number에 사용자가 말한 숫자. 단위 환산은 하지 않는다.
   - "5% 미만"처럼 범위로 말하면 range에 쓴다(미만: hi=5, hi_inc=false / 이상: lo=5, lo_inc=true).
4. 수치를 말하지 않았으면 숫자를 만들지 마라. "기름이 좀 있다"처럼 양을 말하지 않은 진술은
   해당 수치 사실을 status "UNKNOWN", 값은 모두 null, note에 진술 요약을 남긴다.
   (단, '기름이 묻어 있음' 같은 다른 사실로 표현할 수 있으면 그 사실은 CLAIMED로 뽑는다.)
5. '직전 질문'에 대해 "모르겠다/몰라요/확인이 안 된다"고 하면 그 사실을 status "DECLARED_UNKNOWN"으로 낸다.
6. 직전 질문이 묶음 질문(group)이면:
   - "다 없어요/해당 없음/아니요 전부" → group_answer.choice = "none_all"
   - "있어요/하나 있어요/잘 모르겠어요" → group_answer.choice = "expand" (구체적으로 말한 사실은 facts에도 넣는다)
7. quote에는 근거가 된 사용자 발화 원문 일부를 그대로 복사한다(바꾸어 쓰지 마라).
8. 사용자가 분류번호(예: 51-03-01)를 말하면 user_code_claim에 그 번호를 그대로 쓴다. 그 번호를 사실로 넣지 마라.
9. 사용자가 무언가를 물으면(예: "왜 기름이 중요해?") user_question에 그 질문을 쓴다.
10. 서류·시험성적서가 없다거나 구할 수 없다고 하면 evidence_refused = true.
11. 뽑을 것이 없으면 facts는 빈 배열이다."""


def catalog_view(kb: KnowledgeBase, last_question: QuestionChoice | None) -> list[dict]:
    """LLM에 보여 줄 사실 목록. internal 사실은 직전 질문일 때 그 선택지만 보여 준다."""
    out = []
    for fd in kb.catalog.values():
        if fd.internal:
            if last_question is None or last_question.key != fd.key:
                continue
            vals = {str(o.value): o.label for o in last_question.value_options if o.kind == "value"}
            out.append(_fact_view(fd, vals))
            continue
        out.append(_fact_view(fd))
    return out


def _fact_view(fd: FactDef, values: dict[str, str] | None = None) -> dict:
    v: dict[str, Any] = {"key": fd.key, "type": fd.type, "question": fd.question_hint}
    if fd.label:
        v["label"] = fd.label
    if fd.unit:
        v["unit"] = fd.unit
    if fd.type == "enum":
        v["values"] = (
            values
            if values is not None
            else {k: fd.value_labels.get(k, k) for k in (fd.values or ())}
        )
        if fd.value_aliases and values is None:
            v["aliases"] = {k: list(a) for k, a in fd.value_aliases.items()}
    return v


def _question_view(q: QuestionChoice | None) -> dict | None:
    if q is None:
        return None
    return {
        "type": q.unit,
        "key": q.key,
        "facts": q.facts,
        "question": q.question_hint,
        "options": [o.label for o in q.value_options],
    }


def build_user_prompt(
    kb: KnowledgeBase,
    text: str,
    *,
    effective: dict[str, Fact],
    last_question: QuestionChoice | None,
    recent: list[dict],
    feedback: list[str] | None = None,
) -> str:
    known = {
        k: (f.value.model_dump() if hasattr(f.value, "model_dump") else f.value)
        for k, f in effective.items()
        if f.is_known
    }
    payload: dict[str, Any] = {
        "사실 목록": catalog_view(kb, last_question),
        "현재 알고 있는 사실": known,
        "직전 질문": _question_view(last_question),
        "최근 대화": recent[-6:],
        "사용자 발화": text,
    }
    if feedback:
        payload["이전 출력의 오류(고쳐서 다시 내라)"] = feedback
    return json.dumps(payload, ensure_ascii=False)


def extract(
    llm: LLMClient,
    kb: KnowledgeBase,
    text: str,
    *,
    effective: dict[str, Fact],
    last_question: QuestionChoice | None,
    recent: list[dict],
    message_id: str,
    prompt_version: str,
    max_retries: int = 1,
) -> tuple[ExtractionResult, list[LLMCall]]:
    """LLM 추출 → guard 검증. 거부가 있으면 오류를 붙여 1회 재시도한다."""
    calls: list[LLMCall] = []
    feedback: list[str] | None = None
    result = ExtractionResult()
    for attempt in range(max_retries + 1):
        user = build_user_prompt(
            kb,
            text,
            effective=effective,
            last_question=last_question,
            recent=recent,
            feedback=feedback,
        )
        call = llm.complete_json(
            name="extract",
            system=EXTRACT_SYSTEM,
            user=user,
            schema=EXTRACTION_SCHEMA,
            prompt_version=prompt_version,
        )
        calls.append(call)
        if call.error or call.parsed is None:
            result = ExtractionResult(errors=[call.error or "응답 없음"])
            feedback = None
            continue
        result = validate_extraction(
            kb, call.parsed, text, last_question=last_question, message_id=message_id
        )
        result.attempts = attempt + 1
        if not result.rejected:
            break
        feedback = [f"{r['key']}: {r['reason']}" for r in result.rejected]
    return result, calls
