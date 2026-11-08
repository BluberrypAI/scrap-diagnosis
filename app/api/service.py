"""건·문진 서비스. 라우터(routes.py)는 HTTP만 다루고, 상태 전이·영속화는 여기서 한다.

상태 전이
- 문진 한 턴: RouteDecision.next_status 그대로 (ASK/RESOLVE/FINAL_REVIEW → DIAGNOSING,
  REQUEST_EVIDENCE/UNSUPPORTED → NEEDS_INFO). FINAL_REVIEW도 확정 전까지는 DIAGNOSING이다.
- confirm: 서버가 다시 평가해 확정 가능할 때만 → CODE_CONFIRMED (판정 버전 고정, Trace 불변)
- reopen: CODE_CONFIRMED에서만 → DIAGNOSING (이전 판정은 superseded로 보존)

코드 없는 결론(폐기물 아님 등, result_type NO_CODE)도 규칙 엔진이 낸 결론이라 확정할 수 있고,
건 상태는 분류번호가 있는 결론과 같은 CODE_CONFIRMED다(docs/handoff-contract.md).
확정할 때 경로추천 AI 인계 객체(diagnosis-handoff-v1)를 만들어 판정 버전에 저장한다.

시각: 모두 UTC로 저장한다. 법 기준일 as_of는 대화 시작 시각(started_at)의 Asia/Seoul 날짜이고
reopen해도 바꾸지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.extractor import extract
from app.agent.orchestrator import DiagnosisSession, QuickReply
from app.agent.router import Branch
from app.api.deps import KBInfo, LLMs
from app.api.documents import extract_text
from app.config import Settings
from app.domain.case import DIAGNOSABLE, CaseStatus, status_after_turn
from app.domain.clock import seoul_date
from app.domain.facts import FactStatus
from app.domain.handoff import RESULT_NO_CODE, build_handoff, result_type_of
from app.domain.verdict import TurnResponse, build_verdict
from app.persistence.models import (
    Company,
    DiagnosisSessionRecord,
    Document,
    FactRecord,
    TraceRecord,
    VerdictRecord,
    WasteCase,
    new_id,
    utcnow,
)
from app.persistence.repository import LoadedSession, SessionRepository, row_to_fact
from app.rules.answers import AnswerError, fact_answer
from app.rules.model import KnowledgeBase


class ServiceError(Exception):
    def __init__(self, status: int, message: str, **extra: Any):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


class CaseService:
    def __init__(
        self,
        db: Session,
        kb: KnowledgeBase,
        kb_info: KBInfo,
        llms: LLMs,
        settings: Settings,
        today: date | None,
        company: Company,
    ):
        self.db = db
        self.kb = kb
        self.kb_info = kb_info
        self.llms = llms
        self.settings = settings
        self.today = today  # 고정한 법 기준일(테스트). None이면 대화 시작 시각의 서울 날짜
        self.company = company
        self.repo = SessionRepository(
            db, kb, extractor_llm=llms.extractor, responder_llm=llms.responder
        )

    # ---- 조회 ----------------------------------------------------------------------------

    def get_case(self, case_id: str) -> WasteCase:
        case = self.db.get(WasteCase, case_id)
        if case is None or case.company_id != self.company.id:
            raise ServiceError(404, "건을 찾을 수 없습니다")  # 다른 기업의 건도 404
        return case

    def list_cases(self, status: CaseStatus | None) -> list[WasteCase]:
        q = select(WasteCase).where(WasteCase.company_id == self.company.id)
        if status is not None:
            q = q.where(WasteCase.status == status.value)
        return list(self.db.scalars(q.order_by(WasteCase.updated_at.desc())).all())

    def session_record(self, case: WasteCase) -> DiagnosisSessionRecord:
        rec = self.repo.latest_for_case(case.id)
        if rec is None:
            raise ServiceError(409, "문진 세션이 없습니다")
        return rec

    def session_id_of(self, case: WasteCase) -> str | None:
        rec = self.repo.latest_for_case(case.id)
        return rec.id if rec else None

    def latest_turn(self, case: WasteCase) -> TurnResponse | None:
        sid = self.session_id_of(case)
        row = self.repo.latest_turn(sid) if sid else None
        if row is None or not row.payload.get("response"):
            return None
        return TurnResponse.model_validate(row.payload["response"])

    def documents(self, case: WasteCase) -> list[Document]:
        return list(
            self.db.scalars(
                select(Document).where(Document.case_id == case.id).order_by(Document.created_at)
            ).all()
        )

    # ---- 생성 ----------------------------------------------------------------------------

    def create_case(
        self, *, memo: str | None, quantity: float | None, unit: str | None, period: str | None
    ) -> tuple[WasteCase, TurnResponse]:
        case = WasteCase(
            id=new_id(),
            company_id=self.company.id,
            memo=memo,
            quantity=quantity,
            unit=unit,
            period=period,
            status=CaseStatus.DIAGNOSING.value,
        )
        self.db.add(case)
        self.db.flush()
        started_at = utcnow()  # 대화 시작. as_of는 이 시각의 Asia/Seoul 날짜
        s = DiagnosisSession(
            self.kb,
            extractor_llm=self.llms.extractor,
            responder_llm=self.llms.responder,
            case_id=case.id,
            as_of=self.today or seoul_date(started_at),
            max_questions=self.settings.max_questions,
            prompt_version=self.settings.prompt_version,
        )
        self._seed_profile(s)
        resp = s.start(memo.strip() if memo and memo.strip() else None)
        ls = self.repo.create(
            case,
            s,
            kb_dir=self.kb_info.kb_dir,
            kb_version=self.kb_info.version,
            table_versions=self.kb_info.table_versions,
            started_at=started_at,
        )
        self._finish_turn(case, ls)
        return case, resp

    def _seed_profile(self, s: DiagnosisSession) -> None:
        """기업 프로필의 사이트 사실(PROFILE). 카탈로그에 없거나 값이 맞지 않는 키는 건너뛴다."""
        facts = (self.company.profile or {}).get("facts") or {}
        for k, v in facts.items():
            try:
                s.seed({k: v})
            except AnswerError:
                continue

    # ---- 문진 ----------------------------------------------------------------------------

    def _open_session(self, case: WasteCase) -> LoadedSession:
        if CaseStatus(case.status) not in DIAGNOSABLE:
            raise ServiceError(
                409,
                f"{case.status} 상태에서는 문진할 수 없습니다(확정 건은 reopen 후 진행)",
                case_status=case.status,
            )
        return self.repo.load(self.session_record(case))

    def _finish_turn(self, case: WasteCase, ls: LoadedSession) -> None:
        now = utcnow()
        case.status = status_after_turn(ls.session.case_status).value
        case.updated_at = now
        ls.record.last_activity_at = now
        self.repo.save(ls)

    def message(
        self, case: WasteCase, *, text: str | None, quick_reply: QuickReply | None
    ) -> TurnResponse:
        ls = self._open_session(case)
        resp = ls.session.handle(text=text, quick_reply=quick_reply)
        self._finish_turn(case, ls)
        return resp

    # ---- 문서 ----------------------------------------------------------------------------

    def upload_document(
        self,
        case: WasteCase,
        *,
        filename: str,
        content_type: str | None,
        data: bytes,
        manual_facts: str | None,
    ) -> tuple[Document, TurnResponse]:
        ls = self._open_session(case)
        s = ls.session
        manual = self._parse_manual_facts(manual_facts) if manual_facts else None
        text = extract_text(filename, content_type, data)
        doc = Document(
            id=new_id(),
            case_id=case.id,
            filename=filename,
            content_type=content_type,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            extracted_text=text,
        )
        self.db.add(doc)

        calls: list[dict] = []
        rejected: list[dict] = []
        if manual is not None:
            method = "manual"
            facts = [
                fact_answer(self.kb, k, v, source_ref=doc.id).model_copy(
                    update={"quote": None, "note": "문서 업로드 시 직접 입력"}
                )
                for k, v in manual.items()
            ]
        elif self.llms.extractor is not None and text.strip():
            method = "llm"
            ex, llm_calls = extract(
                self.llms.extractor,
                self.kb,
                text[: self.settings.document_text_limit],
                effective=s.store.effective(),
                last_question=s.last_question,
                recent=[],
                message_id=doc.id,
                prompt_version=s.prompt_version,
            )
            calls = [c.model_dump(mode="json") for c in llm_calls]
            rejected = list(ex.rejected)
            facts = []
            for f in ex.facts:
                # 문서에서는 값이 확인된 사실만 증빙으로 받는다('모름'·미정량 진술은 버림)
                if f.status == FactStatus.CLAIMED and f.value is not None:
                    facts.append(f)
                else:
                    rejected.append({"key": f.key, "reason": "값이 없는 사실(문서 증빙 아님)"})
        else:
            method = "none"
            facts = []

        evidenced = [
            f.model_copy(
                update={
                    "status": FactStatus.EVIDENCED,
                    "source_type": "DOCUMENT",
                    "source_ref": doc.id,
                    "recorded_at": utcnow(),
                }
            )
            for f in facts
        ]
        doc.extracted_facts = {
            "method": method,
            "accepted": {f.key: f.model_dump(mode="json")["value"] for f in evidenced},
            "rejected": rejected,
        }
        self.repo.add_trace(
            ls.record,
            "DOCUMENT",
            doc.id[:12],
            {
                "document_id": doc.id,
                "filename": filename,
                "sha256": doc.sha256,
                "method": method,
                "text_chars": len(text),
                "llm_calls": calls,
                "appended_facts": [f.model_dump(mode="json") for f in evidenced],
                "rejected": rejected,
            },
        )
        for f in evidenced:
            s.store.append(f)
        if evidenced:
            s.state.evidence_refused = False
        s.messages.append({"role": "document", "id": doc.id, "text": filename, "memo": False})
        resp = s.handle()
        self._finish_turn(case, ls)
        return doc, resp

    def _parse_manual_facts(self, raw: str) -> dict[str, Any]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ServiceError(422, f"facts는 JSON 객체여야 합니다: {exc}") from exc
        if not isinstance(data, dict):
            raise ServiceError(422, "facts는 JSON 객체여야 합니다")
        problems = []
        for k, v in data.items():
            if k not in self.kb.catalog:
                problems.append({"key": k, "reason": "카탈로그에 없는 사실 키"})
                continue
            try:
                fact_answer(self.kb, k, v)
            except AnswerError as exc:
                problems.append({"key": k, "reason": str(exc)})
        if problems:
            raise ServiceError(422, "문서 사실 값이 올바르지 않습니다", problems=problems)
        return data

    # ---- 확정·재개 -----------------------------------------------------------------------

    def confirm(self, case: WasteCase, expected_code: str | None) -> tuple[VerdictRecord, int]:
        """서버가 다시 평가해 규칙 엔진이 결론을 낸 경우(FINAL_REVIEW)만 확정한다.

        expected_code(선택): 클라이언트가 화면에서 본 결론. 분류번호가 있는 판정이면 그 번호,
        코드 없는 결론이면 사유(outcome, 예: NOT_WASTE. '@NOT_WASTE'도 받음)와 같아야 한다.
        다르면 409이며 server_code·server_outcome을 돌려준다. 보내지 않으면 비교하지 않는다.
        """
        if case.status == CaseStatus.CODE_CONFIRMED.value:
            raise ServiceError(409, "이미 확정된 건입니다", case_status=case.status)
        ls = self._open_session(case)
        s = ls.session
        step = s.peek()  # 클라이언트를 믿지 않고 서버가 지금 사실로 다시 평가한다
        ev, d = step.evaluation, step.decision
        if not (ev.can_confirm and d.branch == Branch.FINAL_REVIEW) or ev.decided is None:
            raise ServiceError(
                409,
                "아직 확정할 수 없습니다",
                branch=d.branch.value,
                reason=d.reason,
                failure_reason=d.failure_reason,
            )
        decided = ev.decided
        result_type = result_type_of(decided)
        outcome = decided.outcome if result_type == RESULT_NO_CODE else None
        seen = expected_code
        if seen is not None and not _expected_matches(seen, decided.code, outcome):
            raise ServiceError(
                409,
                "화면의 결론과 서버 판정이 다릅니다",
                server_code=decided.code,
                server_outcome=outcome,
            )
        last = self.repo.latest_turn(ls.record.id)
        now = utcnow()
        version = self.repo.next_verdict_version(case.id)
        handoff = build_handoff(
            self.kb,
            case_id=case.id,
            verdict_version=version,
            decided=decided,
            rule=s.rule_index.get(decided.rule_ids[0]),
            effective=step.effective,
            table_id=ev.table_id,
            table_version=ev.table_version,
            kb_version=ls.record.kb_version,
            diagnosis_started_at=ls.record.started_at,
            confirmed_at=now,
            as_of=s.as_of,
        ).model_dump(mode="json")
        verdict = VerdictRecord(
            case_id=case.id,
            session_id=ls.record.id,
            version=version,
            result_type=result_type,
            code=decided.code,
            name=decided.name if decided.code is not None else None,
            category=decided.category,
            outcome=outcome,
            rule_ids=list(decided.rule_ids),
            table_id=ev.table_id,
            table_version=ev.table_version,
            kb_version=ls.record.kb_version,
            as_of=s.as_of,
            facts_snapshot={k: f.model_dump(mode="json") for k, f in step.effective.items()},
            verdict=build_verdict(self.kb, step, s.rule_index).model_dump(mode="json"),
            trace_turn_id=last.turn_id if last else None,
            handoff=handoff,
            confirmed_at=now,
        )
        self.db.add(verdict)
        self.repo.add_trace(
            ls.record,
            "CONFIRM",
            new_id()[:12],
            {
                "verdict_version": verdict.version,
                "result_type": result_type,
                "code": verdict.code,
                "outcome": outcome,
                "rule_ids": verdict.rule_ids,
                "table_id": verdict.table_id,
                "table_version": verdict.table_version,
                "kb_version": verdict.kb_version,
                "as_of": s.as_of.isoformat(),
                "branch_reason": d.reason,
                "facts_snapshot": verdict.facts_snapshot,
                "route_action": handoff["route_guidance"]["action"],
            },
        )
        s.case_status = CaseStatus.CODE_CONFIRMED.value
        case.status = CaseStatus.CODE_CONFIRMED.value
        case.updated_at = now
        ls.record.last_activity_at = now
        self.repo.save(ls)
        frozen = self.repo.freeze_traces(ls.record)
        return verdict, frozen

    def reopen(
        self, case: WasteCase, reason: str | None
    ) -> tuple[VerdictRecord | None, TurnResponse]:
        if case.status != CaseStatus.CODE_CONFIRMED.value:
            raise ServiceError(409, "확정된 건만 다시 열 수 있습니다", case_status=case.status)
        current = self.repo.current_verdict(case.id)
        if current is not None:
            now = utcnow()
            current.superseded_at = now
            current.reopened_at = now
            current.reopen_reason = reason
        rec = self.session_record(case)
        ls = self.repo.load(rec)
        self.repo.add_trace(
            rec,
            "REOPEN",
            new_id()[:12],
            {"superseded_version": current.version if current else None, "reason": reason},
        )
        ls.session.case_status = CaseStatus.DIAGNOSING.value
        # 같은 사실·같은 법 기준일(as_of)로 문진을 이어 간다. as_of는 바꾸지 않는다.
        resp = ls.session.handle()
        self._finish_turn(case, ls)
        return current, resp

    # ---- Trace ---------------------------------------------------------------------------

    def trace_sessions(
        self, case: WasteCase
    ) -> list[tuple[DiagnosisSessionRecord, list[TraceRecord]]]:
        out = []
        for rec in case.sessions:
            out.append((rec, self.repo.traces(rec.id)))
        return out

    def fact_rows(self, session_id: str) -> list[dict]:
        rows = self.db.scalars(
            select(FactRecord).where(FactRecord.session_id == session_id).order_by(FactRecord.seq)
        ).all()
        return [{"seq": r.seq, **row_to_fact(r).model_dump(mode="json")} for r in rows]


def _expected_matches(expected: str, code: str | None, outcome: str | None) -> bool:
    """클라이언트가 본 결론과 서버 판정이 같은가. 코드 없는 결론은 사유(또는 '@사유')로 비교한다."""
    if code is not None:
        return expected == code
    return expected.removeprefix("@") == outcome
