"""API 요청·응답 모델. 문진 한 턴의 응답은 app/domain/verdict.py의 TurnResponse(md 10절)다.

시각은 UTC로 저장하고, 응답에서는 시간대를 붙인 ISO 8601(Asia/Seoul, +09:00)로 낸다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.agent.orchestrator import QuickReply
from app.domain.case import CaseStatus
from app.domain.clock import to_seoul
from app.domain.verdict import TurnResponse

# 응답 시각: Asia/Seoul로 바꿔 낸다(저장은 UTC).
SeoulDateTime = Annotated[datetime, AfterValidator(to_seoul)]


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
    created_at: SeoulDateTime


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
    created_at: SeoulDateTime
    updated_at: SeoulDateTime
    # 문진 세션 시각. as_of(법 기준일)는 diagnosis_started_at의 Asia/Seoul 날짜이고 reopen해도 같다.
    diagnosis_started_at: SeoulDateTime | None = None
    last_activity_at: SeoulDateTime | None = None
    as_of: date | None = None


class VerdictOut(_ORM):
    version: int
    result_type: str  # WASTE_CODE | NO_CODE
    code: str | None
    name: str | None
    category: str | None
    outcome: str | None  # 코드 없는 결론의 사유(NOT_WASTE 등)
    rule_ids: list[str]
    table_id: str | None
    table_version: str | None
    kb_version: str
    as_of: date
    facts_snapshot: dict[str, Any]
    verdict: dict[str, Any]
    trace_turn_id: str | None
    handoff: dict[str, Any] | None  # diagnosis-handoff-v1 (docs/handoff-contract.md)
    confirmed_at: SeoulDateTime
    superseded_at: SeoulDateTime | None
    reopened_at: SeoulDateTime | None
    reopen_reason: str | None


class DocumentOut(_ORM):
    id: str
    filename: str
    content_type: str | None
    size: int
    sha256: str
    extracted_facts: dict[str, Any]
    created_at: SeoulDateTime


class CaseCreated(BaseModel):
    case: CaseOut
    turn: TurnResponse


class CaseDetail(BaseModel):
    case: CaseOut
    current_verdict: VerdictOut | None
    verdicts: list[VerdictOut]  # 모든 버전(reopen으로 대체된 것 포함)
    latest_turn: TurnResponse | None
    documents: list[DocumentOut]
    # 현재(대체되지 않은) 확정 판정의 인계 객체. 확정 전·reopen 뒤에는 null
    handoff: dict[str, Any] | None = None


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
    """클라이언트가 본 결론(선택). 서버 재평가 결과와 다르면 409(server_code·server_outcome).

    분류번호가 있는 판정이면 그 번호, 코드 없는 결론이면 사유(예: NOT_WASTE 또는 @NOT_WASTE).
    """

    expected_code: str | None = None


class ConfirmOut(BaseModel):
    case: CaseOut
    verdict: VerdictOut
    handoff: dict[str, Any]  # 경로추천 AI 인계 객체(diagnosis-handoff-v1)
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
    recorded_at: SeoulDateTime
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
