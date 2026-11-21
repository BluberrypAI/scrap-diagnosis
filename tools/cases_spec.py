"""명세 오라클(spec oracle): knowledge/cases/input_model.yaml의 게이트 순서를 그대로 옮긴 함수.

골든 데이터셋의 기대 결과를 계산하는 데만 쓴다. 판정 엔진은 이 모듈을 import하지 않는다
(엔진을 이 코드에 맞춰 만들면 골든셋이 독립적인 테스트 오라클이 아니게 된다).

게이트는 위에서부터 순서대로 평가한다. 게이트에서 결론이 나면 바로 끝내고,
게이트를 통과할 정보가 없으면 INSUFFICIENT_INFO로 끝낸다.
"""

from __future__ import annotations

EXCLUSIONS = {
    "radioactive",
    "uncontained_gas",
    "wastewater",
    "livestock_manure",
    "sewage_nightsoil",
    "livestock_disease",
    "aquatic_disease",
    "ammunition",
    "pet_funeral",
    "fishery_byproduct_unmixed",
}
CAN_LISTED = {
    "food_beverage",
    "agri_product",
    "detergent",
    "cosmetics",
    "medicine",
    "butane",
    "insecticide",
    "clothing",
    "paper_product",
    "rubber_glove",
}
CAN_DESIGNATION = (
    "foreign_matter_le_2pct",
    "unmixed",
    "compressed",
    "compress_facility_ok",
    "sorted_by_metal",
    "registered",
    "supplied_r41",
)
PLASTICS = {"pp", "pe", "pet"}


def result(outcome: str, code: str | None = None, flags: list[str] | None = None, gate: str = ""):
    return {"outcome": outcome, "code": code, "flags": flags or [], "gate": gate}


def designated_triggers(f: dict) -> list[str]:
    hits = []
    if f.get("chemical_itself") == "yes":
        hits.append("chemical_itself")
    if f.get("residue") in ("paint_other", "other_contents", "unknown"):
        hits.append("residue")
    oil = f.get("oil_presence")
    pct = f.get("oil_pct_evidenced")
    if oil == "unknown" or (oil == "present" and (pct is None or pct >= 5)):
        hits.append("oil")
    return hits


def is_can(f: dict) -> bool:
    return f.get("input_form") == "can"


def evaluate(f: dict) -> dict:
    # G1 폐기물 여부
    if f.get("discharged") == "no":
        return result("NOT_WASTE", gate="G1")
    if f.get("discharged") != "yes":
        return result("INSUFFICIENT_INFO", gate="G1")

    # G2 순환자원(인정)
    if f.get("circular_recognized") == "yes":
        return result("CIRCULAR_RESOURCE", gate="G2")
    # G3 순환자원(지정: 폐금속캔류, 준수사항 모두 충족)
    medicine_ok = f.get("can_contents") != "medicine" or f.get("medicine_small") == "no"
    if is_can(f) and f.get("can_contents") in CAN_LISTED and medicine_ok:
        d = f.get("can_designation") or {}
        if all(d.get(k) == "yes" for k in CAN_DESIGNATION):
            return result("CIRCULAR_RESOURCE", gate="G3")

    # G4 적용 제외
    exclusion = f.get("law_exclusion")
    if exclusion in EXCLUSIONS:
        return result("EXCLUDED", gate="G4")
    if exclusion != "none":
        return result("INSUFFICIENT_INFO", gate="G4")

    # G5 사업장 여부 (지정폐기물 가능성이면 그 자체로 사업장: 시행령 제2조제6호)
    designated = designated_triggers(f)
    daily = f.get("daily_avg_kg")
    site = [
        f.get("emission_facility"),
        f.get("public_facility"),
        None if daily is None else ("yes" if daily >= 300 else "no"),
        f.get("construction_5t"),
        "yes" if designated else f.get("site_emits_designated"),
    ]
    if "yes" not in site:
        if all(s == "no" for s in site):
            return result("HOUSEHOLD", gate="G5")
        return result("INSUFFICIENT_INFO", gate="G5")

    # G6 지정폐기물 가능성
    if designated:
        return result("DESIGNATED_POSSIBLE", gate="G6")

    # G7 범위
    material = f.get("material")
    out = None  # 범위 밖이면 후보 코드("" = 후보 없음)
    packaging_yes = f.get("packaging_used") == "yes"
    if material == "pvc":
        # D13: PVC 포장재는 51-03-03과 51-03-07이 겹쳐 후보 코드를 정하지 않는다
        out = "" if packaging_yes else "51-03-03"
    elif material == "other_resin":
        out = "51-03-01"
    elif material == "synthetic_rubber":
        out = "51-03-02"
    elif material == "other":
        out = ""
    elif material in ("aluminium", "steel") and f.get("input_form") not in ("can", "scrap"):
        # D18: 금속 스크랩만 범위 안. 그 밖의 형태는 용기류(51-29-04)일 수 있어 범위 밖으로 둔다
        out = "51-29-02" if material == "aluminium" else "51-29-01"
    elif material in PLASTICS and f.get("foamed") == "yes":
        # D13: 발포 포장재는 51-03-06과 51-03-07이 겹쳐 후보 코드를 정하지 않는다
        out = "" if packaging_yes else "51-03-06"
    elif material in PLASTICS and f.get("fishery_origin") == "fishing_net":
        out = "51-03-08"
    elif material in PLASTICS and f.get("fishery_origin") == "aquaculture_buoy":
        out = "51-03-05"
    elif is_can(f) and f.get("can_contents") in ("other_product", "excluded_export_return"):
        out = "51-29-04"
    elif is_can(f) and f.get("can_contents") == "medicine" and f.get("medicine_small") == "yes":
        # D14: 내용량 30mL(30g) 이하 의약품 캔은 제18조제1호 마목에서 제외
        out = "51-29-04"
    if out is not None:
        return result("OUT_OF_SCOPE", code=out or None, gate="G7")
    if f.get("physical_state") in ("liquid", "semisolid"):
        return result("OUT_OF_SCOPE", gate="G7")
    if f.get("physical_state") != "solid" or material is None:
        return result("INSUFFICIENT_INFO", gate="G7")

    # G8 코드
    if f.get("input_form") == "scrap" and material in ("aluminium", "steel"):
        # D18: 고철(51-29-01)·비철금속(51-29-02). 지정 순환자원 준수사항은 묻지 않고 폐기물로 본다
        code = "51-29-02" if material == "aluminium" else "51-29-01"
        return result("GENERAL", code, ["circular_designation_assumed"], gate="G8")
    if is_can(f):
        if f.get("can_contents") not in CAN_LISTED or not medicine_ok:
            return result("INSUFFICIENT_INFO", gate="G8")
        flags = ["route_unsupported"] if f.get("can_metal") == "steel" else []
        return result("GENERAL", "51-29-03", flags, gate="G8")
    packaging = f.get("packaging_used")
    if packaging == "yes":
        return result("GENERAL", "51-03-07", ["interpretation"], gate="G8")
    if packaging in ("yes_excluded", "no"):
        return result("GENERAL", "51-03-01", gate="G8")
    return result("INSUFFICIENT_INFO", gate="G8")
