"""말(자유 문장) 이해: 가리기 → 추출 AI(제안) → 검사기 → 사실 기록 / 확인 버튼 / 질의응답 agent.

한 턴의 흐름(workflow)
1. 식별 정보를 가린다(redact). 가리기에 실패하면 AI로 보내지 않는다(fail-closed)
2. 추출 AI가 의도와 사실 후보를 낸다. DB 트랜잭션을 닫고 부른다(연결을 붙잡지 않게)
3. 검사기가 카탈로그·근거 문구로 거른다. 단정한 답은 바로 기록하고, 추측한 답과 말로 한
   '지정폐기물 가능성을 지우는 답'은 확인 버튼(CONFIRM_GUESS)으로 미룬다
4. 문진에 관한 질문은 질의응답 agent(app/llm/assist.py)가 자료를 찾아 답한다. 판정은 바꾸지 않는다
무엇을 물을지와 판정은 이 모듈이 정하지 않는다(다음 질문 계산기·규칙 엔진).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.engine.planner import question_facts
from app.interview import catalog as cat
from app.interview import guard
from app.interview import present as pr
from app.llm import redact
from app.llm.assist import run_agent
from app.llm.extract import build_user, extract
from app.persistence.models import Case, Message

logger = logging.getLogger(__name__)

NO_LLM = "지금은 말로 답하기를 쓸 수 없어요. 아래 버튼으로 답해 주세요."
BLOCKED = "개인 정보(전화번호·주소 등)가 있어 AI로 보내지 않았어요. 아래 버튼으로 답해 주세요."
FAILED = "말씀을 이해하지 못했어요. 아래 버튼으로 답해 주세요."
UNCLEAR = "무슨 말씀인지 정확히 몰라서, 아래에서 골라 주세요."
OFF_TOPIC = (
    "저는 폐기물 분류 문진만 도와드려요. 업체 추천은 문진을 확정한 뒤 경로 화면에서 볼 수 있어요."
)
GROUP_BUTTON = "오염 여부는 판정에 중요해서 버튼으로 한 번 더 확인할게요."
REFUSALS = {
    "서류가 없어요",
    "서류 없어요",
    "서류 없음",
    "성적서가 없어요",
    "성적서 없어요",
    "없어요",
}


def is_refusal(text: str) -> bool:
    """서류 카드의 '서류가 없어요' 버튼(웹은 이 문장을 text로 보낸다). AI 없이 바로 처리한다."""
    return text.strip().rstrip(".!") in REFUSALS


class UnderstandMixin:
    """CaseService에 섞어 쓴다(self.db, self.kb, self.settings, self.llm, record, step, ...)."""

    llm: Any = None

    def recent(self, case: Case) -> list[dict]:
        rows = self.db.scalars(
            select(Message).where(Message.case_id == case.id).order_by(Message.id.desc()).limit(6)
        ).all()
        return [{"role": m.role, "text": m.text[:300]} for m in reversed(rows)]

    def trace_llm(self, case: Case, turn_id: str, call, user: str) -> None:
        scrubbed = redact.scrub_call(call, user, store_prompts=self.settings.trace_store_prompts)
        self.trace(case, turn_id, "LLM", scrubbed.model_dump(mode="json"), None)

    def understand(self, case: Case, text: str, turn_id: str) -> tuple[str | None, str, dict, Any]:
        """말 한 마디를 처리한다. (응답 앞에 붙일 말, Trace 종류, Trace 내용, assist)."""
        step = self.step(case)
        if step.branch == "REQUEST_EVIDENCE" and is_refusal(text):
            for f in step.asked_facts:
                self.record(case, f, "unknown", "UTTERANCE", turn_id)
            return None, "ANSWER", {"text": text, "refused": True}, None
        if self.llm is None:
            return NO_LLM, "TEXT", {"text": text}, None
        try:
            masked = redact.redact(text).text
        except redact.RedactionError:
            return BLOCKED, "TEXT", {"blocked": "redaction"}, None
        user = build_user(
            self.kb,
            step.facts,
            step.question,
            step.requested_documents,
            redact.redact_obj(self.recent(case)),
            masked,
        )
        self.db.commit()  # AI를 기다리는 동안 DB 트랜잭션을 열어 두지 않는다
        proposal, call = extract(self.llm, user, self.settings.prompt_version)
        self.trace_llm(case, turn_id, call, user)
        if proposal is None:
            return FAILED, "TEXT", {"error": call.error}, None
        res = guard.check(self.kb, proposal, masked, step.question, step.plan_question)
        notes: list[str] = []
        recorded = self.apply_proposal(case, step, res, turn_id)
        if recorded:
            notes.append("알겠어요. " + ", ".join(recorded) + "(으)로 적었어요.")
        if res.group_needs_button:
            notes.append(GROUP_BUTTON)
        if proposal.intent == "refuse_document" and step.branch == "REQUEST_EVIDENCE":
            for f in step.asked_facts:
                self.record(case, f, "unknown", "UTTERANCE", turn_id)
        assist = None
        if proposal.intent == "question" or proposal.question_text:
            assist = self.answer_question(case, proposal.question_text or masked, turn_id)
            if assist is None:
                notes.append("질문에 답할 자료를 찾지 못했어요.")
        elif proposal.intent == "off_topic":
            notes.append(OFF_TOPIC)
        elif proposal.intent == "unclear" and not recorded and not res.confirm:
            notes.append(UNCLEAR)
        if recorded or res.confirm or res.group_none_all:
            case.questions_asked += 1
        payload = {
            "intent": proposal.intent,
            "accepted": [c.key for c in res.accepted],
            "confirm": [c.key for c in res.confirm],
            "confirm_values": {c.key: c.value for c in res.confirm},
            "rejected": res.rejected,
            "group_none_all": res.group_none_all,
        }
        return (" ".join(notes) or None), "UNDERSTAND", payload, assist

    def apply_proposal(self, case: Case, step, res: guard.GuardResult, turn_id: str) -> list[str]:
        """검사를 통과한 값을 기록하고, 확인이 필요한 값은 확인 목록에 둔다. 기록한 값의 라벨."""
        labels = []
        for c in res.accepted:
            self.record(case, c.key, c.value, "UTTERANCE", turn_id, quote=c.quote)
            labels.append(cat.value_label(self.catalog, c.key, c.value))
        if res.group_none_all and step.plan_question:
            q = step.plan_question
            ask = [f for f in step.next.facts if f in question_facts(q)]
            for f, v in pr.group_none_values(self.kb, q, ask).items():
                self.record(case, f, v, "SCREENING", turn_id)
            labels.append(f"'{q.get('text', '')}' → 모두 해당 없음")
        if res.confirm:
            pending = [p for p in case.pending if p["fact"] not in {c.key for c in res.confirm}]
            for c in res.confirm:
                reason = "guess" if c.certainty == "guess" else "risky"
                pending.append(
                    {"fact": c.key, "value": c.value, "quote": c.quote, "reason": reason}
                )
            case.pending = pending
        return labels

    def case_snapshot(self, case: Case) -> dict:
        """agent의 case_state 도구가 보는 요약(읽기 전용, 식별 정보 없음)."""
        states = self.states(case)
        step = self.step(case, states)
        final = step.branch == "FINAL_REVIEW"
        r = step.next.result
        return {
            "answers": {
                k: cat.value_label(
                    self.catalog, k, "unknown" if s.status == "DECLARED_UNKNOWN" else s.value
                )
                for k, s in states.items()
            },
            "question": (step.question or {}).get("text") or (step.plan_question or {}).get("text"),
            "question_facts": step.asked_facts,
            "branch": step.branch,
            "outcome": r.outcome if final else None,
            "code": pr.public_code(r) if final else None,
            "rule_id": pr.deciding_rule(r) if final else None,
        }

    def answer_question(self, case: Case, question: str, turn_id: str) -> dict | None:
        """질의응답 agent: 자료를 찾아 답한다. 판정은 바꾸지 않는다. 실패하면 None."""
        state = self.case_snapshot(case)
        self.db.commit()  # AI를 기다리는 동안 DB 트랜잭션을 열어 두지 않는다
        assist, calls, steps = run_agent(
            self.llm,
            self.kb,
            question=question,
            state=state,
            max_tool_calls=self.settings.assist_max_tool_calls,
            prompt_version=self.settings.prompt_version,
        )
        for call in calls:
            self.trace_llm(case, turn_id, call, call.user)
        self.trace(
            case,
            turn_id,
            "ASSIST",
            {
                "tools": [
                    {
                        "tool": s["tool"],
                        "arg": s["arg"],
                        "ids": [r.get("id") or r.get("rule_id") for r in s["results"]],
                    }
                    for s in steps
                ]
            },
            None,
        )
        return assist
