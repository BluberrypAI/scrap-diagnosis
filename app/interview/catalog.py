"""사실 카탈로그(knowledge/flow/facts.yaml) 도우미: 값 검증, 라벨, 선택지."""

from __future__ import annotations

from typing import Any

from app.engine.flow import norm

BOOL3_LABELS = {"yes": "예", "no": "아니요", "unknown": "모름"}


class FactValueError(ValueError):
    def __init__(self, key: str, value: Any, reason: str) -> None:
        super().__init__(reason)
        self.key, self.value, self.reason = key, value, reason


def spec(catalog: dict[str, dict], path: str) -> dict | None:
    """사실 경로(예: material, can_designation.registered)의 정의. 없으면 None."""
    base, _, sub = path.partition(".")
    f = catalog.get(base)
    if f is None:
        return None
    if f["type"] == "object":
        if not sub or sub not in f["fields"]:
            return None
        return {"id": path, "label": f["fields"][sub], "type": f.get("field_type", "bool3")}
    return None if sub else f


def all_paths(catalog: dict[str, dict]) -> list[str]:
    out = []
    for fid, f in catalog.items():
        if f["type"] == "object":
            out += [f"{fid}.{k}" for k in f["fields"]]
        else:
            out.append(fid)
    return out


def value_map(s: dict) -> dict[str, str]:
    """선택지 값 → 라벨(모름 포함)."""
    if s["type"] == "bool3":
        return dict(BOOL3_LABELS)
    if s["type"] == "enum":
        return {str(norm(k)): v for k, v in s["values"].items()}
    return {}


def allows_unknown(s: dict) -> bool:
    if s["type"] in ("bool3", "number"):
        return True
    return "unknown" in value_map(s)


def validate(catalog: dict[str, dict], path: str, value: Any) -> Any:
    """답 값을 저장 형식으로 바꾼다. 틀리면 FactValueError. 'unknown'은 그대로 돌려준다."""
    s = spec(catalog, path)
    if s is None:
        raise FactValueError(path, value, "카탈로그에 없는 사실")
    if value is None or (isinstance(value, str) and value.strip() in ("", "-")):
        raise FactValueError(path, value, "빈 값")
    value = norm(value)
    if value == "unknown":
        if not allows_unknown(s):
            raise FactValueError(path, value, "'모름'을 받지 않는 사실")
        return "unknown"
    if s["type"] == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise FactValueError(path, value, "숫자가 아님")
        if "min" in s and value < s["min"]:
            raise FactValueError(path, value, f"{s['min']}보다 작음")
        if "max" in s and value > s["max"]:
            raise FactValueError(path, value, f"{s['max']}보다 큼")
        return value
    if str(value) not in value_map(s):
        raise FactValueError(path, value, "선택지 밖 값")
    return str(value)


def value_label(catalog: dict[str, dict], path: str, value: Any) -> str:
    s = spec(catalog, path)
    if s is None or value is None:
        return str(value)
    if value == "unknown":
        return "모름"
    if s["type"] == "number":
        unit = s.get("unit") or ""
        return f"{value}{unit}"
    return value_map(s).get(str(norm(value)), str(value))


def options(catalog: dict[str, dict], path: str, allowed: list[str] | None = None) -> list[dict]:
    """질문 카드 선택지. 값 버튼 + (받으면) 모름 버튼."""
    s = spec(catalog, path)
    if s is None:
        return []
    out = []
    for v, label in value_map(s).items():
        if v == "unknown" or (allowed is not None and v not in allowed):
            continue
        out.append({"label": label, "value": v, "kind": "value"})
    if allows_unknown(s):
        out.append({"label": "모름", "value": None, "kind": "unknown"})
    return out


def input_kind(s: dict) -> str:
    return "number" if s["type"] == "number" else "choice"


def value_type(s: dict) -> str:
    return {"bool3": "bool", "enum": "enum", "number": "number"}.get(s["type"], s["type"])
