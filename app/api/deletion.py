"""기업 데이터 삭제(CORP-009, 서버의 회원 탈퇴 유예 만료 후 호출).

- 해당 기업의 건·세션·사실·서류(+값)·판정·Trace·사용자와 기업 행을 지운다. 다른 기업은 그대로.
- 불변 Trace 보호(ImmutableTraceError)는 ORM 이벤트라서, 이 경로에서만 Core `DELETE` 문으로
  우회한다. 다른 곳의 수정·삭제 보호는 그대로다.
- 멱등: 이미 지워진 기업은 이전 성공 기록의 건수를 그대로 돌려준다.
- 이력(`deletion_log`)에는 기업 id의 SHA-256만 남긴다. 실패하면 삭제를 되돌리고 FAILED로 기록하며,
  재시도하면 같은 행의 attempts를 올려 이어 간다.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.persistence.models import (
    Company,
    DeletionLog,
    DiagnosisSessionRecord,
    Document,
    DocumentValue,
    FactRecord,
    TraceRecord,
    User,
    VerdictRecord,
    WasteCase,
    utcnow,
)

DONE = "DONE"
FAILED = "FAILED"
# 외래 키 순서(자식 -> 부모)
TABLES = (
    "trace_turns",
    "fact_records",
    "document_values",
    "verdicts",
    "documents",
    "diagnosis_sessions",
    "waste_cases",
    "users",
    "companies",
)


class DeletionFailed(Exception):
    def __init__(self, log: DeletionLog):
        super().__init__(log.error or "삭제 실패")
        self.log = log


def company_hash(external_id: str) -> str:
    return hashlib.sha256(external_id.encode()).hexdigest()


def purge_company(db: Session, company: Company) -> dict[str, int]:
    """한 트랜잭션 안에서 기업 데이터를 지우고 테이블별 건수를 돌려준다(커밋은 호출자)."""
    case_ids = select(WasteCase.id).where(WasteCase.company_id == company.id)
    session_ids = select(DiagnosisSessionRecord.id).where(
        DiagnosisSessionRecord.case_id.in_(case_ids)
    )
    doc_ids = select(Document.id).where(Document.case_id.in_(case_ids))
    steps = (
        ("trace_turns", delete(TraceRecord).where(TraceRecord.session_id.in_(session_ids))),
        ("fact_records", delete(FactRecord).where(FactRecord.session_id.in_(session_ids))),
        (
            "document_values",
            delete(DocumentValue).where(
                DocumentValue.document_id.in_(doc_ids) | DocumentValue.case_id.in_(case_ids)
            ),
        ),
        ("verdicts", delete(VerdictRecord).where(VerdictRecord.case_id.in_(case_ids))),
        ("documents", delete(Document).where(Document.case_id.in_(case_ids))),
        (
            "diagnosis_sessions",
            delete(DiagnosisSessionRecord).where(DiagnosisSessionRecord.case_id.in_(case_ids)),
        ),
        ("waste_cases", delete(WasteCase).where(WasteCase.company_id == company.id)),
        ("users", delete(User).where(User.company_id == company.id)),
        ("companies", delete(Company).where(Company.id == company.id)),
    )
    counts: dict[str, int] = {}
    for name, stmt in steps:
        counts[name] = db.execute(stmt).rowcount or 0
    return counts


def _latest_log(db: Session, h: str) -> DeletionLog | None:
    return db.scalars(
        select(DeletionLog)
        .where(DeletionLog.company_hash == h)
        .order_by(DeletionLog.started_at.desc(), DeletionLog.id.desc())
        .limit(1)
    ).first()


def latest_deletion(db: Session, external_id: str) -> DeletionLog | None:
    return _latest_log(db, company_hash(external_id))


def delete_company_data(db: Session, external_id: str) -> DeletionLog:
    """기업 데이터를 삭제하고 성공 기록을 돌려준다. 실패하면 FAILED를 남기고 DeletionFailed."""
    h = company_hash(external_id)
    prev = _latest_log(db, h)
    company = db.scalars(select(Company).where(Company.external_id == external_id)).first()
    if company is None and prev is not None and prev.status == DONE:
        return prev  # 이미 지움(멱등)
    retry = prev is not None and prev.status == FAILED
    try:
        counts = purge_company(db, company) if company is not None else dict.fromkeys(TABLES, 0)
        log = prev if retry else DeletionLog(company_hash=h, started_at=utcnow(), attempts=0)
        if not retry:
            db.add(log)
        log.attempts += 1
        log.status, log.counts, log.error, log.finished_at = DONE, counts, None, utcnow()
        db.commit()
        return log
    except Exception as exc:
        db.rollback()
        failed = _latest_log(db, h)
        err = f"{type(exc).__name__}: {exc}"[:1000]
        if failed is not None and failed.status == FAILED:
            failed.attempts += 1
            failed.error, failed.finished_at = err, utcnow()
        else:
            failed = DeletionLog(
                company_hash=h,
                status=FAILED,
                counts={},
                attempts=1,
                error=err,
                started_at=utcnow(),
                finished_at=utcnow(),
            )
            db.add(failed)
        db.commit()
        raise DeletionFailed(failed) from exc
