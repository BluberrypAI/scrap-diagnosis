"""요청 본문. 모르는 필드는 무시한다(서버가 필드를 더해도 깨지지 않게)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CaseCreateIn(_Body):
    memo: str | None = Field(default=None, max_length=2000)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=20)
    period: str | None = Field(default=None, max_length=50)
    # 서버에서 사용자가 확인한 기업 정보만 보낸다(PROFILE_CONFIRMED)
    confirmed_facts: dict[str, Any] | None = None
    company_profile_version: str | None = Field(default=None, max_length=64)


class QuickReplyIn(_Body):
    key: str = Field(max_length=96)
    # some: 묶음 체크 방식(value = 고른 항목 사실 키 목록, 고르지 않은 항목은 해당 없음)
    kind: Literal["value", "unknown", "none_all", "expand", "some", "retract"] = "value"
    value: Any = None


class MessageIn(_Body):
    text: str | None = Field(default=None, max_length=4000)
    quick_reply: QuickReplyIn | None = None
    confirmed_facts: dict[str, Any] | None = None
    company_profile_version: str | None = Field(default=None, max_length=64)


class ConfirmIn(_Body):
    expected_code: str | None = Field(default=None, max_length=40)


class ReopenIn(_Body):
    reason: str | None = Field(default=None, max_length=1000)


class ApplyValueIn(_Body):
    """검수한 서류 값 하나. value_id(검수 대기 후보) 또는 fact_key 중 하나는 있어야 한다.

    value를 빼면 후보 값을 그대로 쓰고(value_id일 때), 주면 검수에서 고친 값으로 쓴다.
    reject=true면 적용하지 않고 후보를 REJECTED로 둔다. reviewer·reviewed_at은 서버가 채운다.
    """

    value_id: str | None = Field(default=None, max_length=32)
    fact_key: str | None = Field(default=None, max_length=96)
    value: Any = None
    unit: str | None = Field(default=None, max_length=30)
    document_version: int = Field(ge=1)
    reviewer: str | None = Field(default=None, max_length=200)
    reviewed_at: datetime | None = None
    reject: bool = False

    @model_validator(mode="after")
    def _ref(self) -> ApplyValueIn:
        if not self.value_id and not self.fact_key:
            raise ValueError("value_id 또는 fact_key가 필요합니다")
        return self


class ApplyIn(_Body):
    values: list[ApplyValueIn] = Field(min_length=1, max_length=200)


class RevokeIn(_Body):
    reason: str | None = Field(default=None, max_length=1000)
    document_version: int | None = Field(default=None, ge=1)
