"""건·문진 서비스. 라우터(routes.py)는 HTTP만 다루고, 상태 전이·영속화는 여기서 한다.

상태 전이
- 문진 한 턴: RouteDecision.next_status 그대로 (ASK/RESOLVE/FINAL_REVIEW → DIAGNOSING,
  REQUEST_EVIDENCE/UNSUPPORTED → NEEDS_INFO). FINAL_REVIEW도 확정 전까지는 DIAGNOSING이다.
- confirm: 서버가 다시 평가해 확정 가능할 때만 → CODE_CONFIRMED (판정 버전 고정, Trace 불변)
- reopen: CODE_CONFIRMED에서만 → DIAGNOSING (이전 판정은 superseded로 보존)
- 서류: 업로드 값은 후보(document_values)일 뿐이고, 검수 완료 값 적용(apply)만 EVIDENCED가 된다.
  효력 해제(revoke)·파일 교체(새 버전)는 그 서류의 증빙을 평가에서 뺀다(이력은 보존).
- 규칙 버전: 세션의 kb_version이 지금 규칙과 다르면 쓰기는 409 KB_CHANGED, rebase로 맞춘다.

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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent import templates
from app.agent.orchestrator import DiagnosisSession, QuickReply
from app.agent.router import Branch
from app.api.deps import KBInfo, LLMs
from app.api.documents import extract_text
from app.api.profile import profile_facts
from app.api.schemas import ApplyValueIn
from app.config import Settings
from app.domain.case import DIAGNOSABLE, CaseStatus, status_after_turn
from app.domain.clock import seoul_date
from app.domain.facts import (
    REVOKE_NOTE,
    Fact,
    FactStatus,
    active_facts,
    document_source_ref,
    revoke_fact,
    source_matches,
)
from app.domain.handoff import RESULT_NO_CODE, build_handoff, result_type_of
from app.domain.ranges import NumRange
from app.domain.verdict import TurnResponse, build_verdict, value_label
from app.persistence.models import (
    Company,
    DiagnosisSessionRecord,
    Document,
    DocumentValue,
    FactRecord,
    TraceRecord,
    VerdictRecord,
    WasteCase,
    new_id,
    utcnow,
)
from app.persistence.repository import KBChanged, LoadedSession, SessionRepository, row_to_fact
from app.rules.answers import AnswerError, check_document_value
from app.rules.model import KnowledgeBase

# 서류 값 상태(document_values.status)
VALUE_UNVERIFIED = "UNVERIFIED"  # 검수 대기 후보(판정에 안 씀)
VALUE_APPLIED = "APPLIED"  # 검수 완료 → EVIDENCED
VALUE_REJECTED = "REJECTED"  # 검수에서 버림
VALUE_REVOKED = "REVOKED"  # 서류 교체·검수 취소로 효력 해제


def _json_value(v: Any) -> Any:
    return v.model_dump(mode="json") if isinstance(v, NumRange) else v


class ServiceError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None, **extra: Any):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
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
            db,
            kb,
            extractor_llm=llms.extractor,
            responder_llm=llms.responder,
            kb_version=kb_info.version,
        )

    # ---- 조회 ----------------------------------------------------------------------------

    def get_case(self, case_id: str) -> WasteCase:
        case = self.db.get(WasteCase, case_id)
        if case is None or case.company_id != self.company.id:
            raise ServiceError(
                404, "건을 찾을 수 없습니다", "CASE_NOT_FOUND"
            )  # 다른 기업의 건도 404
        return case

    def list_cases(
        self, status: CaseStatus | None, *, page: int | None = None, size: int | None = None
    ) -> tuple[list[WasteCase], int]:
        """(건 목록, 전체 건수). page·size를 주면 그 쪽만 자른다(1부터)."""
        cond = [WasteCase.company_id == self.company.id]
        if status is not None:
            cond.append(WasteCase.status == status.value)
        total = self.db.scalar(select(func.count()).select_from(WasteCase).where(*cond)) or 0
        q = select(WasteCase).where(*cond).order_by(WasteCase.updated_at.desc(), WasteCase.id)
        if page is not None and size is not None:
            q = q.offset((page - 1) * size).limit(size)
        return list(self.db.scalars(q).all()), total

    def session_record(self, case: WasteCase) -> DiagnosisSessionRecord:
        rec = self.repo.latest_for_case(case.id)
        if rec is None:
            raise ServiceError(409, "문진 세션이 없습니다", "CASE_NOT_DIAGNOSABLE")
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

    def conversation(self, case: WasteCase) -> list[dict[str, Any]]:
        """세션 state에 쌓인 대화 기록을 화면용으로 바꾼다(docs/ui/ui-contract.md 2절)."""
        out: list[dict[str, Any]] = []
        for rec in sorted(case.sessions, key=lambda r: r.created_at):
            for m in (rec.state or {}).get("messages", []):
                role = m.get("role")
                item: dict[str, Any] = {"turn_id": m.get("id", ""), "at": m.get("at")}
                if role == "assistant":
                    item.update(
                        role="assistant",
                        text=m.get("text", ""),
                        branch=m.get("branch"),
                        question_key=m.get("question_key"),
                    )
                elif role == "document":
                    item.update(
                        role="user",
                        text=templates.DOCUMENT_MESSAGE.format(filename=m.get("text", "")),
                        document_id=m.get("id"),
                    )
                else:
                    item.update(
                        role="user",
                        text=m.get("text", ""),
                        quick_reply=m.get("quick_reply"),
                        memo=bool(m.get("memo")),
                    )
                out.append(item)
        return out

    def summary(self, case: WasteCase, rec: DiagnosisSessionRecord | None = None) -> dict[str, Any]:
        """건 목록 카드(docs/ui/ui-contract.md 3절). 마지막 턴 Trace와 현재 판정에서 만든다."""
        rec = rec if rec is not None else self.repo.latest_for_case(case.id)
        row = self.repo.latest_turn(rec.id) if rec is not None else None
        payload = row.payload if row is not None else {}
        resp = payload.get("response") or {}
        current = self.repo.current_verdict(case.id)

        title = None
        material = (payload.get("effective_facts") or {}).get("material") or {}
        if material.get("value") is not None and material.get("status") in ("CLAIMED", "EVIDENCED"):
            title = value_label(self.kb, "material", material["value"])
        if not title and case.memo and case.memo.strip():
            title = case.memo.strip().splitlines()[0][:30]

        code = outcome = name = None
        if current is not None:
            code, outcome, name = current.code, current.outcome, current.name
        elif resp.get("branch") == Branch.FINAL_REVIEW.value:
            v = resp.get("verdict") or {}
            code, outcome, name = v.get("waste_code"), v.get("outcome"), v.get("waste_name")
        if code is not None:
            result_label = f"{code} {name or ''}".strip()
        else:
            result_label = templates.OUTCOME_LABEL.get(outcome) if outcome else None

        if case.status in templates.NEXT_ACTION_BY_STATUS:
            next_action = templates.NEXT_ACTION_BY_STATUS[case.status]
        elif case.status == CaseStatus.CODE_CONFIRMED.value and current is not None:
            action = ((current.handoff or {}).get("route_guidance") or {}).get("action")
            next_action = templates.NEXT_ACTION_BY_ROUTE.get(action or "RECOMMEND_ROUTE")
        else:
            next_action = templates.NEXT_ACTION_BY_BRANCH.get(resp.get("branch") or "")
        return {
            "title": title or templates.NEW_CASE_TITLE,
            "code": code,
            "outcome": outcome,
            "result_label": result_label,
            "status_label": templates.STATUS_LABEL.get(case.status, case.status),
            "next_action": next_action,
        }

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
        """기업 프로필의 사이트 사실(PROFILE). 카탈로그에 없거나 값이 맞지 않는 키는 건너뛴다.

        사이트 사실 = facilities에서 계산한 값 + 직접 지정한 facts(직접 지정 우선).
        """
        facts = profile_facts(self.company.profile)
        for k, v in facts.items():
            try:
                s.seed({k: v})
            except AnswerError:
                continue

    # ---- 문진 ----------------------------------------------------------------------------

    def _open_session(self, case: WasteCase, *, allow_kb_change: bool = False) -> LoadedSession:
        if CaseStatus(case.status) not in DIAGNOSABLE:
            raise ServiceError(
                409,
                f"{case.status} 상태에서는 문진할 수 없습니다(확정 건은 reopen 후 진행)",
                "CASE_NOT_DIAGNOSABLE",
                case_status=case.status,
            )
        return self._load(self.session_record(case), allow_kb_change=allow_kb_change)

    def _load(self, rec: DiagnosisSessionRecord, *, allow_kb_change: bool = False) -> LoadedSession:
        """세션 복원. 저장된 규칙 버전이 지금과 다르면 409 KB_CHANGED(rebase 후 진행)."""
        try:
            return self.repo.load(rec, allow_kb_change=allow_kb_change)
        except KBChanged as exc:
            raise ServiceError(
                409,
                "규칙 버전이 바뀌었습니다. rebase로 지금 규칙에 맞춘 뒤 진행하세요",
                "KB_CHANGED",
                session_kb_version=exc.session_kb_version,
                current_kb_version=exc.current_kb_version,
            ) from exc

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
    # 서류 값: 후보 → 검수 → 적용(docs/api/server-engine-contract.md 3절).
    # - 업로드·직접 입력 값은 후보(document_values, UNVERIFIED)로만 저장한다. 판정은 바뀌지 않는다.
    # - 서버가 검수 완료로 보낸 값만 EVIDENCED 사실로 append한다(source_ref = 문서id@v버전).
    # - 엔진은 서류 원문과 값을 대조하지 않는다. 형식만 거른다(check_document_value).
    # - 자동 읽기(OCR·AI)는 하지 않는다(document-extraction-v1 계약만 둔다). 원문은 저장만 한다.

    def get_document(self, case: WasteCase, document_id: str) -> Document:
        doc = self.db.get(Document, document_id)
        if doc is None or doc.case_id != case.id:
            raise ServiceError(404, "서류를 찾을 수 없습니다", "DOCUMENT_NOT_FOUND")
        return doc

    def document_values(self, doc: Document) -> list[DocumentValue]:
        return list(
            self.db.scalars(
                select(DocumentValue)
                .where(DocumentValue.document_id == doc.id)
                .order_by(DocumentValue.created_at, DocumentValue.id)
            ).all()
        )

    def upload_document(
        self,
        case: WasteCase,
        *,
        filename: str,
        content_type: str | None,
        data: bytes,
        manual_facts: str | None,
    ) -> tuple[Document, TurnResponse, list[DocumentValue]]:
        ls = self._open_session(case)
        manual = self._parse_manual_facts(manual_facts) if manual_facts else {}
        text = extract_text(filename, content_type, data)
        doc = Document(id=new_id(), case_id=case.id, version=1)
        self._set_file(doc, filename, content_type, data, text, manual)
        self.db.add(doc)
        values = self._store_candidates(case, ls, doc, manual)
        self._document_trace(ls, doc, text, values)
        return doc, self._document_turn(case, ls, doc, filename), values

    def replace_document(
        self,
        case: WasteCase,
        document_id: str,
        *,
        filename: str,
        content_type: str | None,
        data: bytes,
        manual_facts: str | None,
    ) -> tuple[Document, TurnResponse, list[DocumentValue]]:
        """같은 서류의 새 파일(새 버전). 이전 버전에서 적용된 값은 자동으로 효력을 해제한다."""
        ls = self._open_session(case)
        doc = self.get_document(case, document_id)
        manual = self._parse_manual_facts(manual_facts) if manual_facts else {}
        text = extract_text(filename, content_type, data)
        prev = doc.version
        # 교체 시점까지의 모든 버전(이전 표기 '문서id' 포함)을 해제한다 = 이전 파일 전부
        revoked_keys, revoked_rows = self._revoke(
            ls,
            doc,
            document_source_ref(doc.id),
            version=None,
            note=f"새 파일(v{prev + 1})로 교체",
            include_unverified=True,
        )
        doc.version = prev + 1
        doc.updated_at = utcnow()
        self._set_file(doc, filename, content_type, data, text, manual)
        values = self._store_candidates(case, ls, doc, manual)
        self._document_trace(
            ls,
            doc,
            text,
            values,
            replaced_version=prev,
            revoked_keys=revoked_keys,
            revoked_value_ids=[r.id for r in revoked_rows],
        )
        return doc, self._document_turn(case, ls, doc, filename), values

    def _set_file(
        self,
        doc: Document,
        filename: str,
        content_type: str | None,
        data: bytes,
        text: str,
        manual: dict[str, Any],
    ) -> None:
        doc.filename = filename
        doc.content_type = content_type
        doc.size = len(data)
        doc.sha256 = hashlib.sha256(data).hexdigest()
        doc.extracted_text = text
        doc.extracted_facts = {
            "method": "manual" if manual else "none",
            "candidates": {k: _json_value(v) for k, v in manual.items()},
            "accepted": {},  # 이전 호환. 업로드 값은 더 이상 바로 적용되지 않는다
        }

    def _store_candidates(
        self, case: WasteCase, ls: LoadedSession, doc: Document, manual: dict[str, Any]
    ) -> list[DocumentValue]:
        out = []
        for k, v in manual.items():
            row = DocumentValue(
                id=new_id(),
                document_id=doc.id,
                document_version=doc.version,
                case_id=case.id,
                session_id=ls.record.id,
                fact_key=k,
                value=_json_value(v),
                unit=None,
                status=VALUE_UNVERIFIED,
                note="업로드 시 직접 입력(검수 대기)",
                created_at=utcnow(),
            )
            self.db.add(row)
            out.append(row)
        return out

    def _document_trace(
        self,
        ls: LoadedSession,
        doc: Document,
        text: str,
        values: list[DocumentValue],
        **extra: Any,
    ) -> None:
        self.repo.add_trace(
            ls.record,
            "DOCUMENT",
            new_id()[:12],
            {
                "document_id": doc.id,
                "document_version": doc.version,
                "filename": doc.filename,
                "sha256": doc.sha256,
                "method": doc.extracted_facts["method"],
                "text_chars": len(text),
                "candidates": [
                    {"value_id": r.id, "fact_key": r.fact_key, "value": r.value} for r in values
                ],
                "appended_facts": [],  # 후보는 사실이 아니다(검수 후 apply로만 반영)
                **extra,
            },
        )

    def _document_turn(
        self, case: WasteCase, ls: LoadedSession, doc: Document, filename: str
    ) -> TurnResponse:
        s = ls.session
        s.messages.append(
            {
                "role": "document",
                "id": doc.id,
                "text": filename,
                "memo": False,
                "at": utcnow().isoformat(timespec="seconds"),
            }
        )
        resp = s.handle()
        self._finish_turn(case, ls)
        return resp

    def _parse_manual_facts(self, raw: str) -> dict[str, Any]:
        """업로드의 facts(JSON 객체 {사실 키: 값}). 형식이 틀린 항목이 하나라도 있으면 422."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ServiceError(
                422, f"facts는 JSON 객체여야 합니다: {exc}", "VALIDATION_ERROR"
            ) from exc
        if not isinstance(data, dict):
            raise ServiceError(422, "facts는 JSON 객체여야 합니다", "VALIDATION_ERROR")
        out: dict[str, Any] = {}
        problems = []
        for k, v in data.items():
            try:
                out[k] = check_document_value(self.kb, k, v)
            except AnswerError as exc:
                problems.append({"key": k, "value": v, "reason": str(exc)})
        if problems:
            raise ServiceError(
                422, "서류 값 형식이 올바르지 않습니다", "VALIDATION_ERROR", problems=problems
            )
        return out

    def apply_values(
        self, case: WasteCase, document_id: str, items: list[ApplyValueIn]
    ) -> tuple[TurnResponse, list[DocumentValue]]:
        """서버가 검수 완료로 보낸 값을 EVIDENCED로 적용하고 다시 평가한다."""
        ls = self._open_session(case)
        s = ls.session
        doc = self.get_document(case, document_id)
        stale = {i.document_version for i in items if i.document_version != doc.version}
        rows: dict[str, DocumentValue] = {}
        problems: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            if not item.value_id:
                continue
            row = self.db.get(DocumentValue, item.value_id)
            if row is None or row.document_id != doc.id:
                problems.append(
                    {"index": idx, "value_id": item.value_id, "reason": "이 서류의 값이 아닙니다"}
                )
            elif row.document_version != doc.version:
                stale.add(row.document_version)
            else:
                rows[item.value_id] = row
        if stale:
            raise ServiceError(
                409,
                "서류 버전이 바뀌었습니다. 최신 버전으로 다시 검수하세요",
                "DOCUMENT_VERSION_MISMATCH",
                document_id=doc.id,
                current_version=doc.version,
                sent_versions=sorted(stale),
            )
        plan: list[tuple[ApplyValueIn, DocumentValue | None, str, Any]] = []
        for idx, item in enumerate(items):
            row = rows.get(item.value_id or "")
            if item.value_id and row is None:
                continue  # 위에서 problems에 넣음
            key = item.fact_key or (row.fact_key if row else "")
            base = {"index": idx, "value_id": item.value_id, "key": key}
            if row is not None and item.fact_key and item.fact_key != row.fact_key:
                problems.append({**base, "reason": f"값 행의 사실 키는 {row.fact_key}입니다"})
                continue
            if item.reject:
                if row is None:
                    problems.append({**base, "reason": "reject에는 value_id가 필요합니다"})
                else:
                    plan.append((item, row, key, None))
                continue
            raw = item.value if "value" in item.model_fields_set or row is None else row.value
            unit = item.unit if item.unit is not None else (row.unit if row else None)
            try:
                plan.append((item, row, key, check_document_value(self.kb, key, raw, unit)))
            except AnswerError as exc:
                problems.append({**base, "value": raw, "reason": str(exc)})
        if problems:
            raise ServiceError(
                422, "서류 값 형식이 올바르지 않습니다", "VALIDATION_ERROR", problems=problems
            )

        ref = document_source_ref(doc.id, doc.version)
        now = utcnow()
        appended: list[Fact] = []
        touched: list[DocumentValue] = []
        for item, row, key, value in plan:
            if row is None:
                row = DocumentValue(
                    id=new_id(),
                    document_id=doc.id,
                    document_version=doc.version,
                    case_id=case.id,
                    session_id=ls.record.id,
                    fact_key=key,
                    created_at=now,
                )
                self.db.add(row)
            row.reviewer = item.reviewer
            row.reviewed_at = item.reviewed_at
            row.updated_at = now
            touched.append(row)
            if item.reject:
                row.status = VALUE_REJECTED
                continue
            jv = _json_value(value)
            if row.value is not None and row.value != jv:
                row.note = f"후보 값 {row.value!r}을 검수에서 {jv!r}로 고침"
            row.value = jv
            row.unit = item.unit if item.unit is not None else row.unit
            row.status = VALUE_APPLIED
            s.store.append(
                Fact(
                    key=key,
                    value=value,
                    status=FactStatus.EVIDENCED,
                    source_type="DOCUMENT",
                    source_ref=ref,
                    note=f"서류 값 검수 완료({item.reviewer})",
                )
            )
            appended.append(s.store.history[-1])
        if appended:
            s.state.evidence_refused = False
        self.repo.add_trace(
            ls.record,
            "APPLY",
            new_id()[:12],
            {
                "document_id": doc.id,
                "document_version": doc.version,
                "source_ref": ref,
                "values": [
                    {
                        "value_id": r.id,
                        "fact_key": r.fact_key,
                        "value": r.value,
                        "unit": r.unit,
                        "status": r.status,
                        "reviewer": r.reviewer,
                        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
                    }
                    for r in touched
                ],
                "appended_facts": [f.model_dump(mode="json") for f in appended],
            },
        )
        resp = s.handle()
        self._finish_turn(case, ls)
        return resp, touched

    def revoke_document(
        self, case: WasteCase, document_id: str, *, reason: str | None, version: int | None
    ) -> tuple[TurnResponse, list[DocumentValue]]:
        """서류(또는 그 버전)에서 온 증빙의 효력을 해제하고 다시 평가한다. 이력은 남긴다."""
        ls = self._open_session(case)
        doc = self.get_document(case, document_id)
        if version is not None and version > doc.version:
            raise ServiceError(
                409,
                "없는 서류 버전입니다",
                "DOCUMENT_VERSION_MISMATCH",
                document_id=doc.id,
                current_version=doc.version,
                sent_versions=[version],
            )
        ref = document_source_ref(doc.id, version)
        keys, rows = self._revoke(
            ls,
            doc,
            ref,
            version=version,
            note=f"{REVOKE_NOTE}: {reason}" if reason else REVOKE_NOTE,
            include_unverified=False,
        )
        self.repo.add_trace(
            ls.record,
            "REVOKE",
            new_id()[:12],
            {
                "document_id": doc.id,
                "document_version": version,
                "source_ref": ref,
                "reason": reason,
                "revoked_keys": keys,
                "revoked_value_ids": [r.id for r in rows],
            },
        )
        resp = ls.session.handle()
        self._finish_turn(case, ls)
        return resp, rows

    def _revoke(
        self,
        ls: LoadedSession,
        doc: Document,
        ref: str,
        *,
        version: int | None,
        note: str,
        include_unverified: bool,
    ) -> tuple[list[str], list[DocumentValue]]:
        """ref 출처의 유효한 증빙마다 해제 표시 행을 append하고 값 행을 REVOKED로 바꾼다."""
        s = ls.session
        keys = sorted(
            {
                f.key
                for f in active_facts(s.store.history)
                if f.status == FactStatus.EVIDENCED
                and f.source_type == "DOCUMENT"
                and source_matches(f.source_ref, ref)
            }
        )
        for k in keys:
            s.store.append(revoke_fact(k, ref, note=note))
        statuses = {VALUE_APPLIED, VALUE_UNVERIFIED} if include_unverified else {VALUE_APPLIED}
        now = utcnow()
        rows = [
            r
            for r in self.document_values(doc)
            if r.status in statuses and (version is None or r.document_version == version)
        ]
        for r in rows:
            r.status = VALUE_REVOKED
            r.updated_at = now
            r.note = note
        return keys, rows

    # ---- 규칙 버전 -----------------------------------------------------------------------

    def kb_changed(self, case: WasteCase) -> bool:
        return self.repo.kb_changed(self.repo.latest_for_case(case.id))

    def rebase(self, case: WasteCase) -> TurnResponse:
        """지금 규칙으로 다시 평가하고 세션의 규칙 버전을 갱신한다(Trace REBASE).

        확정된 건은 409(판정 버전은 건드리지 않는다. reopen하면 지금 규칙으로 이어 간다).
        """
        if case.status == CaseStatus.CODE_CONFIRMED.value:
            raise ServiceError(
                409,
                "확정된 건은 rebase할 수 없습니다(reopen하면 지금 규칙으로 이어 갑니다)",
                "CASE_NOT_DIAGNOSABLE",
                case_status=case.status,
            )
        ls = self._open_session(case, allow_kb_change=True)
        self._rebase_record(ls, trigger="rebase")
        resp = ls.session.handle()
        self._finish_turn(case, ls)
        return resp

    def _rebase_record(self, ls: LoadedSession, *, trigger: str) -> None:
        rec = ls.record
        self.repo.add_trace(
            rec,
            "REBASE",
            new_id()[:12],
            {
                "trigger": trigger,
                "changed": rec.kb_version != self.kb_info.version,
                "from_kb_version": rec.kb_version,
                "to_kb_version": self.kb_info.version,
                "from_kb_dir": rec.kb_dir,
                "to_kb_dir": self.kb_info.kb_dir,
                "from_table_versions": rec.table_versions,
                "to_table_versions": self.kb_info.table_versions,
            },
        )
        rec.kb_dir = self.kb_info.kb_dir
        rec.kb_version = self.kb_info.version
        rec.table_versions = dict(self.kb_info.table_versions)

    # ---- 확정·재개 -----------------------------------------------------------------------

    def confirm(self, case: WasteCase, expected_code: str | None) -> tuple[VerdictRecord, int]:
        """서버가 다시 평가해 규칙 엔진이 결론을 낸 경우(FINAL_REVIEW)만 확정한다.

        expected_code(선택): 클라이언트가 화면에서 본 결론. 분류번호가 있는 판정이면 그 번호,
        코드 없는 결론이면 사유(outcome, 예: NOT_WASTE. '@NOT_WASTE'도 받음)와 같아야 한다.
        다르면 409이며 server_code·server_outcome을 돌려준다. 보내지 않으면 비교하지 않는다.
        """
        if case.status == CaseStatus.CODE_CONFIRMED.value:
            raise ServiceError(
                409, "이미 확정된 건입니다", "ALREADY_CONFIRMED", case_status=case.status
            )
        ls = self._open_session(case)
        s = ls.session
        step = s.peek()  # 클라이언트를 믿지 않고 서버가 지금 사실로 다시 평가한다
        ev, d = step.evaluation, step.decision
        if not (ev.can_confirm and d.branch == Branch.FINAL_REVIEW) or ev.decided is None:
            raise ServiceError(
                409,
                "아직 확정할 수 없습니다",
                "NOT_CONFIRMABLE",
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
                "CODE_MISMATCH",
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
            raise ServiceError(
                409, "확정된 건만 다시 열 수 있습니다", "NOT_REOPENABLE", case_status=case.status
            )
        current = self.repo.current_verdict(case.id)
        if current is not None:
            now = utcnow()
            current.superseded_at = now
            current.reopened_at = now
            current.reopen_reason = reason
        rec = self.session_record(case)
        ls = self._load(rec, allow_kb_change=True)
        self.repo.add_trace(
            rec,
            "REOPEN",
            new_id()[:12],
            {"superseded_version": current.version if current else None, "reason": reason},
        )
        if self.repo.kb_changed(rec):
            # 확정 건은 rebase할 수 없으므로 reopen이 지금 규칙으로 맞춘다(이전 판정은 그대로 보존)
            self._rebase_record(ls, trigger="reopen")
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
