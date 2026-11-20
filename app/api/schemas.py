"""요청 본문. 모르는 필드는 무시한다(서버가 필드를 더해도 깨지지 않게)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    kind: Literal["value", "unknown", "none_all", "expand", "retract"] = "value"
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
