"""SQLAlchemy 2.x 모델. 개발은 SQLite, 운영은 PostgreSQL(같은 모델, Alembic 마이그레이션).

- 사실(FactRecord)과 Trace(TraceRecord)는 append-only 행이다. 세션을 다시 만들 때 seq 순서로 읽는다.
- 확정 판정(VerdictRecord)은 버전으로 쌓는다. reopen하면 superseded_at·reopened_at만 채운다
  (지우지 않음).
- 시각은 모두 UTC로 저장한다. API·인계 객체로 내보낼 때 Asia/Seoul로 바꾼다(app/domain/clock.py).
- 확정 시점의 Trace 행은 immutable=True가 되고, 이후 수정·삭제는 막는다(events.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# 제약 이름을 고정해 SQLite·PostgreSQL 마이그레이션이 같은 이름을 쓰게 한다.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite는 시간대를 버린다 → 읽을 때 UTC로 되돌린다."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class UTCDateTime(TypeDecorator):
    """시간대 있는 UTC 시각. SQLite가 버린 시간대를 읽을 때 되돌린다."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(UTC)
        return value

    def process_result_value(self, value, dialect):  # noqa: ANN001
        return as_utc(value)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    # scrap-server가 쓰는 기업 ID(/internal/v1의 X-Company-Id). 개발용으로 만든 기업은 None.
    external_id: Mapped[str | None] = mapped_column(String(128), unique=True, index=False)
    # 기업 정보: 기본 정보·배출시설·주생산품. "facts"는 문진 시작 때 PROFILE 사실로 넣는다.
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    users: Mapped[list[User]] = relationship(back_populates="company")


class User(Base):
    """계정(최소). 인증은 아직 없다 — TODO: 실제 인증·권한."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    company: Mapped[Company] = relationship(back_populates="users")


class WasteCase(Base):
    __tablename__ = "waste_cases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    memo: Mapped[str | None] = mapped_column(Text)  # 종류 메모(자유 기술)
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(20))
    period: Mapped[str | None] = mapped_column(String(50))  # 배출 시기(예: 2026-11, 2026 Q4)
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    sessions: Mapped[list[DiagnosisSessionRecord]] = relationship(
        back_populates="case", order_by="DiagnosisSessionRecord.created_at"
    )


class DiagnosisSessionRecord(Base):
    __tablename__ = "diagnosis_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("waste_cases.id"), index=True)
    # 법 기준일 = started_at의 Asia/Seoul 날짜. reopen해도 바꾸지 않는다.
    as_of: Mapped[date] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)  # 대화 시작
    last_activity_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)  # 마지막 턴
    kb_dir: Mapped[str] = mapped_column(String(500))
    kb_version: Mapped[str] = mapped_column(String(64))  # 규칙 데이터 파일 해시
    table_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # DiagnosisSession.export_state(): SessionState, last_question, messages, case_status ...
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fact_count: Mapped[int] = mapped_column(Integer, default=0)
    trace_count: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=0)  # 낙관적 잠금
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    case: Mapped[WasteCase] = relationship(back_populates="sessions")

    __mapper_args__ = {"version_id_col": revision}


class FactRecord(Base):
    """사실 이력 한 줄(append-only). 키·값만 그대로 저장한다(키별 특별 처리 없음)."""

    __tablename__ = "fact_records"
    __table_args__ = (UniqueConstraint("session_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("diagnosis_sessions.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    source_type: Mapped[str] = mapped_column(String(20))
    source_ref: Mapped[str] = mapped_column(String(100), default="")
    note: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime())
    # 사용자 철회 행(status UNKNOWN). 앞선 같은 키의 CLAIMED를 평가에서 뺀다(app/domain/facts.py).
    retracted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # 서류 효력 해제 표시 행(status UNKNOWN). 같은 키·출처(source_ref)의 앞선 EVIDENCED를 뺀다.
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("waste_cases.id"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str | None] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    # {"method": "manual"|"none", "candidates": {key: value}, "accepted": {}}.
    # 0005부터 업로드 값은 판정에 쓰지 않는 후보(document_values)다. accepted는 이전 호환(빈 객체).
    extracted_facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # 파일 버전. 같은 서류의 파일을 바꾸면 1씩 올리고 파일 정보(이름·해시·본문)를 새 파일로 바꾼다.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())  # 마지막 파일 교체 시각

    values: Mapped[list[DocumentValue]] = relationship(
        order_by="(DocumentValue.created_at, DocumentValue.id)", viewonly=True
    )


class DocumentValue(Base):
    """서류 값 한 줄(후보 → 검수 → 적용).

    - UNVERIFIED: 업로드·직접 입력으로 들어온 후보. 판정에 쓰지 않는다.
    - APPLIED: 서버가 검수 완료로 보낸 값. 같은 값이 EVIDENCED 사실로 append돼 있다.
    - REJECTED: 검수에서 버린 후보.
    - REVOKED: 서류 교체·검수 취소로 효력이 해제됨(사실 이력에는 해제 표시 행).
    엔진은 서류 원문과 값을 대조하지 않는다. 형식(빈 값·숫자 칸의 글자·선택지 밖 값)만 거른다.
    """

    __tablename__ = "document_values"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    document_version: Mapped[int] = mapped_column(Integer)
    case_id: Mapped[str] = mapped_column(ForeignKey("waste_cases.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("diagnosis_sessions.id"))
    fact_key: Mapped[str] = mapped_column(String(100))
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="UNVERIFIED")
    reviewer: Mapped[str | None] = mapped_column(String(200))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class VerdictRecord(Base):
    """확정 판정 버전. reopen해도 지우지 않고 superseded_at만 채운다."""

    __tablename__ = "verdicts"
    __table_args__ = (UniqueConstraint("case_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("waste_cases.id"), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("diagnosis_sessions.id"))
    version: Mapped[int] = mapped_column(Integer)
    result_type: Mapped[str] = mapped_column(String(20), default="WASTE_CODE")  # | NO_CODE
    code: Mapped[str | None] = mapped_column(String(50))
    outcome: Mapped[str | None] = mapped_column(String(50))  # 코드 없는 결론의 사유
    name: Mapped[str | None] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(50))
    rule_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    table_id: Mapped[str | None] = mapped_column(String(100))
    table_version: Mapped[str | None] = mapped_column(String(50))
    kb_version: Mapped[str] = mapped_column(String(64))
    as_of: Mapped[date] = mapped_column(Date)
    facts_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # 유효 사실
    verdict: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # 응답 스키마 verdict
    trace_turn_id: Mapped[str | None] = mapped_column(String(32))  # 확정 근거가 된 마지막 턴
    # 경로추천 AI 인계 객체(diagnosis-handoff-v1). 0002 이전 판정은 비어 있다.
    handoff: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    confirmed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    reopened_at: Mapped[datetime | None] = mapped_column(UTCDateTime())  # 이 판정을 다시 연 시각
    reopen_reason: Mapped[str | None] = mapped_column(Text)


class TraceRecord(Base):
    """Decision Trace 한 줄.

    kind: TURN(문진 한 턴) | DOCUMENT(업로드·파일 교체) | APPLY(검수 값 적용)
    | REVOKE(서류 효력 해제)
    | CONFIRM | REOPEN | REBASE(규칙 버전 갱신).
    """

    __tablename__ = "trace_turns"
    __table_args__ = (UniqueConstraint("session_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("diagnosis_sessions.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20), default="TURN")
    turn_id: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    immutable: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
