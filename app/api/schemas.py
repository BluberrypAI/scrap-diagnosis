"""API 요청·응답 모델. 문진 한 턴의 응답은 app/domain/verdict.py의 TurnResponse(md 10절)다.

시각은 UTC로 저장하고, 응답에서는 시간대를 붙인 ISO 8601(Asia/Seoul, +09:00)로 낸다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent.orchestrator import QuickReply
from app.api.profile import CompanyProfile, profile_out
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
    # 기본 정보·배출시설·주생산품(docs/ui/ui-contract.md 5절). 서버가 facilities로 사이트 사실을
    # 계산하고, 직접 보낸 facts가 우선한다. 사이트 사실은 문진 시작 때 PROFILE 사실로 들어간다.
    profile: CompanyProfile = CompanyProfile()


class CompanyProfileUpdate(BaseModel):
    profile: CompanyProfile


class CompanyOut(_ORM):
    id: str
    name: str
    # 저장된 profile. facts는 계산된 사이트 사실(facilities 계산값 + 직접 지정값)이다.
    profile: dict[str, Any]
    created_at: SeoulDateTime

    @field_validator("profile", mode="after")
    @classmethod
    def _computed_facts(cls, v: dict[str, Any]) -> dict[str, Any]:
        return profile_out(v)


# ---- 건 ----------------------------------------------------------------------------------


class CaseCreate(BaseModel):
    memo: str | None = Field(default=None, max_length=2000)  # 종류 메모
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=20)
    period: str | None = Field(default=None, max_length=50)


class CaseSummary(BaseModel):
    """건 목록 카드(docs/ui/ui-contract.md 3절)."""

    title: str  # 소재 라벨 → 메모 첫 줄(30자) → "새 폐기물"
    code: str | None = None  # 확정(또는 확정 검토 중) 분류번호
    outcome: str | None = None  # 코드 없는 결론의 사유
    result_label: str | None = None  # "51-03-01 폐합성수지류…" / "폐기물 아님". 없으면 null(미정)
    status_label: str  # 문진 중 / 추가 정보 필요 / 확정 / 운반 중 / 완료
    next_action: str | None = None  # 다음 할 일


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
    summary: CaseSummary | None = None  # 건 목록 카드(ui-v1)


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


class ConversationItem(BaseModel):
    """대화 기록 한 줄(docs/ui/ui-contract.md 2절). 새로고침해도 대화를 다시 그린다.

    - 사용자 말: role user, text = 말한 문장(건 메모 포함, memo true)
    - 버튼 답: role user, text = 고른 선택지 라벨, quick_reply = 보낸 값
    - 서류 업로드: role user, text = "서류를 올렸어요: 파일명", document_id
    - AI 말: role assistant, branch, question_key
    """

    turn_id: str
    role: Literal["user", "assistant"]
    text: str
    quick_reply: dict[str, Any] | None = None
    memo: bool = False
    document_id: str | None = None
    branch: str | None = None
    question_key: str | None = None
    at: SeoulDateTime | None = None  # 이 기능 전에 쌓인 기록은 null


class CaseDetail(BaseModel):
    case: CaseOut
    current_verdict: VerdictOut | None
    verdicts: list[VerdictOut]  # 모든 버전(reopen으로 대체된 것 포함)
    latest_turn: TurnResponse | None
    documents: list[DocumentOut]
    # 현재(대체되지 않은) 확정 판정의 인계 객체. 확정 전·reopen 뒤에는 null
    handoff: dict[str, Any] | None = None
    conversation: list[ConversationItem] = []  # 대화 기록(reopen 전후 포함, 시간순)


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


# ---- 카탈로그 ----------------------------------------------------------------------------


class CatalogValue(BaseModel):
    value: Any  # enum 값(문자열) 또는 bool
    label: str
    parent_value: str | None = None  # parent가 있는 사실: 이 값이 속한 상위 분류 값


class CatalogFact(BaseModel):
    """보드 편집·라벨용 사실 요약. 내부 사실(internal)은 뺀다."""

    key: str
    label: str
    type: Literal["enum", "bool", "number"]
    unit: str | None = None
    values: list[CatalogValue] = []  # enum: 값 영역, bool: 예/아니오, number: 비움
    parent: str | None = None  # 상위 분류 사실 키(예: material → material_group)
