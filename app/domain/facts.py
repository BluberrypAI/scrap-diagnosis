"""런타임 사실(Fact)과 사실 이력 저장소.

같은 키의 사실은 덮어쓰지 않고 append한다. 평가에는 키별 '유효 사실'을 쓴다.
유효 사실 우선순위: EVIDENCED > CLAIMED > 그 외(UNKNOWN, DECLARED_UNKNOWN), 같은 등급이면 최신.

철회(retract, docs/ui/ui-contract.md 4절): 사용자가 "모름으로 되돌리기"를 누르면 그 키에
`status=UNKNOWN, retracted=True` 행을 append한다(이력은 지우지 않는다). 유효 사실을 고를 때는
철회 행보다 늦지 않게 기록된 같은 키의 진술(CLAIMED)을 무시한다. EVIDENCED는 무시하지 않고,
철회 뒤에 다시 진술하면 그 값이 유효하다. 철회 행이 없는 이력의 동작은 이전과 같다.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
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

SourceType = Literal["UTTERANCE", "DOCUMENT", "PROFILE", "SCREENING", "SIMULATION", "DERIVED"]


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
    # 사용자가 이 키의 앞선 진술을 철회함(status는 UNKNOWN). 앞선 CLAIMED를 평가에서 뺀다.
    retracted: bool = False

    @property
    def is_known(self) -> bool:
        return self.status in KNOWN_STATUSES and self.value is not None


def _sort_key(f: Fact) -> tuple:
    # 같은 등급·같은 시각이면 입력 순서와 무관하게 결정되도록 출처·값으로 마저 정렬한다.
    return (STATUS_RANK[f.status], f.recorded_at, f.source_ref, repr(f.value))


RETRACT_NOTE = "사용자가 철회"


def retract_fact(key: str, *, source_ref: str = "", source_type: SourceType = "UTTERANCE") -> Fact:
    """그 키를 '모르는 상태'로 되돌리는 철회 행."""
    return Fact(
        key=key,
        value=None,
        status=FactStatus.UNKNOWN,
        source_type=source_type,
        source_ref=source_ref,
        note=RETRACT_NOTE,
        retracted=True,
    )


def _retracted_claim(f: Fact, cut: datetime | None) -> bool:
    return cut is not None and f.status == FactStatus.CLAIMED and f.recorded_at <= cut


def active_facts(history: Iterable[Fact]) -> list[Fact]:
    """철회된 진술(CLAIMED)을 뺀 이력. 키마다 마지막 철회 시각 이전의 진술을 뺀다.

    입력 순서와 무관하다(기록 시각으로만 판단). 철회 행이 없으면 이력 그대로다.
    """
    items = list(history)
    cuts: dict[str, datetime] = {}
    for f in items:
        if f.retracted and (f.key not in cuts or f.recorded_at > cuts[f.key]):
            cuts[f.key] = f.recorded_at
    if not cuts:
        return items
    return [f for f in items if not _retracted_claim(f, cuts.get(f.key))]


def effective_fact(history: Iterable[Fact]) -> Fact | None:
    items = active_facts(history)
    if not items:
        return None
    return max(items, key=_sort_key)


class FactStore:
    """append-only 사실 이력.

    append로 들어오는 사실은 기록 시각이 항상 앞의 것보다 늦도록 맞춘다. 한 턴 안에서 연달아
    들어온 사실도 '같은 등급이면 최신' 규칙이 들어온 순서대로 적용되게 하기 위해서다.
    (생성자로 넘긴 이력은 그대로 둔다 — 순서 불변성 테스트는 이력 자체의 시각으로 판단한다.)
    """

    _TICK = timedelta(microseconds=1)

    def __init__(self, facts: Iterable[Fact] = ()) -> None:
        self._facts: list[Fact] = list(facts)
        self._last = max((f.recorded_at for f in self._facts), default=None)

    def append(self, fact: Fact) -> None:
        if self._last is not None and fact.recorded_at <= self._last:
            fact = fact.model_copy(update={"recorded_at": self._last + self._TICK})
        self._last = fact.recorded_at
        self._facts.append(fact)

    def extend(self, facts: Iterable[Fact]) -> None:
        for f in facts:
            self.append(f)

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
