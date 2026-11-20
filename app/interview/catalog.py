"""사실 카탈로그(knowledge/flow/facts.yaml) 도우미: 값 검증, 라벨, 선택지."""

from __future__ import annotations

from typing import Any

from app.engine.flow import norm
from app.engine.ranges import NumRange

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


def is_document_fact(catalog: dict[str, dict], path: str) -> bool:
    """서류로만 값을 받는 사실(facts.yaml source: document)."""
    s = spec(catalog, path)
    return bool(s and s.get("source") == "document")


def _range(path: str, value: dict, s: dict) -> dict:
    """서류의 구간 값({lo, lo_inc, hi, hi_inc}: '0.5 미만', 불검출)을 검사해 저장 형식으로."""
    if not set(value) <= {"lo", "lo_inc", "hi", "hi_inc"} or not ({"lo", "hi"} & set(value)):
        raise FactValueError(path, value, "구간 형식이 아님")
    out = {}
    for k in ("lo", "hi"):
        v = value.get(k)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, int | float):
            raise FactValueError(path, value, "구간 끝이 숫자가 아님")
        if ("min" in s and v < s["min"]) or ("max" in s and v > s["max"]):
            raise FactValueError(path, value, "구간이 값 범위를 벗어남")
        out[k] = v
        out[f"{k}_inc"] = bool(value.get(f"{k}_inc", k == "lo"))
    if "lo" in out and "hi" in out and out["lo"] > out["hi"]:
        raise FactValueError(path, value, "하한이 상한보다 큼")
    return out


def validate(catalog: dict[str, dict], path: str, value: Any, *, allow_range: bool = False) -> Any:
    """답 값을 저장 형식으로 바꾼다. 틀리면 FactValueError. 'unknown'은 그대로 돌려준다.

    allow_range: 서류 값만 구간({hi: 0.5, hi_inc: false} 등)을 받는다.
    """
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
    if s["type"] == "number" and isinstance(value, dict):
        if not allow_range:
            raise FactValueError(path, value, "구간 값은 서류로만 받음")
        return _range(path, value, s)
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
        if isinstance(value, dict):
            return NumRange(**value).label(unit)
        return f"{value:g}{unit}" if isinstance(value, float) else f"{value}{unit}"
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
