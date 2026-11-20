"""DB 모델.

- 사실은 append-only(FactRecord): 고치거나 철회해도 새 행을 더한다. 유효 값은 키마다 마지막 행이다.
- 회사 사실(CompanyFact)은 scope: company 질문의 답을 회사별로 기억한다(2026-11-20 B안).
- 확정한 판정(Verdict)과 그때까지의 Trace(TraceEvent.immutable)는 고치거나 지우지 않는다.
  예외는 기업 데이터 삭제 경로(session.info["allow_immutable_delete"])뿐이다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.orm.attributes import get_history


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CompanyFact(Base):
    __tablename__ = "company_facts"
    __table_args__ = (UniqueConstraint("company_id", "fact"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    fact: Mapped[str] = mapped_column(String(64))
    value: Mapped[Any] = mapped_column(JSON)
    source_case_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="DIAGNOSING")
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    period: Mapped[str | None] = mapped_column(String(50), nullable=True)
    kb_version: Mapped[str] = mapped_column(String(64))
    as_of: Mapped[str] = mapped_column(String(10))  # 법 기준일(문진 시작일, Asia/Seoul)
    expanded: Mapped[list] = mapped_column(JSON, default=list)  # 펼친 묶음 질문 id
    # 확인 버튼으로 다시 물을 말 답(추측, 지정폐기물 가능성을 지우는 답)
    # [{fact, value, quote, reason: guess|risky}]
    pending: Mapped[list] = mapped_column(JSON, default=list)
    questions_asked: Mapped[int] = mapped_column(Integer, default=0)
    company_profile_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": row_version}


class FactRecord(Base):
    __tablename__ = "fact_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    fact: Mapped[str] = mapped_column(String(96))
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    # CLAIMED(답함) | EVIDENCED(검수한 서류 값) | DECLARED_UNKNOWN(모른다고 답함)
    # | RETRACTED(철회·서류 효력 해제, 아직 안 물어본 상태로)
    status: Mapped[str] = mapped_column(String(20))
    # UTTERANCE(질문에 답함) | SCREENING(묶음 '해당 없음') | PROFILE(회사 정보 기억)
    # | PROFILE_CONFIRMED(서버가 확인해 보낸 값) | DOCUMENT(검수한 서류 값)
    source_type: Mapped[str] = mapped_column(String(20))
    # 서류 값의 근거: "문서id@v버전"
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)  # 말로 답한 근거 문구(가린 글)
    turn_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Message(Base):
    """대화 기록(conversation). 사용자 말·버튼과 엔진의 질문·결과."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    turn_id: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    text: Mapped[str] = mapped_column(Text, default="")
    quick_reply: Mapped[Any] = mapped_column(JSON, nullable=True)
    branch: Mapped[str | None] = mapped_column(String(30), nullable=True)
    question_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Document(Base):
    """올린 서류. 원문 파일은 저장하지 않고 이름·형식·크기·해시와 자동 읽기 요약만 둔다."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)  # 파일을 바꿀 때마다 1씩
    # {"method": none|manual|table|manual+table, "candidates": {사실: 값}, "table_read"?: 요약}
    extracted_facts: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentValue(Base):
    """서류 값 한 줄. UNVERIFIED(검수 대기)는 판정에 쓰지 않고, APPLIED만 EVIDENCED 사실이 된다.

    상태: UNVERIFIED → APPLIED | REJECTED, APPLIED → REVOKED(효력 해제·파일 교체)
    """

    __tablename__ = "document_values"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    document_version: Mapped[int] = mapped_column(Integer)
    fact_key: Mapped[str] = mapped_column(String(96))
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="UNVERIFIED")
    reviewer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Verdict(Base):
    __tablename__ = "verdicts"
    __table_args__ = (UniqueConstraint("case_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(30))
    code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    result_type: Mapped[str] = mapped_column(String(20))
    handoff: Mapped[dict] = mapped_column(JSON)
    kb_version: Mapped[str] = mapped_column(String(64))
    company_profile_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)


class TraceEvent(Base):
    """판정 근거 추적. 매 턴의 입력과 판정 결과(적용 규칙·근거 조문)를 남긴다."""

    __tablename__ = "trace_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # CREATE | ANSWER | TEXT | RETRACT | DOCUMENT | APPLY | REVOKE | CONFIRM | REOPEN | REBASE
    kind: Mapped[str] = mapped_column(String(20))
    payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    result: Mapped[Any] = mapped_column(JSON, nullable=True)
    kb_version: Mapped[str] = mapped_column(String(64))
    immutable: Mapped[bool] = mapped_column(Boolean, default=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DeletionLog(Base):
    __tablename__ = "deletion_log"

    company_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(10))  # DONE | FAILED
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImmutableRowError(RuntimeError):
    pass


@event.listens_for(Session, "before_flush")
def _protect_immutable(session: Session, _ctx, _instances) -> None:
    if session.info.get("allow_immutable_delete"):
        return
    for obj in session.deleted:
        if isinstance(obj, TraceEvent) and obj.immutable:
            raise ImmutableRowError("확정된 Trace는 지울 수 없음")
        if isinstance(obj, Verdict):
            raise ImmutableRowError("확정된 판정은 지울 수 없음")
    for obj in session.dirty:
        if isinstance(obj, TraceEvent):
            # 확정할 때 immutable로 바꾸는 갱신만 허용하고, 그 뒤의 내용 변경은 막는다
            changed = {
                a.key for a in obj.__mapper__.column_attrs if get_history(obj, a.key).has_changes()
            }
            was_immutable = get_history(obj, "immutable").deleted == [True] or (
                obj.immutable and "immutable" not in changed
            )
            if was_immutable and changed - {"immutable"}:
                raise ImmutableRowError("확정된 Trace는 고칠 수 없음")
        if isinstance(obj, Verdict):
            # 다시 열기(reopen) 표시만 허용한다
            changed = {
                a.key for a in obj.__mapper__.column_attrs if get_history(obj, a.key).has_changes()
            }
            if changed - {"reopened_at", "reopen_reason", "superseded"}:
                raise ImmutableRowError("확정된 판정은 고칠 수 없음")
