"""런타임 사실(Fact)과 사실 이력 저장소.

같은 키의 사실은 덮어쓰지 않고 append한다. 평가에는 키별 '유효 사실'을 쓴다.
유효 사실 우선순위: EVIDENCED > CLAIMED > 그 외(UNKNOWN, DECLARED_UNKNOWN), 같은 등급이면 최신.

철회(retract, docs/ui/ui-contract.md 4절): 사용자가 "모름으로 되돌리기"를 누르면 그 키에
`status=UNKNOWN, retracted=True` 행을 append한다(이력은 지우지 않는다). 유효 사실을 고를 때는
철회 행보다 늦지 않게 기록된 같은 키의 진술(CLAIMED)을 무시한다. EVIDENCED는 무시하지 않고,
철회 뒤에 다시 진술하면 그 값이 유효하다. 철회 행이 없는 이력의 동작은 이전과 같다.

서류 효력 해제(revoke, docs/api/server-engine-contract.md): 서류를 교체하거나 검수를 취소하면
그 서류에서 온 키마다 `revoked=True` 표시 행(status UNKNOWN, source_type DOCUMENT,
source_ref = 해제한 출처)을 append한다. 유효 사실을 고를 때는 표시 행보다 늦지 않게 기록된
같은 키·같은 출처의 증빙(EVIDENCED, DOCUMENT)을 무시하고, 표시 행 자체도 고르지 않는다
(서류가 없던 상태로 돌아간다). 출처가 `문서id`이면 그 문서의 모든 버전(`문서id@v2` 등),
`문서id@vN`이면 그 버전만 해당한다. 해제 뒤에 다시 적용(apply)한 값은 유효하다.
이력은 지우지 않는다.
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
    # 서류 효력 해제 표시 행(status UNKNOWN). 같은 키·출처의 앞선 EVIDENCED를 평가에서 뺀다.
    revoked: bool = False

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


REVOKE_NOTE = "서류 효력 해제"
DOC_VERSION_SEP = "@v"


def document_source_ref(document_id: str, version: int | None = None) -> str:
    """서류 출처 표기. 버전을 주면 `문서id@v버전`."""
    return document_id if version is None else f"{document_id}{DOC_VERSION_SEP}{version}"


def document_id_of(source_ref: str) -> str:
    """`문서id@v버전` → 문서id(버전 없는 이전 표기는 그대로)."""
    return source_ref.split(DOC_VERSION_SEP, 1)[0]


def source_matches(source_ref: str, revoked_ref: str) -> bool:
    """해제한 출처(revoked_ref)가 이 사실의 출처를 덮는가. `문서id`는 그 문서의 모든 버전."""
    if source_ref == revoked_ref:
        return True
    return DOC_VERSION_SEP not in revoked_ref and source_ref.startswith(
        revoked_ref + DOC_VERSION_SEP
    )


def revoke_fact(key: str, source_ref: str, *, note: str | None = None) -> Fact:
    """그 키에서 source_ref 서류의 증빙을 빼는 표시 행."""
    return Fact(
        key=key,
        value=None,
        status=FactStatus.UNKNOWN,
        source_type="DOCUMENT",
        source_ref=source_ref,
        note=note or REVOKE_NOTE,
        revoked=True,
    )


def _revoked_evidence(f: Fact, marks: list[Fact]) -> bool:
    if f.status != FactStatus.EVIDENCED or f.source_type != "DOCUMENT":
        return False
    return any(
        f.recorded_at <= m.recorded_at and source_matches(f.source_ref, m.source_ref) for m in marks
    )


def active_facts(history: Iterable[Fact]) -> list[Fact]:
    """평가에 쓸 이력. 철회된 진술(CLAIMED)과 효력이 해제된 서류 증빙을 뺀다.

    - 철회: 키마다 마지막 철회 시각 이전의 진술을 뺀다(철회 행은 남는다 → '모르는 상태').
    - 효력 해제: 표시 행 이전에 기록된 같은 키·같은 출처의 EVIDENCED를 빼고 표시 행도 뺀다.
    입력 순서와 무관하다(기록 시각으로만 판단). 두 표시 행이 없으면 이력 그대로다.
    """
    items = list(history)
    cuts: dict[str, datetime] = {}
    marks: dict[str, list[Fact]] = {}
    for f in items:
        if f.retracted and (f.key not in cuts or f.recorded_at > cuts[f.key]):
            cuts[f.key] = f.recorded_at
        if f.revoked:
            marks.setdefault(f.key, []).append(f)
    if not cuts and not marks:
        return items
    return [
        f
        for f in items
        if not f.revoked
        and not _retracted_claim(f, cuts.get(f.key))
        and not _revoked_evidence(f, marks.get(f.key, []))
    ]


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
        out: dict[str, Fact] = {}
        for k, v in by_key.items():
            f = effective_fact(v)
            if f is not None:  # 효력 해제 표시 행만 남은 키는 '사실 없음'
                out[k] = f
        return out

    def copy(self) -> FactStore:
        return FactStore(self._facts)
