"""런타임 사실(Fact)과 사실 이력 저장소.

같은 키의 사실은 덮어쓰지 않고 append한다. 평가에는 키별 '유효 사실'을 쓴다.
유효 사실 우선순위: EVIDENCED > CLAIMED > 그 외(UNKNOWN, DECLARED_UNKNOWN), 같은 등급이면 최신.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.ranges import NumRange

FactValue = bool | int | float | str | NumRange | None


class FactStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    DECLARED_UNKNOWN = "DECLARED_UNKNOWN"  # 사용자가 "모름"이라고 답함 → 다시 묻지 않음
    CLAIMED = "CLAIMED"  # 사용자 진술
    EVIDENCED = "EVIDENCED"  # 문서로 확인


STATUS_RANK: dict[FactStatus, int] = {
    FactStatus.UNKNOWN: 0,
    FactStatus.DECLARED_UNKNOWN: 0,
    FactStatus.CLAIMED: 1,
    FactStatus.EVIDENCED: 2,
}

KNOWN_STATUSES = frozenset({FactStatus.CLAIMED, FactStatus.EVIDENCED})

SourceType = Literal["UTTERANCE", "DOCUMENT", "PROFILE", "SCREENING", "SIMULATION"]


def _now() -> datetime:
    return datetime.now(UTC)


class Fact(BaseModel):
    key: str
    value: FactValue = None
    status: FactStatus
    source_type: SourceType = "UTTERANCE"
    source_ref: str = ""  # message_id / document_id / group_id
    note: str | None = None  # 정량화되지 않은 진술 원문 요약
    quote: str | None = None  # 근거가 된 원문 일부
    recorded_at: datetime = Field(default_factory=_now)

    @property
    def is_known(self) -> bool:
        return self.status in KNOWN_STATUSES and self.value is not None


def _sort_key(f: Fact) -> tuple:
    # 같은 등급·같은 시각이면 입력 순서와 무관하게 결정되도록 출처·값으로 마저 정렬한다.
    return (STATUS_RANK[f.status], f.recorded_at, f.source_ref, repr(f.value))


def effective_fact(history: Iterable[Fact]) -> Fact | None:
    items = list(history)
    if not items:
        return None
    return max(items, key=_sort_key)


class FactStore:
    """append-only 사실 이력."""

    def __init__(self, facts: Iterable[Fact] = ()) -> None:
        self._facts: list[Fact] = list(facts)

    def append(self, fact: Fact) -> None:
        self._facts.append(fact)

    def extend(self, facts: Iterable[Fact]) -> None:
        self._facts.extend(facts)

    @property
    def history(self) -> list[Fact]:
        return list(self._facts)

    def history_of(self, key: str) -> list[Fact]:
        return [f for f in self._facts if f.key == key]

    def effective(self) -> dict[str, Fact]:
        by_key: dict[str, list[Fact]] = {}
        for f in self._facts:
            by_key.setdefault(f.key, []).append(f)
        return {k: effective_fact(v) for k, v in by_key.items()}  # type: ignore[misc]

    def copy(self) -> FactStore:
        return FactStore(self._facts)
