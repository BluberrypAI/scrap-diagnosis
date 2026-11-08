"""문진 세션 한 턴 처리 (md 10절). 영속화는 `export_state`/`from_state`로 한다(M4).

1. 메시지 저장
2. (자유 진술) extractor → guard → 사실 append / (버튼) quick_reply → 결정적 append
3~5. run_engine: 평가 → 자동 채움 → 충돌 → 라우터(+selector)
6. responder → guard (실패 시 템플릿)
7. 상태 전이, Trace 저장
8. 응답 반환
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from app.agent.extractor import extract
from app.agent.guard import ExtractionResult, norm
from app.agent.llm_client import LLMCall, LLMClient
from app.agent.responder import respond
from app.agent.router import Branch, EngineStep, SessionState, run_engine
from app.domain.clock import seoul_today
from app.domain.facts import Fact, FactStatus, FactStore
from app.domain.trace import TraceTurn
from app.domain.verdict import UI, TurnResponse, build_verdict
from app.rules.answers import AnswerError, fact_answer, group_none_answer
from app.rules.model import KnowledgeBase, Rule
from app.rules.selector import QuestionChoice

EVIDENCE_REFUSE_REPLY = "서류가 없어요"
EVIDENCE_UPLOAD_REPLY = "서류를 올릴게요"


class QuickReply(BaseModel):
    """선택지 버튼 응답. LLM을 거치지 않는다."""

    key: str  # fact key 또는 group_id
    kind: Literal["value", "unknown", "none_all", "expand"] = "value"
    value: Any = None


class DiagnosisSession:
    def __init__(
        self,
        kb: KnowledgeBase,
        *,
        extractor_llm: LLMClient | None = None,
        responder_llm: LLMClient | None = None,
        case_id: str = "case",
        session_id: str | None = None,
        as_of: date | None = None,
        max_questions: int = 12,
        prompt_version: str = "m3.3",
    ):
        self.kb = kb
        self.extractor_llm = extractor_llm
        self.responder_llm = responder_llm
        self.case_id = case_id
        self.session_id = session_id or uuid.uuid4().hex
        self.as_of = as_of or seoul_today()  # 법 기준일: 대화를 시작한 Asia/Seoul 날짜
        self.max_questions = max_questions
        self.prompt_version = prompt_version
        self.store = FactStore()
        self.state = SessionState()
        self.messages: list[dict] = []
        self.last_question: QuestionChoice | None = None
        self.last_step: EngineStep | None = None
        self.traces: list[TraceTurn] = []
        self.case_status = "DIAGNOSING"
        self.rule_index: dict[str, Rule] = {r.rule_id: r for t in kb.tables for r in t.rules}

    # ---- 영속화 (M4) ---------------------------------------------------------------------
    # 사실 이력(store)과 Trace는 저장소가 행 단위로 따로 쌓는다(append-only). 여기서는 그 밖의
    # 세션 상태만 JSON으로 내보낸다. 사실 키에 대한 특별 처리는 없다(키·값만 그대로 저장).

    STATE_VERSION = 1

    def export_state(self) -> dict:
        """사실 이력·Trace를 뺀 세션 상태(JSON 직렬화 가능)."""
        return {
            "version": self.STATE_VERSION,
            "case_id": self.case_id,
            "session_id": self.session_id,
            "as_of": self.as_of.isoformat(),
            "max_questions": self.max_questions,
            "prompt_version": self.prompt_version,
            "case_status": self.case_status,
            "state": {
                "questions_asked": self.state.questions_asked,
                "expanded_groups": sorted(self.state.expanded_groups),
                "focus_codes": sorted(self.state.focus_codes),
                "evidence_refused": self.state.evidence_refused,
            },
            "last_question": (
                self.last_question.model_dump(mode="json") if self.last_question else None
            ),
            "messages": list(self.messages),
        }

    def to_state(self) -> dict:
        """세션 전체(사실 이력·Trace 포함). 파일 저장·테스트용."""
        return {
            **self.export_state(),
            "facts": [f.model_dump(mode="json") for f in self.store.history],
            "traces": [t.model_dump(mode="json") for t in self.traces],
        }

    @classmethod
    def from_state(
        cls,
        kb: KnowledgeBase,
        state: dict,
        *,
        facts: Iterable[Fact | dict] | None = None,
        traces: Iterable[TraceTurn | dict] | None = None,
        extractor_llm: LLMClient | None = None,
        responder_llm: LLMClient | None = None,
    ) -> DiagnosisSession:
        """`export_state`(또는 `to_state`) 결과와 사실 이력으로 세션을 다시 만든다.

        facts/traces를 주지 않으면 state 안의 'facts'/'traces'를 쓴다. 사실은 저장된 순서대로
        다시 쌓는다(기록 시각은 그대로 둔다 → 유효 사실 선택이 저장 전과 같다).
        """
        s = cls(
            kb,
            extractor_llm=extractor_llm,
            responder_llm=responder_llm,
            case_id=state["case_id"],
            session_id=state["session_id"],
            as_of=date.fromisoformat(state["as_of"]),
            max_questions=state.get("max_questions", 12),
            prompt_version=state.get("prompt_version", "m3.1"),
        )
        raw_facts = state.get("facts", []) if facts is None else facts
        s.store = FactStore(f if isinstance(f, Fact) else Fact.model_validate(f) for f in raw_facts)
        raw_traces = state.get("traces", []) if traces is None else traces
        s.traces = [
            t if isinstance(t, TraceTurn) else TraceTurn.model_validate(t) for t in raw_traces
        ]
        st = state.get("state") or {}
        s.state = SessionState(
            questions_asked=st.get("questions_asked", 0),
            expanded_groups=set(st.get("expanded_groups", ())),
            focus_codes=set(st.get("focus_codes", ())),
            evidence_refused=st.get("evidence_refused", False),
        )
        lq = state.get("last_question")
        s.last_question = QuestionChoice.model_validate(lq) if lq else None
        s.messages = list(state.get("messages", []))
        s.case_status = state.get("case_status", "DIAGNOSING")
        return s

    def peek(self) -> EngineStep:
        """사실·상태를 바꾸지 않고 지금 사실로 엔진을 돌린다(확정 전 서버 재검증용)."""
        state = SessionState(
            questions_asked=self.state.questions_asked,
            expanded_groups=set(self.state.expanded_groups),
            focus_codes=set(self.state.focus_codes),
            evidence_refused=self.state.evidence_refused,
        )
        return run_engine(
            self.kb, self.store.copy(), state, self.as_of, max_questions=self.max_questions
        )

    # ---- 시작 ----------------------------------------------------------------------------

    def seed(
        self,
        facts: dict[str, Any],
        *,
        source_type: str = "PROFILE",
        status: FactStatus = FactStatus.CLAIMED,
    ) -> None:
        """기업 프로필 등 문진 전에 아는 사실. 카탈로그에 없는 키는 무시한다."""
        for k, v in facts.items():
            if k in self.kb.catalog:
                self.store.append(
                    fact_answer(
                        self.kb, k, v, source_type=source_type, source_ref="profile", status=status
                    )
                )

    def start(self, memo: str | None = None) -> TurnResponse:
        """건 메모가 있으면 추출기에 한 번 통과시켜 선채운 뒤 첫 질문을 낸다."""
        if memo:
            return self.handle(text=memo, _is_memo=True)
        return self.handle()

    # ---- 한 턴 ---------------------------------------------------------------------------

    def handle(
        self, text: str | None = None, quick_reply: QuickReply | None = None, _is_memo: bool = False
    ) -> TurnResponse:
        turn_id = uuid.uuid4().hex[:12]
        calls: list[LLMCall] = []
        extraction: ExtractionResult | None = None
        appended: list[Fact] = []
        user_question = None
        if text:
            self.messages.append({"role": "user", "id": turn_id, "text": text, "memo": _is_memo})

        if quick_reply is not None:
            appended = self._apply_quick_reply(quick_reply, turn_id)
        elif text:
            extraction, calls = self._extract(text, turn_id)
            appended = self._apply_extraction(extraction)
            user_question = extraction.user_question

        step = run_engine(
            self.kb,
            self.store,
            self.state,
            self.as_of,
            max_questions=self.max_questions,
            user_question=user_question,
        )
        out, rcalls = respond(
            self.responder_llm,
            self.kb,
            step,
            self.rule_index,
            prompt_version=self.prompt_version,
            user_question=user_question,
        )
        calls += rcalls

        d = step.decision
        if d.branch == Branch.ASK_FACT and d.question is not None:
            self.state.questions_asked += 1
            self.last_question = d.question
        else:
            self.last_question = None
        self.last_step = step
        self.case_status = d.next_status
        self.messages.append({"role": "assistant", "id": turn_id, "text": out.message})

        q = d.question
        resp = TurnResponse(
            case_id=self.case_id,
            session_id=self.session_id,
            turn_id=turn_id,
            branch=d.branch.value,
            sub_branch=d.sub_branch,
            message=out.message,
            verdict=build_verdict(self.kb, step, self.rule_index),
            ui=UI(
                can_confirm=step.evaluation.can_confirm and d.branch == Branch.FINAL_REVIEW,
                suggested_replies=out.suggested_replies,
                requested_documents=[r.model_dump() for r in d.requested_documents],
                question=None
                if q is None
                else {
                    "key": q.key,
                    "unit": q.unit,
                    "facts": q.facts,
                    "options": [o.model_dump() for o in q.value_options],
                },
            ),
            case_status=self.case_status,
        )
        self.traces.append(
            TraceTurn(
                turn_id=turn_id,
                input_text=text,
                quick_reply=quick_reply.model_dump() if quick_reply else None,
                extraction=extraction.model_dump(mode="json") if extraction else None,
                appended_facts=[f.model_dump(mode="json") for f in appended],
                effective_facts={k: f.model_dump(mode="json") for k, f in step.effective.items()},
                table_id=step.evaluation.table_id,
                table_version=step.evaluation.table_version,
                rule_results=[
                    r.model_dump(mode="json")
                    for r in step.evaluation.rule_results
                    if r.status.value != "FALSE"
                ][:200],
                conflicts=[c.model_dump(mode="json") for c in step.conflicts],
                branch=d.branch.value,
                branch_rank=d.rank,
                branch_reason=d.reason,
                score_breakdown=[e.model_dump() for e in (q.score_breakdown if q else [])][:20],
                llm_calls=calls,
                responder={"used_template": out.used_template, "problems": out.problems},
                response=resp.model_dump(mode="json"),
            )
        )
        return resp

    # ---- 입력 반영 -----------------------------------------------------------------------

    def _extract(self, text: str, turn_id: str) -> tuple[ExtractionResult, list[LLMCall]]:
        if self.extractor_llm is None:
            return self._match_option(text, turn_id), []
        recent = [{"role": m["role"], "text": m["text"]} for m in self.messages[-7:-1]]
        return extract(
            self.extractor_llm,
            self.kb,
            text,
            effective=self.store.effective(),
            last_question=self.last_question,
            recent=recent,
            message_id=turn_id,
            prompt_version=self.prompt_version,
        )

    def _match_option(self, text: str, turn_id: str) -> ExtractionResult:
        """LLM이 없을 때: 직전 질문의 선택지 라벨과 정확히 같은 답만 받는다."""
        res = ExtractionResult()
        q = self.last_question
        if q is None:
            return res
        t = norm(text)
        for o in q.value_options:
            if norm(o.label) != t:
                continue
            if o.kind == "none_all":
                res.group_answer = {"group_id": q.key, "choice": "none_all"}
            elif o.kind == "expand":
                res.group_answer = {"group_id": q.key, "choice": "expand"}
            elif o.kind == "unknown":
                res.facts = [fact_answer(self.kb, q.key, None, unknown=True, source_ref=turn_id)]
            else:
                res.facts = [fact_answer(self.kb, q.key, o.value, source_ref=turn_id, quote=text)]
        if norm(text) == norm(EVIDENCE_REFUSE_REPLY):
            res.evidence_refused = True
        return res

    def _apply_extraction(self, ex: ExtractionResult) -> list[Fact]:
        appended: list[Fact] = []
        for f in ex.facts:
            self.store.append(f)
            appended.append(f)
        if ex.group_answer:
            appended += self._apply_group(
                ex.group_answer["group_id"],
                ex.group_answer["choice"],
                ex.facts[0].source_ref if ex.facts else "group",
            )
        if ex.user_code_claim:
            if ex.user_code_claim in self.kb.codes:
                self.state.focus_codes.add(ex.user_code_claim)
        if ex.evidence_refused:
            self.state.evidence_refused = True
        return appended

    def _apply_group(self, group_id: str, choice: str, ref: str) -> list[Fact]:
        if choice == "expand":
            self.state.expanded_groups.add(group_id)
            return []
        members = (
            self.last_question.facts
            if (self.last_question and self.last_question.key == group_id)
            else list(self.kb.group(group_id).facts)
        )
        effective = self.store.effective()
        open_members = [k for k in members if not (k in effective and effective[k].is_known)]
        facts = group_none_answer(self.kb, group_id, open_members, source_ref=ref)
        self.store.extend(facts)
        return facts

    def _apply_quick_reply(self, qr: QuickReply, turn_id: str) -> list[Fact]:
        if qr.kind in ("none_all", "expand"):
            return self._apply_group(qr.key, qr.kind, turn_id)
        if qr.key == "__evidence__":
            if qr.value == "refused":
                self.state.evidence_refused = True
            return []
        try:
            f = fact_answer(
                self.kb, qr.key, qr.value, unknown=qr.kind == "unknown", source_ref=turn_id
            )
        except AnswerError:
            return []
        self.store.append(f)
        return [f]

    # ---- 증빙 ----------------------------------------------------------------------------

    def add_evidence(self, facts: dict[str, Any], document_id: str) -> TurnResponse:
        """문서에서 확인된 값(EVIDENCED)을 넣고 다시 평가한다. 문서 파싱은 M4."""
        for k, v in facts.items():
            if k in self.kb.catalog:
                self.store.append(
                    fact_answer(
                        self.kb,
                        k,
                        v,
                        source_type="DOCUMENT",
                        source_ref=document_id,
                        status=FactStatus.EVIDENCED,
                    )
                )
        self.state.evidence_refused = False
        return self.handle()
