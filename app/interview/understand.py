"""말(자유 문장) 이해: 가리기 → 추출 AI(제안) → 검사기 → 사실 기록 / 확인 버튼 / 질의응답 agent.

한 턴의 흐름(workflow)
1. 식별 정보를 가린다(redact). 가리기에 실패하면 AI로 보내지 않는다(fail-closed)
2. 추출 AI가 의도와 사실 후보를 낸다. DB 트랜잭션을 닫고 부른다(연결을 붙잡지 않게)
3. 검사기가 카탈로그·근거 문구로 거른다. 단정한 답은 바로 기록하고, 추측한 답은 확인
   버튼(CONFIRM_GUESS)으로, 말로 한 '지정폐기물 가능성을 지우는 답'은 그 묶음 차례에
   한 번에 묻는 묶음 확인(CONFIRM_GROUP)으로 미룬다
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
CONTINUE = "이어서 볼게요."
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


# 확인 카드("…맞나요?")에 대한 짧은 말 답. AI 없이 바로 처리한다(공백·문장부호 무시)
YES = {"응", "어", "네", "예", "ㅇㅇ", "ㅇ", "넵", "네네", "맞아", "맞아요", "맞습니다",
       "그래", "그래요", "응맞아", "네맞아요", "예맞아요", "맞음", "ok", "yes"}  # fmt: skip
NO = {"아니", "아니요", "아니오", "아뇨", "아니야", "ㄴㄴ", "아닌데", "아니에요", "no"}
# 묶음 확인("모두 해당 없는 게 맞나요?")에서만: '없다'는 '맞다', '있다·모른다'는 '아니다'
GROUP_YES = {"없어", "없어요", "없음", "없습니다", "다없어", "다없어요", "해당없음", "해당없어요",
             "모두해당없음", "다해당없어요"}  # fmt: skip
GROUP_NO = {"있어", "있어요", "있음", "있습니다", "몰라", "몰라요", "모르겠어", "모르겠어요"}


def short_reply(text: str, group: bool = False) -> str | None:
    """'yes' | 'no' | None(짧은 예/아니요가 아님)."""
    s = "".join(ch for ch in text.lower() if ch.isalnum() or "ㄱ" <= ch <= "ㅣ")
    if s in YES or (group and s in GROUP_YES):
        return "yes"
    if s in NO or (group and s in GROUP_NO):
        return "no"
    return None


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
        group = step.sub_branch == "CONFIRM_GROUP"
        reply = short_reply(text, group) if step.sub_branch else None
        if reply is not None:
            return self.answer_confirm_text(case, step, reply, text, turn_id)
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
        confirmed_group = None
        if step.sub_branch == "CONFIRM_GROUP" and proposal.group_none_all:
            # 묶음 확인 카드("모두 해당 없는 게 맞나요?")를 본 뒤 말로 '맞다'고 한 답이 곧 확인이다
            confirmed_group = step.plan_question["id"]
            res.group_confirm.pop(confirmed_group, None)
        notes: list[str] = []
        recorded = self.apply_proposal(case, step, res, turn_id)
        if confirmed_group:
            self.answer(case, {"key": confirmed_group, "kind": "none_all"}, turn_id)
            recorded.append(f"'{step.plan_question.get('text', '')}' → 모두 해당 없음")
        if recorded:
            notes.append("알겠어요. " + ", ".join(recorded) + "(으)로 적었어요.")
        if proposal.intent == "refuse_document" and step.branch == "REQUEST_EVIDENCE":
            for f in step.asked_facts:
                self.record(case, f, "unknown", "UTTERANCE", turn_id)
        assist = None
        if proposal.intent == "question" or proposal.question_text:
            assist = self.answer_question(case, proposal.question_text or masked, turn_id)
            if assist is None:
                notes.append("질문에 답할 자료를 찾지 못했어요.")
        elif proposal.intent in ("off_topic", "unclear") and not (
            recorded or res.confirm or res.group_none_all or res.group_confirm
        ):
            # 가드레일: 무관·불분명한 말은 사실로 기록하지 않고, agent가 짧게 받아 문진으로 돌린다
            assist = self.answer_question(case, masked, turn_id, mode="guard")
            if assist is None:
                notes.append(OFF_TOPIC if proposal.intent == "off_topic" else UNCLEAR)
            else:
                notes.append(CONTINUE)
        if not confirmed_group and (
            recorded or res.confirm or res.group_none_all or res.group_confirm
        ):
            case.questions_asked += 1  # 묶음 확인을 마친 답은 answer()가 이미 셌다
        deferred = {f: v for g in res.group_confirm.values() for f, v in g["facts"].items()}
        payload = {
            "intent": proposal.intent,
            "accepted": [c.key for c in res.accepted],
            "confirm": [c.key for c in res.confirm] + list(deferred),
            "confirm_values": {c.key: c.value for c in res.confirm} | deferred,
            "rejected": res.rejected,
            "group_none_all": res.group_none_all,
            "group_confirm": sorted(res.group_confirm),
        }
        return (" ".join(notes) or None), "UNDERSTAND", payload, assist

    def answer_confirm_text(
        self, case: Case, step, reply: str, text: str, turn_id: str
    ) -> tuple[str | None, str, dict, Any]:
        """확인 카드에 말로 '응'·'아니'라고 한 답을 그 카드의 버튼 답으로 바꾼다."""
        q = step.question
        if step.sub_branch == "CONFIRM_GROUP":
            qr = {"key": q["key"], "kind": "none_all" if reply == "yes" else "expand"}
        else:  # CONFIRM_GUESS: [예, 값] / [아니요]
            yes = next(o for o in q["options"] if o["kind"] == "value")
            qr = (
                {"key": q["key"], "kind": "value", "value": yes["value"]}
                if reply == "yes"
                else {"key": q["key"], "kind": "expand"}
            )
        label = self.answer(case, qr, turn_id)
        prefix = f"알겠어요. {label}(으)로 적었어요." if reply == "yes" else None
        return prefix, "ANSWER", {"text": text, "confirm_reply": reply, "quick_reply": qr}, None

    def apply_proposal(self, case: Case, step, res: guard.GuardResult, turn_id: str) -> list[str]:
        """검사를 통과한 값을 기록하고, 확인이 필요한 값은 확인 목록에 둔다. 기록한 값의 라벨."""
        labels = []
        for c in res.accepted:
            self.record(case, c.key, c.value, "UTTERANCE", turn_id, quote=c.quote)
            labels.append(self.ack_label(c.key, c.value))
        if res.group_none_all and step.plan_question:
            q = step.plan_question
            ask = [f for f in step.next.facts if f in question_facts(q)]
            for f, v in pr.group_none_values(self.kb, q, ask).items():
                self.record(case, f, v, "SCREENING", turn_id)
            labels.append(f"'{q.get('text', '')}' → 모두 해당 없음")
        if res.confirm or res.group_confirm:
            keys = {c.key for c in res.confirm}
            pending = [
                p
                for p in case.pending
                if p.get("fact") not in keys and p.get("group") not in res.group_confirm
            ]
            for c in res.confirm:
                pending.append(
                    {"fact": c.key, "value": c.value, "quote": c.quote, "reason": "guess"}
                )
            for gid, g in res.group_confirm.items():
                # 묶음 확인: 그 묶음 차례에 '모두 해당 없는 게 맞나요?' 한 번으로 묻는다
                pending.append({"group": gid, "facts": g["facts"], "quote": g["quote"]})
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

    def ack_label(self, key: str, value: Any) -> str:
        """'적었어요' 안내에 쓸 라벨. 예/아니요 답은 무엇에 대한 답인지 보이게 쓴다."""
        q = next((q for q in self.kb.plan.questions if q.get("fact") == key), None)
        labels = {str(cat.norm(k)): v for k, v in ((q or {}).get("option_labels") or {}).items()}
        text = cat.value_label(self.catalog, key, value)
        if str(value) in labels:
            text = labels[str(value)]
        spec = cat.spec(self.catalog, key) or {}
        if spec.get("type") == "bool3" and q and q.get("text"):
            return f"'{q['text']}' → {text}"
        return text

    def answer_question(
        self, case: Case, question: str, turn_id: str, mode: str = "question"
    ) -> dict | None:
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
            mode=mode,
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
