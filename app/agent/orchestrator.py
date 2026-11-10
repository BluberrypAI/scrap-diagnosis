"""문진 세션 한 턴 처리 (docs/engine/algorithm.md 7절).

영속화는 `export_state`/`from_state`로 한다(M4).

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

from app.agent.assist import INTENTS, build_context, to_view
from app.agent.extractor import extract
from app.agent.guard import ExtractionResult, norm
from app.agent.llm_client import LLMCall, LLMClient
from app.agent.responder import respond
from app.agent.router import Branch, EngineStep, SessionState, run_engine
from app.agent.templates import RETRACT_REPLY_LABEL
from app.domain.clock import seoul_today, utcnow
from app.domain.facts import Fact, FactStatus, FactStore, retract_fact
from app.domain.ranges import NumRange
from app.domain.trace import TraceTurn
from app.domain.verdict import TurnResponse, build_ui, build_verdict, fact_label, value_label
from app.rules.answers import AnswerError, fact_answer, group_none_answer
from app.rules.model import KnowledgeBase, Rule
from app.rules.selector import UNKNOWN_LABEL, QuestionChoice

EVIDENCE_REFUSE_REPLY = "서류가 없어요"
EVIDENCE_UPLOAD_REPLY = "서류를 올릴게요"


class QuickReply(BaseModel):
    """선택지 버튼 응답. LLM을 거치지 않는다.

    kind: value(값) / unknown(모름) / none_all·expand(묶음 질문) /
    retract(그 사실을 '모르는 상태'로 되돌림, docs/ui/ui-contract.md 4절)
    """

    key: str  # fact key 또는 group_id
    kind: Literal["value", "unknown", "none_all", "expand", "retract"] = "value"
    value: Any = None


def _default_web_search():  # noqa: ANN202
    from app.agent.web_search import get_web_search
    from app.config import get_settings

    return get_web_search(get_settings())


def _skill_hash(text: str | None) -> str | None:
    """어떤 스킬 지침으로 설명했는지 Trace에 남기는 짧은 해시."""
    if not text:
        return None
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _now_iso() -> str:
    """대화 기록 시각(UTC ISO 8601). 응답으로 낼 때 Asia/Seoul로 바꾼다."""
    return utcnow().isoformat(timespec="seconds")


def _same_value(a: Any, b: Any) -> bool:
    def norm_v(v: Any) -> Any:
        if isinstance(v, dict) and v:
            try:
                return NumRange(**v)
            except (TypeError, ValueError):
                return v
        return v

    return norm_v(a) == norm_v(b)


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
        # 보충 설명의 마지막 수단(준비된 자료가 없을 때만). 설정이 없으면 None
        # (app/agent/web_search.py)
        self.web_search = _default_web_search() if responder_llm is not None else None
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
        intent = None
        prev_question = self.last_question  # 답과 "왜?"가 함께 오면 이 질문을 설명한다
        if text:
            self.messages.append(
                {"role": "user", "id": turn_id, "text": text, "memo": _is_memo, "at": _now_iso()}
            )
        elif quick_reply is not None:
            # 버튼 답도 대화 기록에 남긴다(고른 선택지 라벨 + 보낸 값). 화면을 다시 그릴 때 쓴다.
            self.messages.append(
                {
                    "role": "user",
                    "id": turn_id,
                    "text": self.quick_reply_label(quick_reply),
                    "memo": False,
                    "quick_reply": quick_reply.model_dump(mode="json"),
                    "at": _now_iso(),
                }
            )

        if quick_reply is not None:
            appended = self._apply_quick_reply(quick_reply, turn_id)
        elif text:
            extraction, calls = self._extract(text, turn_id)
            appended = self._apply_extraction(extraction)
            user_question = extraction.user_question
            if extraction.question_kind in INTENTS:
                intent = extraction.question_kind

        step = run_engine(
            self.kb,
            self.store,
            self.state,
            self.as_of,
            max_questions=self.max_questions,
            user_question=user_question,
        )
        # 보충 설명: 엔진 평가가 끝난 뒤 그 결과를 설명할 자료만 모은다(판정 무관)
        assist_ctx = (
            build_context(
                self.kb,
                step,
                self.rule_index,
                intent,
                user_question,
                answered_question=prev_question if appended else None,
                web=self.web_search,
            )
            if intent
            else None
        )
        # 입력이 AI 전송 정책으로 막힌 턴은 응답도 템플릿으로 한다
        blocked = extraction.llm_blocked if extraction else None
        out, rcalls = respond(
            None if blocked else self.responder_llm,
            self.kb,
            step,
            self.rule_index,
            prompt_version=self.prompt_version,
            user_question=user_question,
            assist=assist_ctx,
        )
        calls += rcalls
        assist_view = to_view(assist_ctx, out.assist_text or "") if assist_ctx is not None else None
        if blocked and not out.llm_blocked:
            out.llm_blocked = blocked

        d = step.decision
        if d.branch == Branch.ASK_FACT and d.question is not None:
            self.state.questions_asked += 1
            self.last_question = d.question
        else:
            self.last_question = None
        self.last_step = step
        self.case_status = d.next_status
        q = d.question
        self.messages.append(
            {
                "role": "assistant",
                "id": turn_id,
                "text": out.message,
                **({"assist": assist_view.model_dump(mode="json")} if assist_view else {}),
                "branch": d.branch.value,
                "question_key": q.key if q is not None else None,
                "at": _now_iso(),
            }
        )

        resp = TurnResponse(
            case_id=self.case_id,
            session_id=self.session_id,
            turn_id=turn_id,
            branch=d.branch.value,
            sub_branch=d.sub_branch,
            message=out.message,
            verdict=build_verdict(self.kb, step, self.rule_index),
            ui=build_ui(
                self.kb,
                step,
                self.rule_index,
                suggested_replies=out.suggested_replies,
                questions_asked=self.state.questions_asked,
                max_questions=self.max_questions,
            ),
            case_status=self.case_status,
            assist=assist_view,
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
                responder={
                    "used_template": out.used_template,
                    "problems": out.problems,
                    **(
                        {
                            "assist_intent": intent,
                            "assist_cited_ids": out.assist_cited_ids,
                            # 준비된 자료로 답했나(아니면 설명 자료 보강 대상), 웹 검색을 썼나
                            "assist_matched": assist_ctx.matched,
                            "assist_web": assist_ctx.web_used,
                            "skill_hash": _skill_hash(self.kb.skill_text),
                            # 보충 설명용으로 엔진이 찾은 자료 전체(개발자 화면 '찾은 자료만')
                            "assist_found": assist_ctx.payload(),
                            "assist_used_template": out.used_template,
                        }
                        if assist_view
                        else {}
                    ),
                    **({"llm_blocked": out.llm_blocked} if out.llm_blocked else {}),
                },
                response=resp.model_dump(mode="json"),
            )
        )
        return resp

    # ---- 입력 반영 -----------------------------------------------------------------------

    def _extract(self, text: str, turn_id: str) -> tuple[ExtractionResult, list[LLMCall]]:
        if self.extractor_llm is None:
            return self._match_option(text, turn_id), []
        # 버튼 답 기록은 추출기 문맥에 넣지 않는다(M4까지와 같은 문맥)
        said = [m for m in self.messages if not m.get("quick_reply")]
        recent = [{"role": m["role"], "text": m["text"]} for m in said[-7:-1]]
        result, calls = extract(
            self.extractor_llm,
            self.kb,
            text,
            effective=self.store.effective(),
            last_question=self.last_question,
            recent=recent,
            message_id=turn_id,
            prompt_version=self.prompt_version,
        )
        if result.llm_blocked:
            # AI 전송 정책으로 막힘(가리기 실패 등): AI가 꺼진 것처럼 버튼 답만 받는다
            blocked = result.llm_blocked
            result = self._match_option(text, turn_id)
            result.llm_blocked = blocked
        return result, calls

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

    def quick_reply_label(self, qr: QuickReply) -> str:
        """버튼 답을 대화 기록에 남길 문장. 직전 질문의 선택지면 그 라벨, 아니면 '항목: 값'."""
        q = self.last_question
        if q is not None and q.key == qr.key and qr.kind != "retract":
            for o in q.value_options:
                if o.kind != qr.kind:
                    continue
                if o.kind != "value" or _same_value(o.value, qr.value):
                    return o.label
        if qr.key == "__evidence__":
            return EVIDENCE_REFUSE_REPLY if qr.value == "refused" else EVIDENCE_UPLOAD_REPLY
        g = self.kb.group(qr.key)
        if g is not None:
            return {"none_all": g.none_label, "expand": g.expand_label}.get(qr.kind, g.title)
        label = fact_label(self.kb, qr.key)
        if qr.kind == "retract":
            return RETRACT_REPLY_LABEL.format(label=label)
        if qr.kind == "unknown":
            return f"{label}: {UNKNOWN_LABEL}"
        return f"{label}: {value_label(self.kb, qr.key, qr.value) or qr.value}"

    def _apply_quick_reply(self, qr: QuickReply, turn_id: str) -> list[Fact]:
        if qr.kind in ("none_all", "expand"):
            return self._apply_group(qr.key, qr.kind, turn_id)
        if qr.key == "__evidence__":
            if qr.value == "refused":
                self.state.evidence_refused = True
            return []
        if qr.kind == "retract":
            # 앞선 진술을 지우지 않고 철회 행을 append한다(EVIDENCED는 그대로 유효)
            if qr.key not in self.kb.catalog:
                return []
            f = retract_fact(qr.key, source_ref=turn_id)
            self.store.append(f)
            return [f]
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
