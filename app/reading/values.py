"""칸 글자 → 값 해석(숫자, 부등호, 불검출, 단위). 대응 층과 표 검증이 함께 쓴다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.domain.document import Comparator
from app.reading.units import find_unit

ValueKind = Literal["number", "nd", "text", "empty"]

_ND_RE = re.compile(r"^(n\.?\s?d\.?|불검출|검출안됨|검출되지않음|미검출)", re.IGNORECASE)
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?|\.\d+")
_PREFIX_CMP = {
    "<": Comparator.LT,
    "＜": Comparator.LT,
    "≤": Comparator.LTE,
    "≦": Comparator.LTE,
    ">": Comparator.GT,
    "＞": Comparator.GT,
    "≥": Comparator.GTE,
    "≧": Comparator.GTE,
}
_SUFFIX_CMP = {
    "미만": Comparator.LT,
    "이하": Comparator.LTE,
    "초과": Comparator.GT,
    "이상": Comparator.GTE,
}
EMPTY_MARKS = {"", "-", "–", "—", "/", "n/a", "na"}


@dataclass(frozen=True)
class ParsedValue:
    kind: ValueKind
    raw: str  # 칸 글자(각주 표시 뗀 것)
    number_raw: str | None = None  # 값으로 쓴 숫자 표기 그대로("1,234.5")
    value: float | None = None
    comparator: Comparator = Comparator.EQ
    detection_limit: float | None = None  # "불검출(<0.01)"처럼 칸 안에 있는 검출한계
    detection_limit_raw: str | None = None
    unit: str | None = None


def to_float(num_raw: str) -> float:
    return float(num_raw.replace(",", ""))


def numbers_in(text: str) -> list[str]:
    return _NUM_RE.findall(text or "")


def parse_value(text: str) -> ParsedValue:
    raw = (text or "").strip()
    compact = re.sub(r"\s+", "", raw)
    if compact.lower() in EMPTY_MARKS:
        return ParsedValue(kind="empty", raw=raw)
    unit = find_unit(raw)
    if _ND_RE.match(compact):
        nums = numbers_in(compact)
        dl = to_float(nums[0]) if len(nums) == 1 else None
        return ParsedValue(
            kind="nd",
            raw=raw,
            detection_limit=dl,
            detection_limit_raw=nums[0] if dl is not None else None,
            unit=unit,
        )
    nums = numbers_in(compact)
    if len(nums) != 1:
        # 숫자가 없거나 여럿("0.1~0.2", "1.2 / 1.3")이면 값으로 정하지 않는다
        return ParsedValue(kind="text", raw=raw, unit=unit)
    num = nums[0]
    head = compact[: compact.find(num)]
    tail = compact[compact.find(num) + len(num) :]
    cmp = Comparator.EQ
    if head and head[-1] in _PREFIX_CMP:
        cmp = _PREFIX_CMP[head[-1]]
        head = head[:-1]
    for word, c in _SUFFIX_CMP.items():
        if word in tail:
            cmp = c
    # 숫자 앞에 다른 글자(예: "약", "Ca")가 있으면 값으로 보지 않는다. 음수 부호는 받지 않는다.
    if head:
        return ParsedValue(kind="text", raw=raw, unit=unit)
    return ParsedValue(
        kind="number", raw=raw, number_raw=num, value=to_float(num), comparator=cmp, unit=unit
    )


def normalize_unit_cell(text: str | None) -> str | None:
    """단위 칸 글자. '-'·빈칸은 단위 없음."""
    if text is None:
        return None
    t = text.strip()
    if re.sub(r"\s+", "", t).lower() in EMPTY_MARKS:
        return None
    return find_unit(t) or t
