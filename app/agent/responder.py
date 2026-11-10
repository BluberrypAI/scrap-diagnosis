"""응답 생성 (docs/engine/algorithm.md 7절). 라우터가 고른 분기 안에서 '말'만 만든다.

- payload에 없는 코드·수치·조문은 말하지 않는다(guard가 검사).
- 한 턴에 질문은 하나.
- 선택지 버튼(suggested_replies)은 LLM이 아니라 코드가 결정적으로 만든다.
- LLM이 없거나 검증에 두 번 실패하면 결정적 템플릿 문구를 쓴다.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from app.agent import templates
from app.agent.guard import validate_response
from app.agent.llm_client import LLMCall, LLMClient
from app.agent.redact import RedactionError, find_identifiers, redact_obj, scrub_call
from app.agent.router import Branch, EngineStep, blocking_view
from app.config import Settings, get_settings
from app.rules.model import KnowledgeBase, Rule

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "cited_basis_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["message", "cited_basis_ids"],
    "additionalProperties": False,
}

RESPOND_SYSTEM = """너는 사업장 폐기물 분류 문진 도우미다. 기업 담당자에게 한국어 존댓말로 짧게(2~4문장) 말한다.
판정과 다음 행동은 이미 규칙 엔진이 정했다. 너는 주어진 payload를 자연스러운 문장으로 옮기기만 한다.

규칙
1. payload에 없는 분류번호·수치·법 조문·기관명을 말하지 마라. 숫자는 payload에 있는 숫자만 쓴다.
2. branch가 ASK_FACT면 payload.question의 질문 하나만 묻는다. 물음표는 한 번만 쓴다. 선택지는 화면에 버튼으로
   나오므로 문장에 나열하지 않아도 된다. 질문의 뜻이 어려우면 help를 참고해 한 문장으로 쉽게 풀어 준다.
   묶음 질문(type=group)에 already_answered가 있으면, 그 항목은 확인했다고 말하고 items(남은 항목)만 묻는다.
3. REQUEST_EVIDENCE면 필요한 서류와 그 서류로 확인할 항목을 말한다.
4. FINAL_REVIEW면 판정을 말하고, 맞으면 '확정'을 눌러 달라고 한다. unverified가 true면
   '검토 전 규칙에 따른 참고 판정'이라고 덧붙인다. 근거를 말했다면 그 basis의 id를 cited_basis_ids에 넣는다.
   - verdict.code가 있으면 분류번호와 명칭을 말한다.
   - verdict.code가 null이면(result_type NO_CODE) 분류번호를 말하지 말고 verdict.conclusion의 결론을
     쉬운 말로 전한 뒤, next_step처럼 확정하면 다음 단계에서 처리 방법을 안내한다고 말한다.
5. RESOLVE_CONFLICT면 어떤 값이 서로 다른지 말하고 어느 쪽이 맞는지 묻는다.
6. UNSUPPORTED면 왜 정할 수 없는지(failure_text)와 확인할 항목을 안내한다. 판정을 대신 내리지 마라.
7. user_question이 있으면 먼저 help 내용 안에서만 짧게 답하고, 이어서 원래 분기의 말을 한다.
   help에 답이 없으면 '근거 자료를 확인해 안내하겠다'고만 한다.
8. 판정을 바꾸거나 새 사실을 추측하지 마라."""


class ResponderOutput(BaseModel):
    message: str
    cited_basis_ids: list[str] = []
    suggested_replies: list[str] = []
    used_template: bool = False
    problems: list[str] = []
    payload: dict = {}
    llm_blocked: str | None = None  # AI 전송을 막은 이유(가리기 실패). 템플릿으로 답했다


def _fact_label(kb: KnowledgeBase, key: str) -> str:
    fd = kb.catalog.get(key)
    return (fd.label or fd.question_hint) if fd else key


def build_payload(
    kb: KnowledgeBase,
    step: EngineStep,
    rule_index: dict[str, Rule],
    *,
    user_question: str | None = None,
) -> dict[str, Any]:
    d, ev = step.decision, step.evaluation
    p: dict[str, Any] = {"branch": d.branch.value}
    if d.branch == Branch.ASK_FACT and d.question is not None:
        q = d.question
        p["question"] = {
            "key": q.key,
            "type": q.unit,
            "question": q.question_hint,
            "help": q.help,
            "options": [o.label for o in q.value_options],
        }
        if q.unit == "group":
            g = kb.group(q.key)
            answered = [
                k
                for k in (g.facts if g else ())
                if k not in q.facts and k in step.effective and step.effective[k].is_known
            ]
            p["question"]["items"] = [_fact_label(kb, k) for k in q.facts]
            if answered:
                # 일부만 답한 묶음을 다시 물을 때: 남은 항목만 짚는다
                p["question"]["already_answered"] = [_fact_label(kb, k) for k in answered]
    elif d.branch == Branch.REQUEST_EVIDENCE:
        p["documents"] = [
            {
                "evidence_type": doc.evidence_type,
                "label": templates.evidence_label(doc.evidence_type),
                "facts": doc.facts,
                "fact_labels": [_fact_label(kb, k) for k in doc.facts],
            }
            for doc in d.requested_documents
        ]
    elif d.branch == Branch.FINAL_REVIEW and ev.decided is not None:
        c = ev.decided
        rule = rule_index.get(c.rule_ids[0])
        basis = []
        for i, b in enumerate(rule.basis if rule else (), start=1):
            basis.append({"id": f"B{i}", "type": b.type, "ref": b.ref, "excerpt": b.excerpt})
        if c.code is not None:
            p["verdict"] = {"code": c.code, "name": c.name, "category": c.category}
        else:  # 코드 없는 결론: 결론 문장과 확정 후 다음 단계 안내
            p["verdict"] = {
                "code": None,
                "result_type": "NO_CODE",
                "outcome": c.outcome,
                "category": c.category,
                "conclusion": templates.OUTCOME_TEXT.get(c.outcome or "", ""),
                "reason": templates.outcome_reason(c.name),
            }
            p["next_step"] = no_code_next_step(kb, c.outcome)
        p["basis"] = basis
        p["unverified"] = bool(rule and rule.review == "UNVERIFIED")
    elif d.branch == Branch.RESOLVE_CONFLICT:
        p["conflicts"] = [c.model_dump(mode="json") for c in d.conflicts]
    elif d.branch == Branch.UNSUPPORTED:
        p["failure_reason"] = d.failure_reason
        p["failure_text"] = templates.FAILURE_TEXT.get(d.failure_reason or "NO_PATH", "")
        p["open_items"] = [
            _fact_label(kb, u.key)
            for u in ev.blocking_facts
            if not (kb.catalog.get(u.key) and kb.catalog[u.key].internal)
        ]
        # 어떻게 하면 이어지는지: 서류로 받을 사실 / '모름'으로 답한 사실
        ev_types = sorted(
            {u.evidence_type or "DOCUMENT" for u in blocking_view(kb, ev, step.effective).evidence}
        )
        p["evidence_labels"] = [templates.evidence_label(x) for x in ev_types]
        p["needs_test_report"] = "TEST_REPORT" in ev_types
        unknown = [
            u.key
            for u in ev.blocking_facts
            if u.reason == "DECLARED_UNKNOWN"
            and not (kb.catalog.get(u.key) and kb.catalog[u.key].internal)
            and (kb.catalog[u.key].evidence_type or "DOCUMENT") not in ev_types
        ]
        p["unknown_items"] = [_fact_label(kb, k) for k in unknown]
        first = kb.catalog.get(unknown[0]) if unknown else None
        p["unknown_hint"] = (first.help or "").splitlines()[0] if first and first.help else None
    if user_question:
        p["user_question"] = user_question
        q = d.question
        fd = kb.catalog.get(q.facts[0]) if (q and q.facts) else None
        p["help"] = (q.help if q else None) or (fd.help if fd else None)
    return p


def no_code_next_step(kb: KnowledgeBase, outcome: str | None) -> str:
    """확정하면 이어질 안내(경로추천 행동 이름). 안내 표에 없으면 기본 문장."""
    try:
        action = kb.guidance_for("NO_CODE", outcome).action
    except KeyError:
        action = None
    return templates.no_code_next_step(action)


def suggested_replies(step: EngineStep) -> list[str]:
    d = step.decision
    if d.branch == Branch.ASK_FACT and d.question is not None:
        return [o.label for o in d.question.value_options]
    if d.branch == Branch.REQUEST_EVIDENCE:
        return ["서류를 올릴게요", "서류가 없어요"]
    if d.branch == Branch.FINAL_REVIEW:
        return ["확정", "다시 확인할게요"]
    return []


def respond(
    llm: LLMClient | None,
    kb: KnowledgeBase,
    step: EngineStep,
    rule_index: dict[str, Rule],
    *,
    prompt_version: str,
    user_question: str | None = None,
    max_retries: int = 1,
    settings: Settings | None = None,
) -> tuple[ResponderOutput, list[LLMCall]]:
    payload = build_payload(kb, step, rule_index, user_question=user_question)
    replies = suggested_replies(step)
    cfg = settings or get_settings()
    blocked: str | None = None
    send_payload = payload
    if llm is not None:
        try:  # 사용자 발화·값 등이 섞일 수 있으므로 보내기 전 가린다(fail-closed)
            send_payload = redact_obj(payload)
            left = find_identifiers(json.dumps(send_payload, ensure_ascii=False))
            if left:
                raise RedactionError("가린 뒤에도 식별 정보가 남음: " + ", ".join(left))
        except RedactionError as exc:
            blocked = f"redaction_failed: {exc}"
            llm = None
    original_text = json.dumps(payload, ensure_ascii=False)
    payload_text = json.dumps(send_payload, ensure_ascii=False)
    basis_ids = {b["id"] for b in payload.get("basis", [])}
    calls: list[LLMCall] = []
    problems: list[str] = []
    if llm is not None:
        feedback: list[str] | None = None
        for _ in range(max_retries + 1):
            user = (
                payload_text
                if not feedback
                else json.dumps(
                    {"payload": send_payload, "이전 응답의 문제(고쳐서 다시 써라)": feedback},
                    ensure_ascii=False,
                )
            )
            call = llm.complete_json(
                name="respond",
                system=RESPOND_SYSTEM,
                user=user,
                schema=RESPONSE_SCHEMA,
                prompt_version=prompt_version,
            )
            calls.append(scrub_call(call, original_text, store_prompts=cfg.trace_store_prompts))
            if call.error or not call.parsed:
                problems.append(call.error or "응답 없음")
                feedback = None
                continue
            msg = str(call.parsed.get("message", ""))
            cited = [str(x) for x in call.parsed.get("cited_basis_ids", [])]
            found = validate_response(msg, cited, send_payload, payload_text, basis_ids)
            if not found:
                return ResponderOutput(
                    message=msg,
                    cited_basis_ids=cited,
                    suggested_replies=replies,
                    problems=problems,
                    payload=payload,
                ), calls
            problems.extend(found)
            feedback = found
    msg = templates.render(step.decision.branch.value, payload)
    cited = [b["id"] for b in payload.get("basis", [])][:1]
    return ResponderOutput(
        message=msg,
        cited_basis_ids=cited,
        suggested_replies=replies,
        used_template=True,
        problems=problems,
        payload=payload,
        llm_blocked=blocked,
    ), calls
