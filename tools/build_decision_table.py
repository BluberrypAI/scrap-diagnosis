"""골든 데이터셋 Step 2: 결정 테이블과 테스트 요구사항(TR) 생성.

    uv run python tools/build_decision_table.py          # knowledge/cases/decision_table.yaml 생성
    uv run python tools/build_decision_table.py --check  # 생성물이 최신인지 확인

기준 사실(baseline)에서 변수 하나만 바꾼 케이스를 만들어 각 조건이 혼자서 결과를 바꾸는지(MC/DC),
모든 파티션이 한 번 이상 나오는지(partition coverage)를 덮는다. 경계값, 상위 결론의 마스킹,
판정 불변 속성(메타모픽 관계) 케이스를 더한다. 기대 결과는 tools/cases_spec.py로 계산한다.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cases_spec import CAN_DESIGNATION, evaluate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "knowledge" / "cases" / "decision_table.yaml"

SITE_OFF = {
    "emission_facility": "no",
    "public_facility": "no",
    "daily_avg_kg": 50,
    "construction_5t": "no",
    "site_emits_designated": "no",
}
COMMON = {
    "discharged": "yes",
    "circular_recognized": "no",
    "law_exclusion": "none",
    **SITE_OFF,
    "emission_facility": "yes",
    "physical_state": "solid",
    "oil_presence": "none",
    "oil_pct_evidenced": None,
    "residue": "none",
    "chemical_itself": "no",
}
BASELINES = {
    "PP": {
        **COMMON,
        "material": "pp",
        "input_form": "scrap",
        "foamed": "no",
        "fishery_origin": "none",
        "packaging_used": "no",
    },
    "PE_PACK": {
        **COMMON,
        "material": "pe",
        "input_form": "film",
        "foamed": "no",
        "fishery_origin": "none",
        "packaging_used": "yes",
    },
    "CAN": {
        **COMMON,
        "material": "aluminium",
        "input_form": "can",
        "can_contents": "food_beverage",
        "can_metal": "aluminium",
        "can_designation": {k: "yes" for k in CAN_DESIGNATION} | {"registered": "no"},
    },
}


def tr(kind, base, changes, covers, note=""):
    facts = copy.deepcopy(BASELINES[base])
    for k, v in changes.items():
        if k == "can_designation" and isinstance(v, dict):
            facts["can_designation"] = {**facts.get("can_designation", {}), **v}
        else:
            facts[k] = v
    exp = evaluate(facts)
    item = {
        "kind": kind,
        "base": base,
        "changes": changes,
        "expected": {k: exp[k] for k in ("outcome", "code", "flags")},
        "gate": exp["gate"],
        "covers": covers,
    }
    if note:
        item["note"] = note
    return item


def build() -> list[dict]:
    t: list[dict] = []
    # 기준 케이스
    for b in BASELINES:
        t.append(tr("baseline", b, {}, [f"baseline:{b}"]))

    # 파티션·MC/DC: 기준에서 변수 하나만 바꿈
    single = [
        ("PP", {"discharged": "no"}, "discharged=no"),
        ("PP", {"discharged": "unknown"}, "discharged=unknown"),
        ("PP", {"law_exclusion": "wastewater"}, "law_exclusion=listed"),
        ("PP", {"law_exclusion": "unknown"}, "law_exclusion=unknown"),
        ("PP", {"circular_recognized": "yes"}, "circular_recognized=yes"),
        ("PP", {"physical_state": "liquid"}, "physical_state=nonsolid"),
        ("PP", {"physical_state": "semisolid"}, "physical_state=nonsolid"),
        ("PP", {"physical_state": "unknown"}, "physical_state=unknown"),
        ("PP", {"oil_presence": "present"}, "oil=present_without_evidence"),
        ("PP", {"oil_presence": "unknown"}, "oil=unknown"),
        ("PP", {"residue": "paint_dried_within_6mm"}, "residue=paint_dried_within_6mm"),
        ("PP", {"residue": "paint_other"}, "residue=paint_other"),
        ("PP", {"residue": "other_contents"}, "residue=other_contents"),
        ("PP", {"residue": "unknown"}, "residue=unknown"),
        ("PP", {"chemical_itself": "yes"}, "chemical_itself=yes"),
        ("PP", {"material": "pvc"}, "material=pvc"),
        ("PP", {"material": "other_resin"}, "material=other_resin"),
        ("PP", {"material": "synthetic_rubber"}, "material=synthetic_rubber"),
        ("PP", {"material": "pe"}, "material=pe"),
        ("PP", {"material": "pet", "input_form": "flake"}, "material=pet"),
        ("PP", {"foamed": "yes"}, "foamed=yes"),
        ("PP", {"fishery_origin": "fishing_net"}, "fishery_origin=fishing_net"),
        ("PP", {"fishery_origin": "aquaculture_buoy"}, "fishery_origin=aquaculture_buoy"),
        ("PP", {"packaging_used": "yes"}, "packaging_used=yes"),
        ("PP", {"packaging_used": "yes_excluded"}, "packaging_used=yes_excluded"),
        ("PP", {"packaging_used": "unknown"}, "packaging_used=unknown"),
        ("PE_PACK", {"packaging_used": "no"}, "packaging_used=no(film)"),
        ("CAN", {"material": "aluminium", "input_form": "scrap"}, "input_form=aluminium:scrap"),
        ("CAN", {"material": "steel", "input_form": "scrap"}, "input_form=steel:scrap"),
        ("CAN", {"can_metal": "steel", "material": "steel"}, "can_metal=steel"),
        ("CAN", {"can_contents": "butane"}, "can_contents=listed(butane)"),
        ("CAN", {"can_contents": "other_product"}, "can_contents=other_product"),
        ("CAN", {"can_contents": "excluded_export_return"}, "can_contents=excluded"),
        ("CAN", {"can_contents": "unknown"}, "can_contents=unknown"),
        ("CAN", {"residue": "other_contents"}, "residue=other_contents(can)"),
    ]
    for base, ch, cov in single:
        t.append(tr("mcdc", base, ch, [cov]))

    # 순환자원 지정(AND 7개): 모두 yes → 순환자원, 하나라도 no·unknown → 폐기물
    all_yes = {k: "yes" for k in CAN_DESIGNATION}
    t.append(tr("mcdc", "CAN", {"can_designation": all_yes}, ["can_designation=all_yes"]))
    for k in CAN_DESIGNATION:
        t.append(
            tr("mcdc", "CAN", {"can_designation": all_yes | {k: "no"}}, [f"can_designation.{k}=no"])
        )
    t.append(
        tr(
            "mcdc",
            "CAN",
            {"can_designation": all_yes | {"registered": "unknown"}},
            ["can_designation.registered=unknown"],
        )
    )

    # 사업장 여부(OR 5개): 모두 no → 생활폐기물, 하나만 yes → 사업장
    t.append(tr("mcdc", "PP", dict(SITE_OFF), ["business_site=all_no"]))
    for k, v in [
        ("emission_facility", "yes"),
        ("public_facility", "yes"),
        ("daily_avg_kg", 500),
        ("construction_5t", "yes"),
        ("site_emits_designated", "yes"),
    ]:
        t.append(tr("mcdc", "PP", {**SITE_OFF, k: v}, [f"business_site.{k}=yes"]))
    t.append(
        tr("mcdc", "PP", {**SITE_OFF, "emission_facility": "unknown"}, ["business_site=unknown"])
    )

    # 경계값
    t.append(tr("boundary", "PP", {**SITE_OFF, "daily_avg_kg": 299}, ["daily_avg_kg=299"]))
    t.append(tr("boundary", "PP", {**SITE_OFF, "daily_avg_kg": 300}, ["daily_avg_kg=300"]))
    for pct in (4.9, 5.0):
        t.append(
            tr(
                "boundary",
                "PP",
                {"oil_presence": "present", "oil_pct_evidenced": pct},
                [f"oil_pct_evidenced={pct}"],
            )
        )

    # 마스킹: 상위 결론이 하위 조건을 가림
    masking = [
        ("PP", {"discharged": "no", "oil_presence": "present"}, "NOT_WASTE>DESIGNATED"),
        ("PP", {"circular_recognized": "yes", "material": "pvc"}, "CIRCULAR>OUT_OF_SCOPE"),
        ("PP", {"law_exclusion": "wastewater", "oil_presence": "present"}, "EXCLUDED>DESIGNATED"),
        ("PP", {**SITE_OFF, "material": "pvc"}, "HOUSEHOLD>OUT_OF_SCOPE"),
        ("PP", {"material": "pvc", "oil_presence": "present"}, "DESIGNATED>OUT_OF_SCOPE"),
        ("PP", {"foamed": "yes", "packaging_used": "yes"}, "OUT_OF_SCOPE>GENERAL(foam pack)"),
        ("PP", {"material": "pvc", "packaging_used": "yes"}, "OUT_OF_SCOPE>GENERAL(pvc pack)"),
    ]
    for base, ch, cov in masking:
        t.append(tr("masking", base, ch, [cov]))
    t.append(
        tr(
            "masking",
            "PP",
            {**SITE_OFF, "oil_presence": "present"},
            ["DESIGNATED via 시행령 제2조제6호 (household site + oil)"],
            note="지정폐기물 가능성이면 그 자체로 사업장(제2조제6호)이라 생활폐기물이 되지 않는다",
        )
    )

    # 메타모픽: 판정 불변 형태
    for form in ("rigid", "shredded", "flake", "pellet"):
        t.append(tr("metamorphic", "PP", {"input_form": form}, [f"invariant:pp:scrap→{form}"]))
    t.append(tr("metamorphic", "PP", {"input_form": "film"}, ["counterexample:film_not_packaging"]))
    for form in ("bottle", "bale", "flake"):
        t.append(
            tr(
                "metamorphic",
                "PE_PACK",
                {"material": "pet", "input_form": form},
                [f"invariant:pet_packaging:{form}"],
            )
        )
    t.append(
        tr(
            "metamorphic",
            "PP",
            {"material": "pet", "input_form": "bottle", "packaging_used": "no"},
            ["counterexample:bottle_not_packaging"],
            note="병 제조사의 미사용 불량 병처럼 포장에 쓰이지 않은 병",
        )
    )

    # 판정 조정 이후 추가(번호를 바꾸지 않도록 맨 끝에 붙임)
    t.append(tr("mcdc", "PP", {"material": "other"}, ["material=other"]))

    # v2 보강(2026-11-20): 뮤테이션 테스팅에서 살아남은 변형을 잡는 케이스.
    # 목록 기반 규칙은 항목 하나 누락이 흔한 구현 결함이라 항목마다 케이스를 둔다.
    for v in (
        "radioactive",
        "uncontained_gas",
        "livestock_manure",
        "sewage_nightsoil",
        "livestock_disease",
        "aquatic_disease",
        "ammunition",
        "pet_funeral",
        "fishery_byproduct_unmixed",
    ):
        t.append(tr("enumeration", "PP", {"law_exclusion": v}, [f"law_exclusion={v}"]))
    for v in (
        "agri_product",
        "detergent",
        "cosmetics",
        "medicine",
        "insecticide",
        "clothing",
        "paper_product",
        "rubber_glove",
    ):
        ch = {"can_contents": v, **({"medicine_small": "no"} if v == "medicine" else {})}
        t.append(tr("enumeration", "CAN", ch, [f"can_contents={v}"]))
    t.append(tr("mcdc", "PP", {"material": "pe", "foamed": "yes"}, ["foamed=yes(pe)"]))
    t.append(
        tr(
            "mcdc",
            "PP",
            {"material": "pet", "input_form": "flake", "foamed": "yes"},
            ["foamed=yes(pet)"],
        )
    )
    t.append(
        tr(
            "masking",
            "CAN",
            {
                "can_contents": "other_product",
                "can_designation": dict.fromkeys(CAN_DESIGNATION, "yes"),
            },
            ["designation_requires_listed_can"],
            note="제18조 품목이 아닌 캔은 준수사항을 모두 지켜도 지정 순환자원(폐금속캔류)이"
            " 아니다",
        )
    )

    # v3 판정 조정(2026-11-20, D14): 소용량 의약품 캔
    for v, cov in (("yes", "medicine_small=yes"), ("unknown", "medicine_small=unknown")):
        t.append(tr("mcdc", "CAN", {"can_contents": "medicine", "medicine_small": v}, [cov]))

    for i, item in enumerate(t, 1):
        item["id"] = f"TR-{i:03d}"
    return [{"id": x.pop("id"), **x} for x in t]


def render(trs: list[dict]) -> str:
    kinds: dict[str, int] = {}
    outcomes: dict[str, int] = {}
    for x in trs:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
        o = x["expected"]["outcome"]
        outcomes[o] = outcomes.get(o, 0) + 1
    doc = {
        "version": 1,
        "procedure": [
            "G1 discharged: no→NOT_WASTE, unknown→INSUFFICIENT_INFO",
            "G2 circular_recognized=yes → CIRCULAR_RESOURCE",
            "G3 can + 제18조 품목 + 지정 준수사항 7개 모두 yes → CIRCULAR_RESOURCE",
            "G4 law_exclusion: 해당→EXCLUDED, unknown→INSUFFICIENT_INFO",
            "G5 business_site: 하나라도 yes→통과, 모두 no→HOUSEHOLD, 그 외→INSUFFICIENT_INFO"
            " (지정 가능성이면 제2조제6호로 사업장)",
            "G6 chemical_itself·residue·oil 중 하나라도 → DESIGNATED_POSSIBLE",
            "G7 PVC·기타수지·발포·어망·부표·비캔 금속·비고체·제18조 외 캔 → OUT_OF_SCOPE",
            "G8 캔→51-29-03(철은 route_unsupported),"
            " 포장재→51-03-07(interpretation), 아니면 51-03-01",
        ],
        "baselines": BASELINES,
        "summary": {"total": len(trs), "by_kind": kinds, "by_outcome": outcomes},
        "test_requirements": trs,
    }
    header = (
        "# 자동 생성: tools/build_decision_table.py — 직접 고치지 않는다.\n"
        "# 골든 데이터셋 Step 2: 결정 테이블과 테스트 요구사항(TR).\n"
        "# 기대 결과는 명세 오라클(tools/cases_spec.py)로 계산한다.\n"
    )
    return header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100)


def main() -> None:
    text = render(build())
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            sys.exit("decision_table.yaml이 최신이 아닙니다. 다시 생성하세요.")
        print("decision_table.yaml 최신")
        return
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"생성: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
