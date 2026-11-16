"""별표 4의3의 등재 유형 조회. 분류 판정·사업장 허가 판정과 구분한다."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, StringConstraints

RCode = Annotated[str, StringConstraints(pattern=r"^R-\d+(?:-\d+)*$")]


class RecyclingTypes(BaseModel):
    free: list[RCode] = Field(default_factory=list)
    analysis: list[RCode] = Field(default_factory=list)
    unmarked: list[RCode] = Field(default_factory=list)


class RecyclingAssessment(BaseModel):
    contract: Literal["recycling-types-v1"] = "recycling-types-v1"
    case_id: str
    verdict_version: int
    waste_code: str | None
    as_of: str
    status: Literal["table_listed", "not_applicable", "not_covered", "out_of_date"]
    types: RecyclingTypes = Field(default_factory=RecyclingTypes)
    version: str | None = None
    checksum: str | None = None
    source: dict = Field(default_factory=dict)
    pages: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    facility_permit_verified: Literal[False] = False


def load_registry(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    date.fromisoformat(data["valid_from"])
    for row in data["rows"].values():
        RecyclingTypes.model_validate(row["types"])
    data["checksum"] = hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return data


def assess_recycling(registry: dict, handoff: dict) -> RecyclingAssessment:
    as_of = str((handoff.get("timestamps") or {}).get("as_of") or "")
    result = RecyclingAssessment(
        case_id=handoff["case_id"],
        verdict_version=handoff["verdict_version"],
        waste_code=handoff.get("waste_code"),
        as_of=as_of,
        status="not_applicable",
    )
    if (
        handoff.get("category") != "GENERAL"
        or handoff.get("result_type") != "WASTE_CODE"
        or (handoff.get("route_guidance") or {}).get("action") != "RECOMMEND_ROUTE"
    ):
        return result
    result.status = "not_covered"
    if not registry:
        return result
    result.version = registry["version"]
    result.checksum = registry["checksum"]
    result.source = registry["source"]
    result.notes = registry["notes"]
    try:
        valid = date.fromisoformat(as_of) >= date.fromisoformat(registry["valid_from"])
    except ValueError:
        valid = False
    if not valid:
        result.status = "out_of_date"
        return result
    row = registry["rows"].get(result.waste_code)
    if row:
        result.status = "table_listed"
        result.types = RecyclingTypes.model_validate(row["types"])
        result.pages = row["pages"]
    return result
