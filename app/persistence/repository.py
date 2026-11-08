"""문진 세션 저장·복원.

요청마다 DB 행에서 DiagnosisSession을 다시 만든다(서버는 상태를 들고 있지 않는다).
- 사실: FactRecord를 seq 순서로 읽어 FactStore를 다시 쌓는다. 저장은 새로 늘어난 이력만 append.
- 세션 상태: DiagnosisSession.export_state() JSON (SessionState, last_question, messages ...)
- Trace: 이번 요청에서 새로 생긴 턴만 TraceRecord로 append. 불변 행은 고치지 않는다.
- 규칙 버전: 세션에 저장된 kb_version이 지금 규칙과 다르면 복원하지 않고 KBChanged를 낸다
  (조용히 새 규칙으로 이어 가지 않는다). rebase만 allow_kb_change=True로 연다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.agent.llm_client import LLMClient
from app.agent.orchestrator import DiagnosisSession
from app.domain.facts import Fact
from app.persistence.models import (
    DiagnosisSessionRecord,
    FactRecord,
    TraceRecord,
    VerdictRecord,
    WasteCase,
    as_utc,
)
from app.rules.model import KnowledgeBase


def fact_to_row(session_id: str, seq: int, f: Fact) -> FactRecord:
    d = f.model_dump(mode="json")
    return FactRecord(
        session_id=session_id,
        seq=seq,
        key=f.key,
        value=d["value"],
        status=d["status"],
        source_type=f.source_type,
        source_ref=f.source_ref,
        note=f.note,
        quote=f.quote,
        recorded_at=f.recorded_at,
        retracted=f.retracted,
        revoked=f.revoked,
    )


def row_to_fact(r: FactRecord) -> Fact:
    return Fact.model_validate(
        {
            "key": r.key,
            "value": r.value,
            "status": r.status,
            "source_type": r.source_type,
            "source_ref": r.source_ref,
            "note": r.note,
            "quote": r.quote,
            "recorded_at": as_utc(r.recorded_at),
            "retracted": bool(r.retracted),
            "revoked": bool(r.revoked),
        }
    )


class KBChanged(Exception):
    """저장된 세션의 규칙 버전과 지금 규칙이 다름 → 409 KB_CHANGED, rebase 후 진행."""

    def __init__(self, session_kb_version: str, current_kb_version: str):
        super().__init__("규칙 버전이 바뀌었습니다")
        self.session_kb_version = session_kb_version
        self.current_kb_version = current_kb_version


@dataclass
class LoadedSession:
    record: DiagnosisSessionRecord
    session: DiagnosisSession
    trace_base: int = 0  # 불러올 때 session.traces 길이(이후 것이 새 턴)


class SessionRepository:
    def __init__(
        self,
        db: Session,
        kb: KnowledgeBase,
        *,
        extractor_llm: LLMClient | None = None,
        responder_llm: LLMClient | None = None,
        kb_version: str | None = None,
    ):
        self.db = db
        self.kb = kb
        self.kb_version = kb_version  # 지금 규칙 버전. None이면 비교하지 않는다
        self.extractor_llm = extractor_llm
        self.responder_llm = responder_llm

    # ---- 세션 ----------------------------------------------------------------------------

    def create(
        self,
        case: WasteCase,
        session: DiagnosisSession,
        *,
        kb_dir: str,
        kb_version: str,
        table_versions: dict[str, str],
        started_at: datetime,
        company_profile_version: str | None = None,
    ) -> LoadedSession:
        rec = DiagnosisSessionRecord(
            id=session.session_id,
            case_id=case.id,
            as_of=session.as_of,
            started_at=started_at,
            last_activity_at=started_at,
            kb_dir=kb_dir,
            kb_version=kb_version,
            table_versions=table_versions,
            company_profile_version=company_profile_version,
            state=session.export_state(),
        )
        self.db.add(rec)
        self.db.flush()
        return LoadedSession(record=rec, session=session, trace_base=0)

    def latest_for_case(self, case_id: str) -> DiagnosisSessionRecord | None:
        return self.db.scalars(
            select(DiagnosisSessionRecord)
            .where(DiagnosisSessionRecord.case_id == case_id)
            .order_by(DiagnosisSessionRecord.created_at.desc())
            .limit(1)
        ).first()

    def kb_changed(self, rec: DiagnosisSessionRecord | None) -> bool:
        return rec is not None and self.kb_version is not None and rec.kb_version != self.kb_version

    def load(self, rec: DiagnosisSessionRecord, *, allow_kb_change: bool = False) -> LoadedSession:
        if not allow_kb_change and self.kb_changed(rec):
            raise KBChanged(rec.kb_version, self.kb_version or "")
        rows = self.db.scalars(
            select(FactRecord).where(FactRecord.session_id == rec.id).order_by(FactRecord.seq)
        ).all()
        s = DiagnosisSession.from_state(
            self.kb,
            rec.state,
            facts=[row_to_fact(r) for r in rows],
            traces=[],  # Trace는 행으로만 둔다(판정에 쓰이지 않음)
            extractor_llm=self.extractor_llm,
            responder_llm=self.responder_llm,
        )
        return LoadedSession(record=rec, session=s, trace_base=0)

    def save(self, ls: LoadedSession) -> None:
        """새로 늘어난 사실·Trace를 append하고 세션 상태를 갱신한다."""
        rec, s = ls.record, ls.session
        hist = s.store.history
        for i in range(rec.fact_count, len(hist)):
            self.db.add(fact_to_row(rec.id, i, hist[i]))
        rec.fact_count = len(hist)
        for t in s.traces[ls.trace_base :]:
            self.add_trace(rec, "TURN", t.turn_id, t.model_dump(mode="json"))
        ls.trace_base = len(s.traces)
        rec.state = s.export_state()

    # ---- Trace ---------------------------------------------------------------------------

    def add_trace(
        self, rec: DiagnosisSessionRecord, kind: str, turn_id: str, payload: dict[str, Any]
    ) -> TraceRecord:
        row = TraceRecord(
            session_id=rec.id, seq=rec.trace_count, kind=kind, turn_id=turn_id, payload=payload
        )
        rec.trace_count += 1
        self.db.add(row)
        return row

    def freeze_traces(self, rec: DiagnosisSessionRecord) -> int:
        """확정 시점까지의 Trace를 불변으로 표시한다."""
        self.db.flush()
        res = self.db.execute(
            update(TraceRecord)
            .where(TraceRecord.session_id == rec.id, TraceRecord.immutable.is_(False))
            .values(immutable=True)
            .execution_options(synchronize_session="fetch")
        )
        return res.rowcount or 0

    def traces(self, session_id: str) -> list[TraceRecord]:
        return list(
            self.db.scalars(
                select(TraceRecord)
                .where(TraceRecord.session_id == session_id)
                .order_by(TraceRecord.seq)
            ).all()
        )

    def latest_turn(self, session_id: str) -> TraceRecord | None:
        return self.db.scalars(
            select(TraceRecord)
            .where(TraceRecord.session_id == session_id, TraceRecord.kind == "TURN")
            .order_by(TraceRecord.seq.desc())
            .limit(1)
        ).first()

    # ---- 판정 버전 -----------------------------------------------------------------------

    def verdicts(self, case_id: str) -> list[VerdictRecord]:
        return list(
            self.db.scalars(
                select(VerdictRecord)
                .where(VerdictRecord.case_id == case_id)
                .order_by(VerdictRecord.version)
            ).all()
        )

    def current_verdict(self, case_id: str) -> VerdictRecord | None:
        return self.db.scalars(
            select(VerdictRecord)
            .where(VerdictRecord.case_id == case_id, VerdictRecord.superseded_at.is_(None))
            .order_by(VerdictRecord.version.desc())
            .limit(1)
        ).first()

    def next_verdict_version(self, case_id: str) -> int:
        cur = self.db.scalar(
            select(func.max(VerdictRecord.version)).where(VerdictRecord.case_id == case_id)
        )
        return (cur or 0) + 1
