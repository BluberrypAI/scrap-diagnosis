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
        # 부피 기준이 mL인 표기(2026-11-12): 1 mg/mL = 1000 mg/L. 환산했다고 메모에 남긴다
        "mg/ml": UnitRule(1000),
        "μg/ml": UnitRule(1),
        "ug/ml": UnitRule(1),
        # 같은 질량/부피 단위의 접두어만 다른 표기(2026-11-13). 밀도가 필요한 환산은 넣지 않는다
        "ng/ml": UnitRule(0.001),
        "ng/l": UnitRule(0.000001),
        "mg/dl": UnitRule(10),
        "μg/dl": UnitRule(0.01),
        "ug/dl": UnitRule(0.01),
        "g/ml": UnitRule(1_000_000),
        "ppm": UnitRule(1, assumed=True),
    },
    "%": {
        "%": UnitRule(1),
        "wt%": UnitRule(1),
        "중량%": UnitRule(1),
        "%(w/w)": UnitRule(1),
        "mg/kg": UnitRule(0.0001),
        # 질량/질량 표기(2026-11-13): 1 g/kg = 0.1 %, 1 mg/g = 0.1 %, 1 μg/g = 1 mg/kg
        "g/kg": UnitRule(0.1),
        "mg/g": UnitRule(0.1),
        "μg/g": UnitRule(0.0001),
        "ug/g": UnitRule(0.0001),
        "μg/kg": UnitRule(0.0000001),
        "ug/kg": UnitRule(0.0000001),
        "g/100g": UnitRule(1),
        "ppm": UnitRule(0.0001, assumed=True),
    },
}

UNIT_TOKEN_RE = re.compile(
    # 질량(g·mg·㎎·μg·ug·ng) / 부피(L·mL·dL) 또는 질량(kg·g·100g).
    # 뒤에 영문자가 이어지면 다른 단위다(예: mg/m3는 잡지 않음).
    r"((?:[mμµun]?g|㎎)\s*/\s*(?:100\s*g|kg|g|[md]?[lℓL])(?![a-zA-Z])|ppm|ppb|wt\s*%|중량\s*%|%)",
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
