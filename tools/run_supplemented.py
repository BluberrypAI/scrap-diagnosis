"""실제 질의회신 사례에 '가정 상황'을 붙여 끝까지 돌려 보는 시험.

사례 원문에 있는 사실(case_facts)은 그대로 두고, 판정에 필요하지만 원문에 없는 사실은 assumed에 이유와 함께 채운다.
기관 답(expected)과 계산기 결과를 단계별로 비교한다. 가정이 결과를 좌우하는 경우는 variant로 값을 바꿔 다시 돌린다.
실행: python tools/run_supplemented.py   → testdata/supplemented_report.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wastecalc import evaluate, load_kb  # noqa: E402

KB = load_kb()
OUT = ROOT / "testdata" / "supplemented_report.md"

# 공통 가정: 사업활동에서 나와 내보내는 폐기물, 재투입·순환자원 아님, 다른 법 대상 아님, 배출시설 있는 공장
BASE = {"no_longer_needed": True, "direct_reinput": False, "continuous_feedstock": False, "circular_resource_recognized": False,
        "law_exclusion": "none", "emission_facility": True}
NO_GATES = {"oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": False, "designated_residue": False}
LOW_LEACH = {f"leach_{s}": 0 for s in ("pb", "cu", "as", "hg", "cd", "cr6", "cn", "op", "pce", "tce")}

S = [
    # ---------------- S0 폐기물 해당 여부
    dict(id="MOE25-234", title="미강(쌀겨)을 사료 원료로", expected={"S0": "WASTE"},
         facts={"no_longer_needed": True, "direct_reinput": False, "continuous_feedstock": False, "circular_resource_recognized": False},
         assumed="도정 공장에서 필요 없게 된 부산물로 다른 업체에 넘김(회신 전제)"),
    dict(id="GUIDE23-133-01", title="납품용 목재 팔레트를 수거해 같은 용도로 반복 사용", expected={"S0": "NOT_WASTE"},
         facts={"no_longer_needed": False, "circular_resource_recognized": False},
         assumed="팔레트를 계속 운반 용도로 쓰므로 '아직 필요한 물건'으로 답함"),
    dict(id="COURT-2001도70", title="필요 없게 된 물질을 재활용 원료로 공급", expected={"S0": "WASTE"},
         facts={"no_longer_needed": True, "direct_reinput": False, "continuous_feedstock": False, "circular_resource_recognized": False},
         assumed="재투입·순환자원 인정 없음"),
    dict(id="GUIDE23-050-02", title="동제련 슬래그를 밀폐 연속공정으로 시멘트·골재 원료에 투입", expected={"S0": "NOT_WASTE"},
         facts={"no_longer_needed": True, "direct_reinput": False, "continuous_feedstock": True,
                "circular_resource_recognized": False},
         assumed="발생시설에서 별도 가공 없이 연속공정으로 시멘트·골재 공정에 투입(질의 전제)"),
    # ---------------- S2 사업장폐기물 여부
    dict(id="HWP08-M-1-04", title="가정 방문 간호에서 나온 의료폐기물", expected={"S2": "HOUSEHOLD"},
         facts={**{k: BASE[k] for k in ("no_longer_needed", "direct_reinput", "continuous_feedstock",
                                        "circular_resource_recognized", "law_exclusion")},
                "emission_facility": False, "public_facility": "none", "waste_facility": False,
                "designated_waste_emitted": False, "daily_avg_kg": 1, "work_type": "none",
                "waste_kind": "medical", "medical_institution": False, "physical_state": "solid", **NO_GATES},
         assumed="가정(재택)에서 발생, 하루 1kg. 사용자가 종류를 '의료폐기물'로 고름"),
    # ---------------- S3 지정폐기물 여부
    dict(id="WONJU26-52", title="크롬산 폐수 pH 2", expected={"S3": "DESIGNATED"},
         facts={**BASE, "waste_kind": "acid", "physical_state": "liquid", "ph": 2, **NO_GATES},
         assumed="수질오염방지시설로 보내지 않고 위탁(=폐기물관리법 적용)"),
    dict(id="WONJU26-18", title="폐유가 조금 남은 드럼통", expected={"S3": "DESIGNATED"},
         facts={**BASE, "waste_kind": "other", "physical_state": "solid", "oil_presence": "present",
                "oil_content_pct": 10, "pcb_possible": False, "toxic_chemical_discard": False, "designated_residue": False},
         assumed="금속 드럼이라 종류 '그 밖', 기름성분 10%로 가정",
         variant={"oil_content_pct": "UNKNOWN"}),
    dict(id="WONJU26-62", title="유기용제가 바닥에 묻은 빈 드럼", expected={"S3": "DESIGNATED"},
         facts={**BASE, "waste_kind": "other", "physical_state": "solid", **NO_GATES,
                "designated_residue": True, "residue_kind": "organic_solvent"},
         assumed="사용자가 '빈 금속 드럼'이라 종류를 '그 밖'으로 답함. 잔류물 질문에 '유기용제가 남아 있음'",
         variant={"designated_residue": False}, variant_note="사용자가 잔류물을 '없음'으로 잘못 답한 경우(입력 오류 시연)"),
    dict(id="HWP08-D-1-02", title="과산화수소(pH 2.5)가 묻은 PE 용기", expected={"S3": "DESIGNATED"},
         facts={**BASE, "waste_kind": "synthetic_resin", "physical_state": "solid", **NO_GATES,
                "designated_residue": True, "residue_kind": "toxic_chemical"},
         assumed="빈 플라스틱 용기. 잔류물 질문에 '유해화학물질(과산화수소)이 묻어 있음'",
         variant={"designated_residue": False}, variant_note="사용자가 잔류물을 '없음'으로 잘못 답한 경우(입력 오류 시연)"),
    dict(id="HWP08-D-1-01", title="철거한 슬레이트(석면 1% 이상) — 2008년 회신", expected={"S3": "NOT_DESIGNATED"},
         facts={**BASE, "waste_kind": "asbestos_demolition", "physical_state": "solid", "asbestos_pct": 5, **NO_GATES},
         assumed="석면 5%. 회신 당시(2008) 법령 기준 답"),
    dict(id="HWP08-D-1-16", title="지붕 슬레이트 폐석면", expected={"S3": "DESIGNATED"},
         facts={**BASE, "waste_kind": "asbestos_demolition", "physical_state": "solid", "asbestos_pct": 5, **NO_GATES},
         assumed="석면 5%"),
    dict(id="HWP08-D-1-04", title="변전실 변압기 절연유", expected={"S3": "DESIGNATED"},
         facts={**BASE, "waste_kind": "waste_oil", "physical_state": "liquid", "oil_presence": "present",
                "pcb_possible": False, "toxic_chemical_discard": False, "designated_residue": False},
         assumed="PCB 분석 결과 기준 미만으로 확인됨"),
    dict(id="HWP08-D-1-06", title="건설오니·도로청소 폐토사", expected={"S3": "NOT_DESIGNATED"},
         facts={**BASE, "waste_kind": "other", "physical_state": "solid", **NO_GATES},
         assumed="기름·PCB·유해화학물질 없음"),
    dict(id="HWP08-D-1-15", title="압수된 유사석유제품", expected={"S3": "DESIGNATED"},
         facts={**BASE, "waste_kind": "waste_oil", "physical_state": "liquid", "oil_presence": "present",
                "pcb_possible": False, "toxic_chemical_discard": False, "designated_residue": False},
         assumed="연료유로 보고 종류 '폐유'를 고름"),
    dict(id="HWP08-M-1-08", title="혈액이 든 채혈 튜브(병원)", expected={"S3": "DESIGNATED"},
         facts={**{k: BASE[k] for k in ("no_longer_needed", "direct_reinput", "continuous_feedstock",
                                        "circular_resource_recognized", "law_exclusion")},
                "emission_facility": False, "work_type": "none", "daily_avg_kg": 50,
                "waste_kind": "medical", "medical_institution": True, "physical_state": "solid", **NO_GATES},
         assumed="배출시설 없는 의원, 하루 50kg"),
    # ---------------- S4·S5 분류번호와 재활용
    dict(id="REC17-008-2", title="폐축전지 분리 시 나온 폐황산", expected={"S3": "DESIGNATED", "S4": "02-01-02",
                                                                   "S5": "ALLOWED_TYPES"},
         facts={**BASE, "waste_kind": "acid", "physical_state": "liquid", "ph": 0.5, **NO_GATES, "code": "02-01-02"},
         assumed="pH 0.5, 사용자가 폐황산 번호를 고름"),
    dict(id="WONJU26-63", title="다른 성분을 함유한 폐황산", expected={"S4": "02-01-02"},
         facts={**BASE, "waste_kind": "acid", "physical_state": "liquid", "ph": 1, **NO_GATES, "code": "02-01-02"},
         assumed="pH 1"),
    dict(id="WONJU26-56-Q3", title="인산·과산화수소 등 혼합 폐산", expected={"S4": "02-01-99"},
         facts={**BASE, "waste_kind": "acid", "physical_state": "liquid", "ph": 1, **NO_GATES, "code": "02-01-99",
                "no_specific_code_applies": True},
         assumed="pH 1, 염산·황산·질산·불산·LCD 폐산에 해당하지 않음"),
    dict(id="HWP08-D-1-11", title="기름공장의 폐흡착제", expected={"S4": "03-08-01"},
         facts={**BASE, "waste_kind": "adsorbent", "physical_state": "solid", "oil_presence": "present",
                "oil_content_pct": 20, "pcb_possible": False, "toxic_chemical_discard": False, **LOW_LEACH,
                "code": "03-08-01"},
         assumed="기름성분 20%, 용출 물질은 기준 미만"),
    dict(id="GUIDE23-120-01", title="용접잔재물(지정폐기물 아님)", expected={"S4": "51-04-99"},
         facts={**BASE, "waste_kind": "slag", "physical_state": "solid", "blast_furnace_iron_slag": False, **NO_GATES,
                **{k: v for k, v in LOW_LEACH.items() if k in ("leach_pb", "leach_cu", "leach_as", "leach_hg",
                                                              "leach_cd", "leach_cr6", "leach_cn")},
                "oil_content_pct": 0, "code": "51-04-99", "no_specific_code_applies": True},
         assumed="용출 기준 미만"),
    dict(id="GUIDE23-129-01", title="사골 국물에서 분리한 기름", expected={"S4": "51-16-00"},
         facts={**BASE, "waste_kind": "edible_oil", "physical_state": "liquid", "oil_presence": "present",
                "oil_content_pct": 90, "pcb_possible": False, "toxic_chemical_discard": False, "designated_residue": False},
         assumed="식품 공장(배출시설 있음)"),
    dict(id="REC17-007-2", title="시멘트 제조공정 분진", expected={"S4": "51-05-02", "S5": "ALLOWED_TYPES"},
         facts={**BASE, "waste_kind": "dust", "physical_state": "solid", "dust_from_apc": True,
                "dust_from_incinerator": False, **NO_GATES,
                **{k: v for k, v in LOW_LEACH.items() if k in ("leach_pb", "leach_cu", "leach_as", "leach_hg",
                                                              "leach_cd", "leach_cr6", "leach_cn")},
                "code": "51-05-02"},
         assumed="집진기 포집 분진, 용출 기준 미만"),
    dict(id="REC17-006-2", title="교량 철거 EPS 블록", expected={"S4": "51-03-06", "S5": "ALLOWED_TYPES"},
         facts={**BASE, "waste_kind": "synthetic_resin", "physical_state": "solid", **NO_GATES, "code": "51-03-06"},
         assumed="(건설 현장이지만) 사업장폐기물로 가정"),
    dict(id="REC17-006-1", title="전자제품 공장의 폐수처리오니", expected={"S4": "51-01-08", "S5": "ALLOWED_TYPES"},
         facts={**BASE, "waste_kind": "sludge_wastewater", "physical_state": "semisolid",
                "sludge_facility_notified": False, **NO_GATES, "code": "51-01-08", "no_specific_code_applies": True},
         assumed="고시된 오니 발생시설 아님, 유기성"),
    dict(id="REC17-039-1", title="굴·바지락 패각 — 2016년 회신", expected={"S4": "51-17-04", "S5": "RESTRICTED"},
         facts={**BASE, "waste_kind": "other", "physical_state": "solid", **NO_GATES,
                "general_group": "51-17", "code": "51-17-04"},
         assumed="수산물 가공 공장. 회신 당시(2016) 법령 기준 답"),
]


def run(facts: dict) -> dict:
    return evaluate(facts, strict=False, kb=KB)


def compare(exp: dict, r: dict, facts: dict | None = None) -> dict:
    got = {d["stage"]: d["conclusion"] for d in r["decided"]}
    ref = None
    if r.get("reason") == "INTERPRETATION_NEEDED" and r.get("consult") and facts is not None:
        ref = {d["stage"]: d["conclusion"] for d in evaluate(facts, strict=False, kb=KB, allow_interpretive=True)["decided"]}
    out = {}
    for stage, want in exp.items():
        have = got.get(stage)
        if have is None and ref is not None and ref.get(stage) is not None:
            # 해석 근거라 계산기가 결론 대신 문의 안내 — 참고 결론이 기관 답과 같은지 함께 표시
            out[stage] = ("CONSULT" + ("(참고 일치)" if ref[stage] == want else "(참고 불일치)"),
                          f"문의 안내 — 참고 결론 {ref[stage]}")
        elif have is None:
            out[stage] = ("STOPPED", f"{r['status']} at {r.get('stage')}")
        elif stage == "S4":
            out[stage] = ("CORRECT" if have == want else "WRONG", have)
        elif stage == "S5":
            out[stage] = ("CORRECT" if have == want else "WRONG", have)
        else:
            out[stage] = ("CORRECT" if have == want else "WRONG", have)
    return out


def main() -> None:
    lines = ["# 실제 사례 + 가정 상황 시험", "",
             f"기준일 {KB.as_of}, strict 해제. 가정은 사례 원문에 없는 사실을 채운 것이다. "
             "CONSULT는 근거가 해설·질의회신뿐이라 계산기가 결론 대신 문의처·질의서 초안을 낸 경우다.", "",
             "| 사례 | 상황 | 단계 | 기관 답 | 계산기 | 판정 | 가정 |", "|---|---|---|---|---|---|---|"]
    tally = {}
    for sc in S:
        for label, facts in [("기본", sc["facts"])] + ([("변형", {**sc["facts"], **sc["variant"]})]
                                                       if sc.get("variant") else []):
            r = run(facts)
            for stage, (verdict, have) in compare(sc["expected"], r, facts).items():
                note = sc["assumed"] if label == "기본" else (
                    f"변형: {json.dumps(sc['variant'], ensure_ascii=False)}" + (f" — {sc['variant_note']}" if sc.get("variant_note") else ""))
                if label != "기본" and sc.get("variant_note"):
                    verdict = f"{verdict}(입력 오류)"
                tally[verdict] = tally.get(verdict, 0) + 1
                lines.append(f"| {sc['id']} | {sc['title']} | {stage} | {sc['expected'][stage]} | {have} | "
                             f"**{verdict}** | {note} |")
    lines += ["", "합계: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items()))]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
