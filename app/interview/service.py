"""문진 서비스: 건·사실 기록·대화·판정 버전을 DB에 두고, 턴마다 규칙 엔진으로 다시 계산한다.

- 판정은 매 턴 지금까지의 유효 사실 전체로 처음부터 다시 계산한다(상태 기계를 따로 두지 않음).
- 사실 기록은 append-only다. 고치기·철회도 새 행이다.
- 회사 질문(scope: company)의 답은 회사별로 기억해 다음 건에 미리 채운다(PROFILE).
- 말(text) 이해는 LLM 단계에서 붙인다. 지금은 대화에 남기고 버튼 답을 안내한다.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.api.errors import ApiError
from app.config import Settings
from app.engine.kb import KB
from app.engine.planner import question_facts
from app.interview import catalog as cat
from app.interview import present as pr
from app.interview.documents import DocumentMixin
from app.interview.present import FactState, Step
from app.interview.understand import UnderstandMixin
from app.llm.phrase import phrase
from app.persistence.models import (
    Case,
    Company,
    CompanyFact,
    DeletionLog,
    Document,
    DocumentValue,
    FactRecord,
    Message,
    TraceEvent,
    Verdict,
    new_id,
    now,
)

STATUS_LABEL = {
    "DIAGNOSING": "문진 중",
    "NEEDS_INFO": "추가 정보 필요",
    "CODE_CONFIRMED": "확정",
}
NEXT_ACTION = {
    "RECOMMEND_ROUTE": "경로 추천 대기",
    "NO_ROUTE_NEEDED": "처리 경로 필요 없음",
    "REFER_OTHER_LAW": "다른 법 안내",
    "REFER_MUNICIPALITY": "지자체 배출 안내",
    "NEEDS_TEST": "시험·확인 안내",
    "MANUAL_CLASSIFICATION": "담당자 확인 안내",
}


def not_found() -> ApiError:
    return ApiError(404, "CASE_NOT_FOUND", "건을 찾을 수 없습니다")


class CaseService(DocumentMixin, UnderstandMixin):
    def __init__(self, db: Session, kb: KB, settings: Settings, llm: Any = None) -> None:
        self.db, self.kb, self.settings, self.llm = db, kb, settings, llm
        self.catalog = kb.plan.catalog
        self.company_facts = {
            f for q in kb.plan.questions if q.get("scope") == "company" for f in question_facts(q)
        }
        self.groups = {q["id"]: q for q in kb.plan.questions if q.get("kind") == "group"}

    # ---- 공통 --------------------------------------------------------------------------------

    def company(self, external_id: str) -> Company:
        c = self.db.scalar(select(Company).where(Company.external_id == external_id))
        if c is None:
            c = Company(external_id=external_id)
            self.db.add(c)
            self.db.flush()
        return c

    def get_case(self, company: Company, case_id: str) -> Case:
        case = self.db.get(Case, case_id)
        if case is None or case.company_id != company.id:
            raise not_found()
        return case

    def states(self, case: Case) -> dict[str, FactState]:
        out: dict[str, FactState] = {}
        rows = self.db.scalars(
            select(FactRecord).where(FactRecord.case_id == case.id).order_by(FactRecord.id)
        )
        for r in rows:
            if r.status == "RETRACTED":
                out.pop(r.fact, None)
            else:
                out[r.fact] = FactState(
                    r.value, r.status, r.source_type, r.at, r.turn_id, r.source_ref, r.quote
                )
        return out

    def commit(self) -> None:
        try:
            self.db.commit()
        except StaleDataError:
            self.db.rollback()
            raise ApiError(
                409, "CONCURRENT_UPDATE", "다른 요청이 이 건을 먼저 갱신했습니다"
            ) from None

    def touch(self, case: Case) -> None:
        case.updated_at = now()

    def writable(self, case: Case) -> None:
        if case.status == "CODE_CONFIRMED":
            raise ApiError(
                409,
                "CASE_NOT_DIAGNOSABLE",
                "확정된 건입니다. 다시 열기(reopen) 후 진행해 주세요",
                {"case_status": case.status},
            )
        if case.kb_version != self.kb.version:
            raise ApiError(
                409,
                "KB_CHANGED",
                "규칙이 갱신됐습니다. rebase 후 진행해 주세요",
                {"session_kb_version": case.kb_version, "current_kb_version": self.kb.version},
            )

    def record(
        self,
        case: Case,
        path: str,
        value: Any,
        source: str,
        turn_id: str | None,
        source_ref: str | None = None,
        quote: str | None = None,
    ):
        if value == "retract":
            status, stored = "RETRACTED", None
        elif value == "unknown":
            status, stored = "DECLARED_UNKNOWN", None
        else:
            status, stored = ("EVIDENCED" if source == "DOCUMENT" else "CLAIMED"), value
        self.db.add(
            FactRecord(
                case_id=case.id,
                fact=path,
                value=stored,
                status=status,
                source_type=source,
                source_ref=source_ref,
                quote=quote,
                turn_id=turn_id,
            )
        )
        if path in self.company_facts and source in ("UTTERANCE", "SCREENING"):
            self.remember(case, path, stored if status == "CLAIMED" else None)

    def remember(self, case: Case, path: str, value: Any) -> None:
        row = self.db.scalar(
            select(CompanyFact).where(
                CompanyFact.company_id == case.company_id, CompanyFact.fact == path
            )
        )
        if value is None:
            if row is not None:
                self.db.delete(row)
            return
        if row is None:
            row = CompanyFact(company_id=case.company_id, fact=path)
            self.db.add(row)
        row.value, row.source_case_id, row.updated_at = value, case.id, now()

    def validate_facts(self, facts: dict[str, Any]) -> dict[str, Any]:
        out, problems = {}, []
        for key, value in facts.items():
            try:
                out[key] = cat.validate(self.catalog, key, value)
            except cat.FactValueError as e:
                problems.append({"key": e.key, "value": e.value, "reason": e.reason})
        if problems:
            raise ApiError(
                422, "VALIDATION_ERROR", "사실 값 형식이 올바르지 않습니다", {"problems": problems}
            )
        return out

    def apply_confirmed(self, case: Case, facts: dict | None, turn_id: str) -> None:
        if not facts:
            return
        current = self.states(case)
        for key, value in self.validate_facts(facts).items():
            st = current.get(key)
            same = st is not None and (
                (st.status == "DECLARED_UNKNOWN" and value == "unknown") or st.value == value
            )
            if not same:
                self.record(case, key, value, "PROFILE_CONFIRMED", turn_id)

    # ---- 턴 ----------------------------------------------------------------------------------

    def step(self, case: Case, states: dict[str, FactState] | None = None) -> Step:
        states = self.states(case) if states is None else states
        return pr.compute(self.kb, states, case.expanded, case.pending)

    def turn(self, case: Case, turn_id: str, prefix: str | None = None) -> tuple[Step, dict]:
        states = self.states(case)
        step = self.step(case, states)
        if case.status != "CODE_CONFIRMED":
            waiting = step.branch in ("UNSUPPORTED", "REQUEST_EVIDENCE")
            case.status = "NEEDS_INFO" if waiting else "DIAGNOSING"
        text = pr.message(self.kb, step)
        if prefix:
            text = f"{prefix} {text}"
        final = step.branch == "FINAL_REVIEW"
        turn = {
            "turn_id": turn_id,
            "case_id": case.id,
            "branch": step.branch,
            "sub_branch": step.sub_branch,
            "message": text,
            "assist": None,
            "kb_version": self.kb.version,
            "verdict": pr.verdict_view(self.kb, step),
            "ui": {
                "question": step.question,
                "board": pr.board(
                    self.kb, step, states, case.questions_asked, self.settings.max_questions
                ),
                "result": pr.result_card(self.kb, step.next.result) if final else None,
                "can_confirm": final and case.status != "CODE_CONFIRMED",
                "suggested_replies": [],
                "requested_documents": step.requested_documents,
                "conflicts": [],
            },
        }
        return step, turn

    def log(self, case: Case, turn_id: str, role: str, text: str, **kw: Any) -> None:
        self.db.add(Message(case_id=case.id, turn_id=turn_id, role=role, text=text, **kw))

    def trace(self, case: Case, turn_id: str | None, kind: str, payload: Any, step: Step | None):
        result = None
        if step is not None:
            r = step.next.result
            result = {
                "branch": step.branch,
                "outcome": r.outcome,
                "code": r.code,
                "flags": r.flags,
                "blocking_facts": r.blocking_facts,
                "trace": r.trace,
                "question": step.question["key"] if step.question else None,
            }
        self.db.add(
            TraceEvent(
                case_id=case.id,
                turn_id=turn_id,
                kind=kind,
                payload=payload,
                result=result,
                kb_version=self.kb.version,
            )
        )

    def finish_turn(
        self, case: Case, turn_id: str, kind: str, payload: Any, prefix=None, assist=None
    ) -> dict:
        self.db.flush()
        step, turn = self.turn(case, turn_id, prefix)
        turn["assist"] = assist
        self.log(
            case,
            turn_id,
            "assistant",
            turn["message"],
            branch=step.branch,
            question_key=step.question["key"] if step.question else None,
            assist=assist,
        )
        self.trace(case, turn_id, kind, payload, step)
        self.touch(case)
        return turn

    # ---- 건 ----------------------------------------------------------------------------------

    def create_case(self, company: Company, body: dict) -> dict:
        case = Case(
            id=new_id(),
            company_id=company.id,
            memo=body.get("memo"),
            quantity=body.get("quantity"),
            unit=body.get("unit"),
            period=body.get("period"),
            kb_version=self.kb.version,
            as_of=pr.today_kst(),
            expanded=[],
            company_profile_version=body.get("company_profile_version"),
        )
        self.db.add(case)
        self.db.flush()
        turn_id = new_id()
        # 회사 정보 기억(B안): 이전 건에서 답한 사업장 사실을 미리 채운다
        remembered = self.db.scalars(
            select(CompanyFact).where(CompanyFact.company_id == company.id)
        )
        for row in remembered:
            if cat.spec(self.catalog, row.fact) is not None:
                self.record(case, row.fact, row.value, "PROFILE", turn_id)
        self.db.flush()
        self.apply_confirmed(case, body.get("confirmed_facts"), turn_id)
        prefix, assist = None, None
        if case.memo:
            self.log(case, turn_id, "user", case.memo)
            if self.llm is not None:
                # 메모도 대화 중 말과 같이 읽는다(근거 문구가 메모에 있어야 기록된다)
                prefix, _, payload, assist = self.understand(case, case.memo, turn_id)
                self.trace(case, turn_id, "UNDERSTAND", {"memo": True, **payload}, None)
        turn = self.finish_turn(
            case, turn_id, "CREATE", {"memo": case.memo}, prefix=prefix, assist=assist
        )
        self.commit()
        self.polish(case, turn)
        return {"case": self.case_out(case), "turn": turn}

    def message(self, company: Company, case_id: str, body: dict) -> dict:
        case = self.get_case(company, case_id)
        self.writable(case)
        turn_id = new_id()
        if body.get("company_profile_version"):
            case.company_profile_version = body["company_profile_version"]
        self.apply_confirmed(case, body.get("confirmed_facts"), turn_id)
        qr, text = body.get("quick_reply"), body.get("text")
        if (qr is None) == (text is None):
            raise ApiError(422, "VALIDATION_ERROR", "text와 quick_reply 중 하나만 보내 주세요")
        if text is not None:
            self.log(case, turn_id, "user", text)
            prefix, kind, payload, assist = self.understand(case, text, turn_id)
            turn = self.finish_turn(case, turn_id, kind, payload, prefix=prefix, assist=assist)
            self.commit()
            return self.polish(case, turn)
        label = self.answer(case, qr, turn_id)
        self.log(case, turn_id, "user", label, quick_reply=qr)
        kind = "RETRACT" if qr.get("kind") == "retract" else "ANSWER"
        turn = self.finish_turn(case, turn_id, kind, {"quick_reply": qr})
        self.commit()
        return self.polish(case, turn)

    def polish(self, case: Case, turn: dict) -> dict:
        """확정한 턴의 질문 문장을 쉬운 말로 다듬는다(커밋 뒤, 실패하면 고정 문장 그대로)."""
        q = turn["ui"]["question"]
        if self.llm is None or not self.settings.phrase_questions or not q:
            return turn
        if turn["branch"] != "ASK_FACT" or turn.get("sub_branch"):
            return turn
        text, call = phrase(self.llm, q, self.settings.prompt_version)
        if call is not None:
            self.trace_llm(case, turn["turn_id"], call, call.user)
        if text:
            msg = turn["message"]
            turn["message"] = msg.replace(q["text"], text) if q["text"] in msg else text
            row = self.db.scalar(
                select(Message).where(
                    Message.turn_id == turn["turn_id"], Message.role == "assistant"
                )
            )
            if row is not None:
                row.text = turn["message"]
        self.db.commit()
        return turn

    def answer(self, case: Case, qr: dict, turn_id: str) -> str:
        """버튼 답 하나를 사실 기록으로 바꾼다. 대화에 남길 라벨을 돌려준다."""
        key, kind = qr.get("key"), qr.get("kind", "value")
        if isinstance(key, str) and key.startswith(pr.CONFIRM_PREFIX):
            return self.answer_confirm(case, key[len(pr.CONFIRM_PREFIX) :], qr, turn_id)
        if kind in ("value", "unknown", "retract"):
            if cat.spec(self.catalog, key) is None:
                raise ApiError(
                    422,
                    "VALIDATION_ERROR",
                    "알 수 없는 질문입니다",
                    {"problems": [{"key": key, "reason": "카탈로그에 없는 사실"}]},
                )
            if kind == "retract":
                self.record(case, key, "retract", "UTTERANCE", turn_id)
                return f"'{cat.spec(self.catalog, key)['label']}' 답을 지웠어요"
            if kind == "value" and cat.is_document_fact(self.catalog, key):
                raise ApiError(
                    422,
                    "VALIDATION_ERROR",
                    "이 값은 서류로만 받습니다. 서류를 올려 검수해 주세요",
                    {"problems": [{"key": key, "reason": "서류로만 받는 값"}]},
                )
            value = self.validate_facts({key: "unknown" if kind == "unknown" else qr.get("value")})
            v = value[key]
            self.record(case, key, v, "UTTERANCE", turn_id)
            case.questions_asked += 1
            return cat.value_label(self.catalog, key, v)
        if kind not in ("none_all", "expand", "some"):
            raise ApiError(422, "VALIDATION_ERROR", f"알 수 없는 답 종류: {kind}")
        q = self.groups.get(key)
        if q is None:
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "알 수 없는 묶음 질문입니다",
                {"problems": [{"key": key, "reason": "문진 계획에 없는 묶음"}]},
            )
        states = self.states(case)
        step = self.step(case, states)
        if step.plan_question and step.plan_question["id"] == q["id"]:
            ask = step.next.facts
        else:
            ask = [f for f in question_facts(q) if f not in states]
        case.questions_asked += 1
        if kind == "none_all":
            for f, v in pr.group_none_values(self.kb, q, ask).items():
                self.record(case, f, v, "SCREENING", turn_id)
            return q.get("all_yes_label") or pr.NONE_ALL_LABEL
        if kind == "some":
            picked = qr.get("value")
            if (
                "all_yes_label" in q
                or not isinstance(picked, list)
                or not picked
                or not set(picked) <= set(ask)
            ):
                raise ApiError(
                    422,
                    "VALIDATION_ERROR",
                    "고른 항목이 이 묶음 질문의 항목이 아닙니다",
                    {"problems": [{"key": key, "value": picked, "reason": "묶음 항목 밖"}]},
                )
            rest = [f for f in ask if f not in picked]
            for f, v in pr.group_none_values(self.kb, q, rest).items():
                self.record(case, f, v, "SCREENING", turn_id)
            case.expanded = sorted({*case.expanded, q["id"]})  # 고른 항목만 하나씩 묻는다
            items = {i["fact"]: i["label"] for i in q["items"]}
            return "해당: " + " / ".join(items[f] for f in picked)
        if "all_yes_label" in q:
            # 모두 마친 게 아니면 항목별로 묻지 않는다: 미충족·모름은 같은 결론(고시 마목)
            for f in ask:
                self.record(case, f, "unknown", "UTTERANCE", turn_id)
            return q.get("not_all_label") or pr.EXPAND_LABEL
        case.expanded = sorted({*case.expanded, q["id"]})
        return pr.EXPAND_LABEL

    def answer_confirm(self, case: Case, fact: str, qr: dict, turn_id: str) -> str:
        """확인 카드: 예(그 값으로 기록) / 아니요(원래 질문으로) / 모름."""
        item = next((p for p in case.pending if p["fact"] == fact), None)
        if item is None:
            raise ApiError(422, "VALIDATION_ERROR", "확인할 답이 없습니다")
        case.pending = [p for p in case.pending if p["fact"] != fact]
        kind = qr.get("kind", "value")
        case.questions_asked += 1
        if kind == "expand":
            return "아니요"
        value = (
            "unknown" if kind == "unknown" else self.validate_facts({fact: qr.get("value")})[fact]
        )
        self.record(case, fact, value, "UTTERANCE", turn_id, quote=item.get("quote"))
        return cat.value_label(self.catalog, fact, value)

    def confirm(self, company: Company, case_id: str, expected: str | None) -> dict:
        case = self.get_case(company, case_id)
        if case.status == "CODE_CONFIRMED":
            raise ApiError(
                409, "ALREADY_CONFIRMED", "이미 확정된 건입니다", {"case_status": case.status}
            )
        self.writable(case)
        states = self.states(case)
        step = self.step(case, states)
        if step.branch != "FINAL_REVIEW":
            raise ApiError(
                409,
                "NOT_CONFIRMABLE",
                "아직 결론이 나지 않아 확정할 수 없습니다",
                {"branch": step.branch, "reason": step.next.result.outcome, "failure_reason": None},
            )
        r = step.next.result
        code = pr.public_code(r)
        if expected:
            want = expected.lstrip("@")
            if want != (code or r.outcome):
                raise ApiError(
                    409,
                    "CODE_MISMATCH",
                    "보낸 결론이 지금 판정과 다릅니다",
                    {"server_code": code, "server_outcome": r.outcome},
                )
        version = (
            self.db.scalar(select(func.max(Verdict.version)).where(Verdict.case_id == case.id)) or 0
        ) + 1
        started = (
            self.db.scalar(select(func.min(Message.at)).where(Message.case_id == case.id))
            or case.created_at
        )
        confirmed_at = now()
        handoff = pr.handoff(
            self.kb,
            case_id=case.id,
            version=version,
            result=r,
            states=states,
            facts=step.facts,
            started_at=started,
            confirmed_at=confirmed_at,
            as_of=case.as_of,
            profile_version=case.company_profile_version,
        )
        v = Verdict(
            case_id=case.id,
            version=version,
            outcome=r.outcome,
            code=code,
            result_type=handoff["result_type"],
            handoff=handoff,
            kb_version=self.kb.version,
            company_profile_version=case.company_profile_version,
            confirmed_at=confirmed_at,
        )
        self.db.add(v)
        case.status = "CODE_CONFIRMED"
        self.touch(case)
        self.trace(case, None, "CONFIRM", {"expected_code": expected, "version": version}, step)
        self.db.flush()
        frozen = 0
        for t in self.db.scalars(
            select(TraceEvent).where(TraceEvent.case_id == case.id, TraceEvent.immutable.is_(False))
        ):
            t.immutable = True
            frozen += 1
        self.commit()
        return {
            "case": self.case_out(case),
            "verdict": self.verdict_out(v),
            "handoff": handoff,
            "frozen_trace_rows": frozen,
        }

    def reopen(self, company: Company, case_id: str, reason: str | None) -> dict:
        case = self.get_case(company, case_id)
        if case.status != "CODE_CONFIRMED":
            raise ApiError(
                409, "NOT_REOPENABLE", "확정되지 않은 건입니다", {"case_status": case.status}
            )
        current = self.current_verdict(case)
        if current is not None:
            current.reopened_at, current.reopen_reason, current.superseded = now(), reason, True
        case.status = "DIAGNOSING"
        turn_id = new_id()
        self.trace(case, turn_id, "REOPEN", {"reason": reason}, None)
        if case.kb_version != self.kb.version:
            self.trace(
                case, turn_id, "REBASE", {"from": case.kb_version, "to": self.kb.version}, None
            )
            case.kb_version = self.kb.version
        turn = self.finish_turn(case, turn_id, "REOPEN", {"reason": reason})
        self.commit()
        return {
            "case": self.case_out(case),
            "superseded_verdict": self.verdict_out(current) if current else None,
            "turn": turn,
        }

    def rebase(self, company: Company, case_id: str) -> dict:
        case = self.get_case(company, case_id)
        if case.status == "CODE_CONFIRMED":
            raise ApiError(
                409,
                "CASE_NOT_DIAGNOSABLE",
                "확정된 건은 다시 열기(reopen)로 맞춥니다",
                {"case_status": case.status},
            )
        payload = {"from_kb_version": case.kb_version, "to_kb_version": self.kb.version}
        case.kb_version = self.kb.version
        turn = self.finish_turn(case, new_id(), "REBASE", payload)
        self.commit()
        return turn

    # ---- 읽기 --------------------------------------------------------------------------------

    def current_verdict(self, case: Case) -> Verdict | None:
        return self.db.scalar(
            select(Verdict)
            .where(Verdict.case_id == case.id, Verdict.superseded.is_(False))
            .order_by(Verdict.version.desc())
        )

    def verdict_out(self, v: Verdict) -> dict:
        return {
            "version": v.version,
            "outcome": v.outcome,
            "code": v.code,
            "result_type": v.result_type,
            "kb_version": v.kb_version,
            "company_profile_version": v.company_profile_version,
            "confirmed_at": pr.iso(v.confirmed_at),
            "reopened_at": pr.iso(v.reopened_at),
            "reopen_reason": v.reopen_reason,
            "superseded": v.superseded,
            "handoff": v.handoff,
        }

    def case_out(self, case: Case) -> dict:
        states = self.states(case)
        material = states.get("material")
        verdict = self.current_verdict(case) if case.status == "CODE_CONFIRMED" else None
        memo_line = (case.memo or "").split("\n")[0].strip()[:30]
        title = (
            cat.value_label(self.catalog, "material", material.value)
            if material and material.status == "CLAIMED"
            else memo_line or "새 폐기물"
        )
        result_label = None
        next_action = {"DIAGNOSING": "문진 이어 하기", "NEEDS_INFO": "모름 답 고치기"}.get(
            case.status, ""
        )
        if verdict is not None:
            h = verdict.handoff
            result_label = (
                f"{h['waste_code']} {h['waste_name']}"
                if h.get("waste_code")
                else self.kb.outcomes["outcomes"].get(verdict.outcome, {}).get("conclusion")
            )
            next_action = NEXT_ACTION.get((h.get("route_guidance") or {}).get("action"), "")
        return {
            "id": case.id,
            "status": case.status,
            "memo": case.memo,
            "quantity": case.quantity,
            "unit": case.unit,
            "period": case.period,
            "as_of": case.as_of,
            "kb_version": case.kb_version,
            "kb_changed": case.kb_version != self.kb.version,
            "created_at": pr.iso(case.created_at),
            "updated_at": pr.iso(case.updated_at),
            "summary": {
                "title": title,
                "code": verdict.code if verdict else None,
                "outcome": verdict.outcome if verdict else None,
                "result_label": result_label,
                "status_label": STATUS_LABEL.get(case.status, case.status),
                "next_action": next_action,
            },
        }

    def list_cases(self, company: Company, status: str | None, page: int, size: int) -> dict:
        q = select(Case).where(Case.company_id == company.id)
        if status:
            q = q.where(Case.status == status)
        total = self.db.scalar(select(func.count()).select_from(q.subquery())) or 0
        rows = self.db.scalars(
            q.order_by(Case.updated_at.desc(), Case.id).offset((page - 1) * size).limit(size)
        )
        return {
            "items": [self.case_out(c) for c in rows],
            "pagingInfo": {
                "currentPageNumber": page,
                "pageSize": size,
                "totalCount": total,
                "totalPages": math.ceil(total / size) if total else 0,
            },
        }

    def conversation(self, case: Case) -> list[dict]:
        rows = self.db.scalars(
            select(Message).where(Message.case_id == case.id).order_by(Message.id)
        )
        out = []
        for m in rows:
            row = {"turn_id": m.turn_id, "role": m.role, "text": m.text, "at": pr.iso(m.at)}
            if m.role == "user":
                row["quick_reply"] = m.quick_reply
                if m.document_id:
                    row["document_id"] = m.document_id
            else:
                row |= {"branch": m.branch, "question_key": m.question_key, "assist": m.assist}
            out.append(row)
        return out

    def detail(self, company: Company, case_id: str) -> dict:
        case = self.get_case(company, case_id)
        last = self.db.scalar(
            select(Message.turn_id)
            .where(Message.case_id == case.id, Message.role == "assistant")
            .order_by(Message.id.desc())
        )
        _, latest = self.turn(case, last or new_id())
        self.db.rollback()  # 읽기 전용: turn()이 바꾼 상태 표시를 저장하지 않는다
        verdicts = self.db.scalars(
            select(Verdict).where(Verdict.case_id == case.id).order_by(Verdict.version)
        ).all()
        current = next((v for v in reversed(verdicts) if not v.superseded), None)
        current_out = self.verdict_out(current) if current else None
        return {
            "case": self.case_out(case),
            "latest_turn": latest,
            "conversation": self.conversation(case),
            "verdicts": [self.verdict_out(v) for v in verdicts],
            "current_verdict": current_out,
            "documents": self.documents_out(case),
            "handoff": current.handoff if current else None,
            "recycling": (current.handoff or {}).get("recycling") if current else None,
        }

    def trace_out(self, company: Company, case_id: str) -> dict:
        case = self.get_case(company, case_id)
        facts = self.db.scalars(
            select(FactRecord).where(FactRecord.case_id == case.id).order_by(FactRecord.id)
        )
        events = self.db.scalars(
            select(TraceEvent).where(TraceEvent.case_id == case.id).order_by(TraceEvent.id)
        )
        verdicts = self.db.scalars(
            select(Verdict).where(Verdict.case_id == case.id).order_by(Verdict.version)
        )
        return {
            "case_id": case.id,
            "kb_version": case.kb_version,
            "facts": [
                {
                    "fact": f.fact,
                    "value": f.value,
                    "status": f.status,
                    "source_type": f.source_type,
                    "turn_id": f.turn_id,
                    "at": pr.iso(f.at),
                }
                for f in facts
            ],
            "events": [
                {
                    "kind": e.kind,
                    "turn_id": e.turn_id,
                    "payload": e.payload,
                    "result": e.result,
                    "kb_version": e.kb_version,
                    "immutable": e.immutable,
                    "at": pr.iso(e.at),
                }
                for e in events
            ],
            "verdicts": [self.verdict_out(v) for v in verdicts],
        }

    # ---- 기업 데이터 삭제 ----------------------------------------------------------------------

    @staticmethod
    def company_hash(external_id: str) -> str:
        return hashlib.sha256(external_id.encode()).hexdigest()

    def deletion_out(self, log: DeletionLog) -> dict:
        return {
            "company_hash": log.company_hash,
            "status": log.status,
            "counts": log.counts,
            "attempts": log.attempts,
            "error": log.error,
            "started_at": pr.iso(log.started_at),
            "finished_at": pr.iso(log.finished_at),
        }

    def deletion(self, external_id: str) -> dict:
        log = self.db.get(DeletionLog, self.company_hash(external_id))
        if log is None:
            raise ApiError(404, "DELETION_NOT_FOUND", "삭제 이력이 없습니다")
        return self.deletion_out(log)

    def delete_company(self, external_id: str) -> dict:
        h = self.company_hash(external_id)
        log = self.db.get(DeletionLog, h)
        if log is not None and log.status == "DONE":
            return self.deletion_out(log)
        attempts = (log.attempts if log else 0) + 1
        started = log.started_at if log else now()
        try:
            counts = self._delete_rows(external_id)
            log = self.db.get(DeletionLog, h) or DeletionLog(company_hash=h, started_at=started)
            log.status, log.counts, log.attempts, log.error = "DONE", counts, attempts, None
            log.finished_at = now()
            self.db.add(log)
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            log = self.db.get(DeletionLog, h) or DeletionLog(company_hash=h, started_at=started)
            log.status, log.attempts, log.error = "FAILED", attempts, type(exc).__name__
            log.counts = log.counts or {}
            self.db.add(log)
            self.db.commit()
            raise ApiError(
                500, "DELETION_FAILED", "기업 데이터 삭제에 실패했습니다", {"attempts": attempts}
            ) from None
        return self.deletion_out(log)

    def _delete_rows(self, external_id: str) -> dict[str, int]:
        company = self.db.scalar(select(Company).where(Company.external_id == external_id))
        names = [
            "trace_events",
            "fact_records",
            "messages",
            "verdicts",
            "document_values",
            "documents",
            "company_facts",
            "cases",
            "companies",
        ]
        if company is None:
            return dict.fromkeys(names, 0)
        case_ids = select(Case.id).where(Case.company_id == company.id)
        self.db.info["allow_immutable_delete"] = True
        try:
            counts = {}
            for name, model in (
                ("trace_events", TraceEvent),
                ("fact_records", FactRecord),
                ("messages", Message),
                ("verdicts", Verdict),
                ("document_values", DocumentValue),
                ("documents", Document),
            ):
                res = self.db.execute(delete(model).where(model.case_id.in_(case_ids)))
                counts[name] = res.rowcount or 0
            res = self.db.execute(delete(CompanyFact).where(CompanyFact.company_id == company.id))
            counts["company_facts"] = res.rowcount or 0
            res = self.db.execute(delete(Case).where(Case.company_id == company.id))
            counts["cases"] = res.rowcount or 0
            res = self.db.execute(delete(Company).where(Company.id == company.id))
            counts["companies"] = res.rowcount or 0
        finally:
            self.db.info.pop("allow_immutable_delete", None)
        return counts
