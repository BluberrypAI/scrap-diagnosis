"""단위 정규화(계약 docs/document-extraction-contract.md §5 "단위 정규화" 표 중 시험성적서 부분).

표에 없는 단위는 환산하지 않는다(None). 값을 지어내서 맞추지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class UnitRule:
    factor: float
    assumed: bool = False  # ppm처럼 시료 상태를 가정한 환산(경고 UNIT_ASSUMED)


def _norm(unit: str) -> str:
    u = unit.strip().replace(" ", "").replace("㎎", "mg").replace("ℓ", "L").replace("µ", "μ")
    return u.lower()


# 카탈로그 단위 → {서류 표기(정규화) → 규칙}
_RULES: dict[str, dict[str, UnitRule]] = {
    "mg/L": {
        "mg/l": UnitRule(1),
        "μg/l": UnitRule(0.001),
        "ug/l": UnitRule(0.001),
        "ppb": UnitRule(0.001, assumed=True),
        "g/l": UnitRule(1000),
        "ppm": UnitRule(1, assumed=True),
    },
    "%": {
        "%": UnitRule(1),
        "wt%": UnitRule(1),
        "중량%": UnitRule(1),
        "%(w/w)": UnitRule(1),
        "mg/kg": UnitRule(0.0001),
        "ppm": UnitRule(0.0001, assumed=True),
    },
}

UNIT_TOKEN_RE = re.compile(
    r"(mg\s*/\s*[lℓL]|㎎\s*/\s*[lℓL]|[μµu]g\s*/\s*[lℓL]|g\s*/\s*[lℓL]|mg\s*/\s*kg|ppm|ppb|wt\s*%|중량\s*%|%)",
    re.IGNORECASE,
)


def find_unit(text: str) -> str | None:
    """글자 안의 단위 표기(처음 것). 없으면 None."""
    m = UNIT_TOKEN_RE.search(text or "")
    return m.group(1) if m else None


def unit_rule(unit_raw: str | None, target: str | None) -> UnitRule | None:
    """서류 단위 → 카탈로그 단위 환산 규칙. 단위 없는 사실(pH)은 unit_raw가 없어야 한다."""
    if target is None:
        return UnitRule(1) if not unit_raw else None
    if not unit_raw:
        return None
    return _RULES.get(target, {}).get(_norm(unit_raw))


def convert(value: float, unit_raw: str | None, target: str | None) -> float | None:
    rule = unit_rule(unit_raw, target)
    if rule is None:
        return None
    return value * rule.factor
