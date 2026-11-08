"""충돌 탐지 v1 (규칙 기반).

(a) 같은 키에 CLAIMED와 EVIDENCED 값이 서로 다르면 충돌. 뒤에 같은 값을 다시 진술하면 해소.
(b) 후보가 0개면 규칙별로 어떤 사실 때문에 FALSE가 됐는지 모아 최소 설명을 만든다(탐욕적 덮개).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.domain.facts import Fact, FactStatus
from app.domain.ranges import NumRange, contains
from app.rules.evaluator import TV, EvaluationResult


class Conflict(BaseModel):
    kind: Literal["CLAIM_VS_EVIDENCE", "NO_CANDIDATE"]
    facts: list[str]
    claimed: Any = None
    evidenced: Any = None
    rule_ids: list[str] = []
    message: str


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, NumRange) and isinstance(b, int | float) and not isinstance(b, bool):
        return contains(a, b)
    if isinstance(b, NumRange) and isinstance(a, int | float) and not isinstance(a, bool):
        return contains(b, a)
    if (
        isinstance(a, int | float)
        and isinstance(b, int | float)
        and not (isinstance(a, bool) or isinstance(b, bool))
    ):
        return abs(float(a) - float(b)) < 1e-9
    return a == b


def _conflict_message(key: str, claimed: Any, evidenced: Any) -> str:
    said = f"'{key}'에 대해 말씀하신 값({claimed})"
    return f"{said}과 문서 값({evidenced})이 다릅니다."


def _latest(items: list[Fact]) -> Fact | None:
    return max(items, key=lambda f: (f.recorded_at, f.source_ref, repr(f.value)), default=None)


def claim_vs_evidence(history: list[Fact]) -> list[Conflict]:
    out = []
    for key in sorted({f.key for f in history}):
        hist = [f for f in history if f.key == key and f.value is not None]
        claimed = _latest([f for f in hist if f.status == FactStatus.CLAIMED])
        evidenced = _latest([f for f in hist if f.status == FactStatus.EVIDENCED])
        if claimed is None or evidenced is None:
            continue
        if not _same(claimed.value, evidenced.value):
            cv = (
                claimed.value.model_dump()
                if isinstance(claimed.value, NumRange)
                else (claimed.value)
            )
            out.append(
                Conflict(
                    kind="CLAIM_VS_EVIDENCE",
                    facts=[key],
                    claimed=cv,
                    evidenced=evidenced.value,
                    message=_conflict_message(key, cv, evidenced.value),
                )
            )
    return out


def explain_no_candidate(ev: EvaluationResult) -> Conflict | None:
    if ev.table_status != "SELECTED" or ev.candidates:
        return None
    falsified = {r.rule_id: set(r.eliminated_by) for r in ev.rule_results if r.status == TV.FALSE}
    remaining = set(falsified)
    chosen: list[str] = []
    while remaining:
        counts: dict[str, int] = {}
        for rid in remaining:
            for k in falsified[rid]:
                counts[k] = counts.get(k, 0) + 1
        if not counts:
            break
        best = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        chosen.append(best)
        remaining = {rid for rid in remaining if best not in falsified[rid]}
    return Conflict(
        kind="NO_CANDIDATE",
        facts=chosen,
        rule_ids=sorted(falsified),
        message="입력된 사실 조합에 맞는 분류가 없습니다. 다음 사실을 다시 확인해 주세요: "
        + ", ".join(chosen),
    )


def detect_conflicts(history: list[Fact], ev: EvaluationResult) -> list[Conflict]:
    out = claim_vs_evidence(history)
    nc = explain_no_candidate(ev)
    if nc is not None:
        out.append(nc)
    return out
