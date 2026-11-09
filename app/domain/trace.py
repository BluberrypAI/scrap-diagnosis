"""Decision Trace (docs/engine/algorithm.md 8절). 턴마다 판정을 재현할 수 있는 정보를 남긴다."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.agent.llm_client import LLMCall


def _now() -> datetime:
    return datetime.now(UTC)


class TraceTurn(BaseModel):
    turn_id: str
    recorded_at: datetime = Field(default_factory=_now)
    input_text: str | None = None
    quick_reply: dict | None = None
    extraction: dict | None = None  # guard 결과(채택·거부)
    appended_facts: list[dict] = []
    effective_facts: dict[str, dict] = {}
    table_id: str | None = None
    table_version: str | None = None
    rule_results: list[dict] = []
    conflicts: list[dict] = []
    branch: str
    branch_rank: int
    branch_reason: str
    score_breakdown: list[dict] = []
    llm_calls: list[LLMCall] = []
    responder: dict = {}
    response: dict = {}
