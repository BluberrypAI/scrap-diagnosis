"""수치 구간 값.

사용자가 "5% 미만"처럼 구간으로 답하면 대표값을 지어내지 않고 구간 그대로 저장한다.
조건 평가는 구간 전체가 조건을 만족하면 참, 전혀 만족하지 않으면 거짓, 걸치면 판단 보류다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

_Interval = tuple[float | None, bool, float | None, bool]  # lo, lo_inc, hi, hi_inc (None=무한)


class NumRange(BaseModel):
    model_config = ConfigDict(frozen=True)

    lo: float | None = None
    lo_inc: bool = True
    hi: float | None = None
    hi_inc: bool = False

    def as_tuple(self) -> _Interval:
        return (
            self.lo,
            self.lo_inc if self.lo is not None else False,
            self.hi,
            self.hi_inc if self.hi is not None else False,
        )

    def label(self, unit: str | None = None) -> str:
        u = unit or ""

        def fmt(x: float) -> str:
            return f"{x:g}{u}"

        if self.lo is not None and self.hi is not None and self.lo == self.hi:
            return fmt(self.lo)
        parts = []
        if self.lo is not None:
            parts.append(f"{fmt(self.lo)} {'이상' if self.lo_inc else '초과'}")
        if self.hi is not None:
            parts.append(f"{fmt(self.hi)} {'이하' if self.hi_inc else '미만'}")
        return " ".join(parts) if parts else "값 무관"


def _cond_interval(op: str, t: float) -> _Interval:
    return {
        "lt": (None, False, t, False),
        "lte": (None, False, t, True),
        "gt": (t, False, None, False),
        "gte": (t, True, None, False),
        "eq": (t, True, t, True),
    }[op]


def _intersect(a: _Interval, b: _Interval) -> _Interval | None:
    alo, alo_i, ahi, ahi_i = a
    blo, blo_i, bhi, bhi_i = b
    # 하한: 큰 쪽
    if alo is None:
        lo, lo_i = blo, blo_i
    elif blo is None or alo > blo:
        lo, lo_i = alo, alo_i
    elif blo > alo:
        lo, lo_i = blo, blo_i
    else:
        lo, lo_i = alo, alo_i and blo_i
    # 상한: 작은 쪽
    if ahi is None:
        hi, hi_i = bhi, bhi_i
    elif bhi is None or ahi < bhi:
        hi, hi_i = ahi, ahi_i
    elif bhi < ahi:
        hi, hi_i = bhi, bhi_i
    else:
        hi, hi_i = ahi, ahi_i and bhi_i
    if lo is not None and hi is not None:
        if lo > hi or (lo == hi and not (lo_i and hi_i)):
            return None
    return (lo, lo_i if lo is not None else False, hi, hi_i if hi is not None else False)


def range_satisfies(r: NumRange, op: str, value) -> bool | None:
    """구간 r의 모든 점이 조건을 만족하면 True, 어떤 점도 만족하지 않으면 False, 걸치면 None."""
    rt = r.as_tuple()
    if op in ("lt", "lte", "gt", "gte", "eq"):
        inter = _intersect(rt, _cond_interval(op, float(value)))
        if inter is None:
            return False
        return True if inter == rt else None
    if op == "ne":
        res = range_satisfies(r, "eq", value)
        return None if res is None else not res
    if op in ("in", "not_in"):
        results = [range_satisfies(r, "eq", v) for v in value]
        res = (
            True
            if any(x is True for x in results)
            else (False if all(x is False for x in results) else None)
        )
        if op == "not_in":
            return None if res is None else not res
        return res
    raise ValueError(op)


def contains(r: NumRange, x: float) -> bool:
    return _intersect(r.as_tuple(), (float(x), True, float(x), True)) is not None
