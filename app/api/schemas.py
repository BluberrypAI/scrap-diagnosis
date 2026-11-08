"""API 요청·응답 모델. 문진 한 턴의 응답은 app/domain/verdict.py의 TurnResponse(md 10절)다."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.orchestrator import QuickReply
from app.domain.case import CaseStatus
from app.domain.verdict import TurnResponse


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- 기업 --------------------------------------------------------------------------------


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # 기본 정보·배출시설·주생산품. "facts": {사실 키: 값}은 문진 시작 때 PROFILE 사실로 들어간다.
    profile: dict[str, Any] = {}


class CompanyProfileUpdate(BaseModel):
    profile: dict[str, Any]


class CompanyOut(_ORM):
    id: str
    name: str
    profile: dict[str, Any]
    created_at: datetime


# ---- 건 ----------------------------------------------------------------------------------


class CaseCreate(BaseModel):
    memo: str | None = Field(default=None, max_length=2000)  # 종류 메모
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=20)
    period: str | None = Field(default=None, max_length=50)


class CaseOut(_ORM):
    id: str
    company_id: str
    memo: str | None
    quantity: float | None
    unit: str | None
    period: str | None
    status: CaseStatus
    session_id: str | None = None
    created_at: datetime
    updated_at: datetime


class VerdictOut(_ORM):
    version: int
    code: str | None
    name: str | None
    category: str | None
    rule_ids: list[str]
    table_id: str | None
    table_version: str | None
    kb_version: str
    as_of: date
    facts_snapshot: dict[str, Any]
    verdict: dict[str, Any]
    trace_turn_id: str | None
    confirmed_at: datetime
    superseded_at: datetime | None


class DocumentOut(_ORM):
    id: str
    filename: str
    content_type: str | None
    size: int
    sha256: str
    extracted_facts: dict[str, Any]
    created_at: datetime


class CaseCreated(BaseModel):
    case: CaseOut
    turn: TurnResponse


class CaseDetail(BaseModel):
    case: CaseOut
    current_verdict: VerdictOut | None
    verdicts: list[VerdictOut]  # 모든 버전(reopen으로 대체된 것 포함)
    latest_turn: TurnResponse | None
    documents: list[DocumentOut]


# ---- 문진 --------------------------------------------------------------------------------


class MessageIn(BaseModel):
    """자유 진술(text) 또는 선택지 버튼(quick_reply) 중 하나."""

    text: str | None = Field(default=None, max_length=4000)
    quick_reply: QuickReply | None = None

    @model_validator(mode="after")
    def _one_of(self) -> MessageIn:
        has_text = bool(self.text and self.text.strip())
        if has_text == (self.quick_reply is not None):
            raise ValueError("text와 quick_reply 중 하나만 보내야 합니다")
        return self


class DocumentTurn(BaseModel):
    document: DocumentOut
    turn: TurnResponse


class ConfirmIn(BaseModel):
    """클라이언트가 본 코드(선택). 서버 재평가 결과와 다르면 409."""

    expected_code: str | None = None


class ConfirmOut(BaseModel):
    case: CaseOut
    verdict: VerdictOut
    frozen_trace_rows: int


class ReopenIn(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class ReopenOut(BaseModel):
    case: CaseOut
    superseded_verdict: VerdictOut | None
    turn: TurnResponse


# ---- Trace -------------------------------------------------------------------------------


class TraceRowOut(_ORM):
    seq: int
    kind: str
    turn_id: str
    immutable: bool
    recorded_at: datetime
    payload: dict[str, Any]


class TraceSessionOut(BaseModel):
    session_id: str
    as_of: date
    kb_dir: str
    kb_version: str
    table_versions: dict[str, Any]
    facts: list[dict[str, Any]]  # 사실 이력 전체(append-only)
    turns: list[TraceRowOut]


class TraceOut(BaseModel):
    case_id: str
    sessions: list[TraceSessionOut]
    verdicts: list[VerdictOut]
