"""기업 정보(profile) 형식과 사이트 사실 계산 (docs/ui/ui-contract.md 5절).

profile = {"basic": {...}, "facilities": [...], "products": [...], "facts": {...}}
- 서버가 facilities로 사이트 사실(PROFILE)을 계산한다.
  - 대기·수질·소음진동 배출시설 중 하나라도 있으면 emission_facility = true
  - none(해당 없음)이면 emission_facility = false, waste_facility = false
  - waste_treatment(폐기물 처리시설)이면 waste_facility = true
  - 그 밖에는 키를 넣지 않는다(문진에서 묻는다)
- 사용자가 facts를 직접 보내면 계산값보다 우선한다(고급용). 저장은 보낸 그대로 하고,
  응답(`GET /companies/me` 등)의 profile.facts에는 계산값과 직접 지정값을 합친 값을 낸다.
- 위 네 키 밖의 키(예전 형식의 site 등)는 그대로 저장한다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Facility = Literal["air_emission", "water_emission", "noise_vibration", "waste_treatment", "none"]

FACILITY_LABELS: dict[str, str] = {
    "air_emission": "대기 배출시설",
    "water_emission": "수질 배출시설",
    "noise_vibration": "소음·진동 배출시설",
    "waste_treatment": "폐기물 처리시설",
    "none": "해당 없음",
}
EMISSION_FACILITIES = frozenset({"air_emission", "water_emission", "noise_vibration"})


class ProfileBasic(BaseModel):
    model_config = ConfigDict(extra="allow")

    company_name: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=500)


class CompanyProfile(BaseModel):
    """기업 정보. 모든 키는 선택이다."""

    model_config = ConfigDict(extra="allow")

    basic: ProfileBasic | None = None
    facilities: list[Facility] = []
    products: list[str] = []
    # 사이트 사실 직접 지정(고급용). 카탈로그에 없는 키·맞지 않는 값은 문진 시작 때 건너뛴다.
    facts: dict[str, Any] = {}

    @model_validator(mode="after")
    def _none_is_exclusive(self) -> CompanyProfile:
        if "none" in self.facilities and len(set(self.facilities)) > 1:
            raise ValueError("facilities에 none(해당 없음)과 다른 시설을 함께 보낼 수 없습니다")
        return self

    def stored(self) -> dict[str, Any]:
        """DB에 저장할 형태(보낸 키만)."""
        return self.model_dump(mode="json", exclude_unset=True)


class FacilityOption(BaseModel):
    value: str
    label: str


class ProfileOptions(BaseModel):
    facilities: list[FacilityOption]


def profile_options() -> ProfileOptions:
    return ProfileOptions(
        facilities=[FacilityOption(value=k, label=v) for k, v in FACILITY_LABELS.items()]
    )


def computed_facts(facilities: list[str]) -> dict[str, bool]:
    fac = set(facilities)
    out: dict[str, bool] = {}
    if fac & EMISSION_FACILITIES:
        out["emission_facility"] = True
    elif "none" in fac:
        out["emission_facility"] = False
    if "waste_treatment" in fac:
        out["waste_facility"] = True
    elif "none" in fac:
        out["waste_facility"] = False
    return out


def profile_facts(profile: dict[str, Any] | None) -> dict[str, Any]:
    """저장된 profile → 문진 시작 때 넣을 사이트 사실(계산값 + 직접 지정값, 직접 지정 우선)."""
    profile = profile or {}
    facilities = profile.get("facilities") or []
    if not isinstance(facilities, list):
        facilities = []
    explicit = profile.get("facts") or {}
    if not isinstance(explicit, dict):
        explicit = {}
    return {**computed_facts([str(x) for x in facilities]), **explicit}


def profile_out(profile: dict[str, Any] | None) -> dict[str, Any]:
    """응답용 profile: 저장된 값에 facts만 계산된 값으로 바꾼다."""
    out = dict(profile or {})
    out["facts"] = profile_facts(profile)  # 항상 낸다(비어 있으면 {})
    return out
