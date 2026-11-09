"""폐기물 건 상태 (docs/engine/algorithm.md 8절)."""

from __future__ import annotations

from enum import StrEnum


class CaseStatus(StrEnum):
    NEEDS_INFO = "NEEDS_INFO"  # 추가 정보·증빙 필요(판정 불가 건 포함)
    DIAGNOSING = "DIAGNOSING"  # 문진 진행 중
    CODE_CONFIRMED = "CODE_CONFIRMED"  # 코드 확정, 경로 미확정
    IN_TRANSIT = "IN_TRANSIT"  # 운반 중 (갱신 주체 미정 — 이번 범위 밖)
    COMPLETED = "COMPLETED"  # 거래 완료(이력)


# 문진(메시지·문서 업로드)을 받을 수 있는 상태. 확정 뒤에는 reopen을 거쳐야 한다.
DIAGNOSABLE = frozenset({CaseStatus.DIAGNOSING, CaseStatus.NEEDS_INFO})


def status_after_turn(next_status: str) -> CaseStatus:
    """라우터의 next_status → 건 상태.

    ASK_FACT·RESOLVE_CONFLICT·FINAL_REVIEW → DIAGNOSING (FINAL_REVIEW는 확정 전까지 DIAGNOSING),
    REQUEST_EVIDENCE·UNSUPPORTED → NEEDS_INFO.
    """
    return CaseStatus(next_status)
