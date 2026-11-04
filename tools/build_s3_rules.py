"""S3(지정폐기물 여부) 규칙 표를 만든다. 결과: rules/rules_s3.yaml

시행규칙 별표 1의 물질별 기준이 폐기물 종류마다 반복되므로 사람이 손으로 옮기다 틀리지 않게 생성한다.
생성된 YAML이 검토 대상이다. 인용문은 tests/test_rules_data.py가 원문 PDF와 대조한다.
실행: python tools/build_s3_rules.py
"""
from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parents[1] / "rules" / "rules_s3.yaml"
D = "DESIGNATED"

# 시행규칙 별표 1 제1호 가~자: (사실, 기준값, 원문 일부)
LEACH = [
    ("leach_pb", 3, "가목", "용출액 1리터당 3밀리그램 이상의 납을 함유한 경우만 해당한다"),
    ("leach_cu", 3, "나목", "용출액 1리터당 3밀리그램 이상의 구리를 함유한 경우만 해당한다"),
    ("leach_as", 1.5, "다목", "용출액 1리터당 1.5밀리그램 이상의 비소를 함유한 경우만 해당한다"),
    ("leach_hg", 0.005, "라목", "용출액 1리터당 0.005밀리그램 이상의 수은을 함유한 경우만 해당한다"),
    ("leach_cd", 0.3, "마목", "용출액 1리터당 0.3밀리그램 이상의 카드뮴을 함유한 경우만 해당한다"),
    ("leach_cr6", 1.5, "바목", "용출액 1리터당 1.5밀리그램 이상의 6가크롬을 함유한 경우만 해당한다"),
    ("leach_cn", 1, "사목", "용출액 1리터당 1밀리그램 이상의 시안화합물을 함유한 경우만 해당한다"),
    ("leach_op", 1, "아목", "용출액 1리터당 1밀리그램 이상의 유기인화합물을 함유한 경우만 해당한다"),
    ("leach_pce", 0.1, "자목", "용출액 1리터당 0.1밀리그램 이상의 테트라클로로에틸렌을 함유한 경우만 해당한다"),
    ("leach_tce", 0.3, "차목", "용출액 1리터당 0.3밀리그램 이상의 트리클로로에틸렌을 함유한 경우만 해당한다"),
]
OIL_A1 = ("oil_content_pct", 5, "카목", "기름성분(중량비를 기준으로 하여 유해물질을 5퍼센트 이상 함유한 경우만 해당한다)")
GROUP_A_HEAD = "오니류·폐흡착제 및 폐흡수제에 함유된 유해물질"
GROUP_B_HEAD = ("제1호 가목부터 사목까지의 규정과 카목에 따른 유해물질(분진과 소각재의 경우에는 "
                "제1호 가목부터 사목까지의 규정에 따른 유해물질만 해당한다)")
HAZ_HEAD = "유해물질함유 폐기물(기후에너지환경부령으로 정하는 물질을 함유한 것으로 한정한다)"
NOTICE_GAP = ("시행규칙 별표 1 제1호타목·제2호라목 '그 밖에 기후에너지환경부장관이 정하여 고시하는 물질'의 "
              "고시가 있는지 확인하지 못함")


def c(fact, op, value):
    return {"fact": fact, "op": op, "value": value}


def rule(id_, when, source, location, quote, concludes=D, supporting=None, gaps=None, item=None):
    r = {"id": id_, "stage": "S3", "concludes": concludes, "when": when, "source": source,
         "location": location, "quote": quote, "review": "UNVERIFIED"}
    if item:
        r["item"] = item
    if supporting:
        r["supporting"] = supporting
    if gaps:
        r["gaps"] = gaps
    return r


def sup(source, location, quote, note=None):
    s = {"source": source, "location": location, "quote": quote}
    if note:
        s["note"] = note
    return s


rules = []

# 1가 폐합성 고분자화합물 (고체 제외)
FIRST_GAP = ["시행령 별표 1 제1호 표제 '특정시설에서 발생되는 폐기물'의 '특정시설' 범위를 정한 규정을 확인하지 못함"]
for kind, loc, q, item in [
    ("synthetic_resin", "별표 1 제1호가목1)", "폐합성 수지(고체상태의 것은 제외한다)", "폐합성 수지(비고체)"),
    ("synthetic_rubber", "별표 1 제1호가목2)", "폐합성 고무(고체상태의 것은 제외한다)", "폐합성 고무(비고체)"),
]:
    rules.append(rule(f"S3-1GA-{kind.upper()}", [c("waste_kind", "eq", kind), c("physical_state", "in", ["liquid", "semisolid"])],
                      "DEC-A1", loc, q, gaps=FIRST_GAP, item=item))

# 1나 오니류: 수분 95% 미만 + 고시 시설 + 시행규칙 별표 1 제1호 물질
SLUDGE = [
    ("sludge_wastewater", "별표 1 제1호나목1)",
     "폐수처리 오니(기후에너지환경부령으로 정하는 물질을 함유한 것으로 기후에너지환경부장관이 고시한 시설에서 발생되는 것으로 한정한다)"),
    ("sludge_process", "별표 1 제1호나목2)",
     "공정 오니(기후에너지환경부령으로 정하는 물질을 함유한 것으로 기후에너지환경부장관이 고시한 시설에서 발생되는 것으로 한정한다)"),
]
for kind, loc, q in SLUDGE:
    for fact, val, mok, tq in LEACH + [OIL_A1]:
        rules.append(rule(
            f"S3-1NA-{kind.upper()}-{fact.upper()}",
            [c("waste_kind", "eq", kind), c("sludge_facility_notified", "eq", True),
             c("sludge_water_pct", "lt", 95), c(fact, "gte", val)],
            "DEC-A1", loc, q,
            supporting=[sup("DEC-A1", "별표 1 제1호나목", "오니류(수분함량이 95퍼센트 미만이거나 고형물함량이 5퍼센트 이상인 것으로 한정한다)"),
                        sup("RULE-A1", f"별표 1 제1호{mok}", tq)],
            gaps=[NOTICE_GAP], item="오니류"))

# 1다 폐농약
rules.append(rule("S3-1DA-PESTICIDE", [c("waste_kind", "eq", "pesticide"), c("pesticide_from_maker_seller", "eq", True)],
                  "DEC-A1", "별표 1 제1호다목", "폐농약(농약의 제조·판매업소에서 발생되는 것으로 한정한다)", item="폐농약"))

# 2 부식성 폐기물
rules.append(rule("S3-2GA-ACID", [c("waste_kind", "eq", "acid"), c("physical_state", "eq", "liquid"), c("ph", "lte", 2.0)],
                  "DEC-A1", "별표 1 제2호가목",
                  "폐산(액체상태의 폐기물로서 수소이온 농도지수가 2.0 이하인 것으로 한정한다)", item="폐산"))
ALK_Q = "폐알칼리(액체상태의 폐기물로서 수소이온 농도지수가 12.5 이상인 것으로 한정하며, 수산화칼륨 및 수산화나트륨을 포함한다)"
rules.append(rule("S3-2NA-ALKALI-LIQUID", [c("waste_kind", "eq", "alkali"), c("physical_state", "eq", "liquid"), c("ph", "gte", 12.5)],
                  "DEC-A1", "별표 1 제2호나목", ALK_Q, item="폐알칼리"))
rules.append(rule("S3-2NA-ALKALI-NAOH-KOH", [c("waste_kind", "eq", "alkali"), c("alkali_solid_naoh_koh", "eq", True)],
                  "DEC-A1", "별표 1 제2호나목", ALK_Q, item="폐알칼리(수산화나트륨·수산화칼륨)"))

# 3 유해물질함유 폐기물
GROUP_B = [
    # kind, 위치, 원문, 추가 조건, 기름성분 적용 여부, 품목
    ("slag", "별표 1 제3호가목", "광재(鑛滓)[철광 원석의 사용으로 인한 고로(高爐)슬래그(slag)는 제외한다]",
     [c("blast_furnace_iron_slag", "eq", False)], True, "광재"),
    ("dust", "별표 1 제3호나목", "분진(대기오염 방지시설에서 포집된 것으로 한정하되, 소각시설에서 발생되는 것은 제외한다)",
     [c("dust_from_apc", "eq", True), c("dust_from_incinerator", "eq", False)], False, "분진"),
    ("foundry_sand", "별표 1 제3호다목", "폐주물사 및 샌드블라스트 폐사(廢砂)", [], True, "폐주물사·샌드블라스트 폐사"),
    ("refractory", "별표 1 제3호라목", "폐내화물(廢耐火物) 및 재벌구이 전에 유약을 바른 도자기 조각", [], True, "폐내화물·도자기 조각"),
    ("incineration_ash", "별표 1 제3호마목", "소각재", [], False, "소각재"),
    ("stabilized", "별표 1 제3호바목", "안정화 또는 고형화·고화 처리물", [], True, "안정화·고형화·고화 처리물"),
    ("catalyst", "별표 1 제3호사목", "폐촉매", [], True, "폐촉매"),
]
for kind, loc, q, extra, with_oil, item in GROUP_B:
    subs = LEACH[:7] + ([OIL_A1] if with_oil else [])
    for fact, val, mok, tq in subs:
        rules.append(rule(
            f"S3-3-{kind.upper()}-{fact.upper()}",
            [c("waste_kind", "eq", kind)] + extra + [c(fact, "gte", val)],
            "DEC-A1", loc, q,
            supporting=[sup("DEC-A1", "별표 1 제3호", HAZ_HEAD),
                        sup("RULE-A1", "별표 1 제2호가목", GROUP_B_HEAD),
                        sup("RULE-A1", f"별표 1 제1호{mok}", tq)],
            gaps=[NOTICE_GAP], item=item))
rules.append(rule(
    "S3-3-STABILIZED-ASBESTOS",
    [c("waste_kind", "eq", "stabilized"), c("asbestos_pct", "gte", 1)],
    "DEC-A1", "별표 1 제3호바목", "안정화 또는 고형화·고화 처리물",
    supporting=[sup("RULE-A1", "별표 1 제2호나목",
                    "석면(고형화 처리물의 경우로서 건조 고형물의 함량을 기준으로 하여 석면이 1퍼센트 이상 함유된 경우로 한정한다)")],
    gaps=["시행규칙은 '고형화 처리물'로 한정 — 안정화·고화 처리물에도 적용되는지 해석 필요"], item="안정화·고형화·고화 처리물"))
# 3아 폐흡착제·폐흡수제: 시행규칙 별표 1 제1호 전부
for fact, val, mok, tq in LEACH + [OIL_A1]:
    rules.append(rule(
        f"S3-3A-ADSORBENT-{fact.upper()}",
        [c("waste_kind", "eq", "adsorbent"), c(fact, "gte", val)],
        "DEC-A1", "별표 1 제3호아목", "폐흡착제 및 폐흡수제",
        supporting=[sup("DEC-A1", "별표 1 제3호", HAZ_HEAD), sup("RULE-A1", "별표 1 제1호", GROUP_A_HEAD),
                    sup("RULE-A1", f"별표 1 제1호{mok}", tq)],
        gaps=[NOTICE_GAP], item="폐흡착제·폐흡수제"))

# 4 폐유기용제
rules.append(rule("S3-4-SOLVENT", [c("waste_kind", "eq", "organic_solvent")], "DEC-A1", "별표 1 제4호", "폐유기용제",
                  supporting=[sup("DEC-A1", "별표 1 제4호나목", "그 밖의 폐유기용제(가목 외의 유기용제를 말한다)")],
                  item="폐유기용제"))

# 5 폐페인트 및 폐래커
P_HEAD = "폐페인트 및 폐래커(다음 각 목의 것을 포함한다)"
rules.append(rule("S3-5-PAINT", [c("waste_kind", "eq", "paint")], "DEC-A1", "별표 1 제5호", P_HEAD, item="폐페인트·폐래커"))
rules.append(rule("S3-5GA-PAINT-MIX", [c("waste_kind", "eq", "paint_solvent_mix"),
                                       c("paint_mixed_source", "in", ["maker", "coating_large", "recycling"])],
                  "DEC-A1", "별표 1 제5호가목",
                  "페인트 및 래커와 유기용제가 혼합된 것으로서 페인트 및 래커 제조업, 용적 5세제곱미터 이상 또는 동력 3마력 이상의 도장(塗裝)시설, 폐기물을 재활용하는 시설에서 발생되는 것",
                  item="폐페인트·폐래커(유기용제 혼합물)"))
rules.append(rule("S3-5GA-PAINT-MIX-OTHER", [c("waste_kind", "eq", "paint_solvent_mix"), c("paint_mixed_source", "eq", "other")],
                  "DEC-A1", "별표 1 제5호가목",
                  "페인트 및 래커와 유기용제가 혼합된 것으로서 페인트 및 래커 제조업, 용적 5세제곱미터 이상 또는 동력 3마력 이상의 도장(塗裝)시설, 폐기물을 재활용하는 시설에서 발생되는 것",
                  concludes="NEEDS_INTERPRETATION",
                  gaps=["제5호가목의 시설에 해당하지 않는 페인트·유기용제 혼합물이 제4호(폐유기용제) 등 다른 항목에 해당하는지 해석 필요"]))
rules.append(rule("S3-5NA-PAINT-CLEANING", [c("waste_kind", "eq", "paint_cleaning_solvent")], "DEC-A1", "별표 1 제5호나목",
                  "페인트 보관용기에 남아 있는 페인트를 제거하기 위하여 유기용제와 혼합된 것", item="폐페인트·폐래커(용기 세척 혼합물)"))
PC_Q = "폐페인트 용기(용기 안에 남아 있는 페인트가 건조되어 있고, 그 잔존량이 용기 바닥에서 6밀리미터를 넘지 아니하는 것은 제외한다)"
rules.append(rule("S3-5DA-CONTAINER-WET", [c("waste_kind", "eq", "paint_container"), c("paint_dried", "eq", False)],
                  "DEC-A1", "별표 1 제5호다목", PC_Q, item="폐페인트 용기"))
rules.append(rule("S3-5DA-CONTAINER-6MM", [c("waste_kind", "eq", "paint_container"), c("paint_residue_mm", "gt", 6)],
                  "DEC-A1", "별표 1 제5호다목", PC_Q, item="폐페인트 용기"))

# 6 폐유
OIL_Q = "폐유[기름성분을 5퍼센트 이상 함유한 것을 포함하며, 폴리클로리네이티드비페닐(PCBs)함유 폐기물, 폐식용유와 그 잔재물, 폐흡착제 및 폐흡수제는 제외한다]"
rules.append(rule("S3-6-WASTE-OIL", [c("waste_kind", "eq", "waste_oil")], "DEC-A1", "별표 1 제6호", OIL_Q, item="폐유"))
rules.append(rule("S3-6-OIL-5PCT", [c("waste_kind", "not_in", ["waste_oil", "edible_oil", "adsorbent"]),
                                    c("oil_presence", "eq", "present"), c("oil_content_pct", "gte", 5)],
                  "DEC-A1", "별표 1 제6호", OIL_Q, item="폐유(기름성분 5% 이상 함유)"))

# 7 폐석면
rules.append(rule("S3-7GA-ASBESTOS-DEMOLITION", [c("waste_kind", "eq", "asbestos_demolition"), c("asbestos_pct", "gte", 1)],
                  "DEC-A1", "별표 1 제7호가목",
                  "건조고형물의 함량을 기준으로 하여 석면이 1퍼센트 이상 함유된 제품·설비(뿜칠로 사용된 것은 포함한다) 등의 해체·제거 시 발생되는 것",
                  item="폐석면"))
rules.append(rule("S3-7NA-ASBESTOS-PROCESSING", [c("waste_kind", "eq", "asbestos_processing")], "DEC-A1", "별표 1 제7호나목",
                  "슬레이트 등 고형화된 석면 제품 등의 연마·절단·가공 공정에서 발생된 부스러기 및 연마·절단·가공 시설의 집진기에서 모아진 분진",
                  item="폐석면"))
rules.append(rule("S3-7DA-ASBESTOS-WORK", [c("waste_kind", "eq", "asbestos_work_items")], "DEC-A1", "별표 1 제7호다목",
                  "석면의 제거작업에 사용된 바닥비닐시트(뿜칠로 사용된 석면의 해체·제거작업에 사용된 경우에는 모든 비닐시트)·방진마스크·작업복 등",
                  item="폐석면"))

# 8 PCB (종류와 관계없이)
PCB_HEAD = sup("DEC-A1", "별표 1 제8호", "폴리클로리네이티드비페닐 함유 폐기물")
rules.append(rule("S3-8GA-PCB-LIQUID", [c("pcb_possible", "eq", True), c("physical_state", "eq", "liquid"), c("pcb_mg_l", "gte", 2)],
                  "DEC-A1", "별표 1 제8호가목", "액체상태의 것(1리터당 2밀리그램 이상 함유한 것으로 한정한다)",
                  supporting=[PCB_HEAD], item="PCB 함유 폐기물"))
rules.append(rule("S3-8NA-PCB-NONLIQUID", [c("pcb_possible", "eq", True), c("physical_state", "in", ["solid", "semisolid"]),
                                          c("pcb_leach_mg_l", "gte", 0.003)],
                  "DEC-A1", "별표 1 제8호나목", "액체상태 외의 것(용출액 1리터당 0.003밀리그램 이상 함유한 것으로 한정한다)",
                  supporting=[PCB_HEAD], item="PCB 함유 폐기물"))

# 9 폐유독물질 (종류와 관계없이)
rules.append(rule("S3-9-TOXIC", [c("toxic_chemical_discard", "eq", True)], "DEC-A1", "별표 1 제9호",
                  "인체급성유해성물질, 인체만성유해성물질, 생태유해성물질, 허가물질, 제한물질, 금지물질 및 사고대비물질을 폐기하는 경우로 한정하되",
                  item="폐유독물질(또는 그 제외 조항이 가리키는 다른 지정폐기물)"))

# 10 의료폐기물, 10의2 천연방사성제품폐기물
rules.append(rule("S3-10-MEDICAL", [c("waste_kind", "eq", "medical"), c("medical_institution", "eq", True)],
                  "DEC-A1", "별표 1 제10호",
                  "의료폐기물(기후에너지환경부령으로 정하는 의료기관이나 시험·검사 기관 등에서 발생되는 것으로 한정한다)",
                  item="의료폐기물"))
rules.append(rule("S3-10-2-NORM", [c("waste_kind", "eq", "norm_product"), c("norm_bq_g", "lt", 10)], "DEC-A1", "별표 1 제10호의2",
                  "방사능 농도가 그램당 10베크렐 미만인 폐기물을 말한다", item="천연방사성제품폐기물"))

# 11 수은폐기물
rules.append(rule("S3-11GA-MERCURY-PRODUCT", [c("waste_kind", "eq", "mercury_product")], "DEC-A1", "별표 1 제11호가목",
                  "폐계측기기(온도계, 혈압계, 체온계 등), 폐전지 및 그 밖의 기후에너지환경부장관이 고시하는 폐제품을 말한다",
                  item="수은함유폐기물"))
rules.append(rule("S3-11NA-MERCURY-SEPARATED", [c("waste_kind", "eq", "mercury_separated")], "DEC-A1", "별표 1 제11호나목",
                  "수은구성폐기물(수은함유폐기물로부터 분리한 수은 및 그 화합물로 한정한다)", item="수은구성폐기물"))
rules.append(rule("S3-11DA-MERCURY-RESIDUE", [c("waste_kind", "eq", "mercury_residue"), c("leach_hg", "gte", 0.005)],
                  "DEC-A1", "별표 1 제11호다목", "용출액 1리터당 0.005밀리그램 이상의 수은 및 그 화합물이 함유된 것",
                  item="수은함유폐기물 처리잔재물"))

# 폐이차전지: 별표 4는 03-10을 지정폐기물 번호로 두지만 시행령 별표 1의 근거 항목을 찾지 못함 → 해석 필요
rules.append(rule("S3-BATTERY-DAMAGED", [c("waste_kind", "eq", "battery"), c("battery_damaged", "eq", True)],
                  "RULE-A4", "별표 4 제1호 03-10",
                  "03-10-03 리튬계 폐이차전지(침수ㆍ화재ㆍ변형ㆍ파손 등이 발생한 것과 셀이 훼손되어 유해물질이 유출되거나 화재ㆍ폭발의 위험이 있는 것으로 한정한다)",
                  concludes="NEEDS_INTERPRETATION",
                  gaps=["시행규칙 별표 4는 손상된 폐이차전지(03-10)를 지정폐기물 번호로 두지만, 시행령 별표 1에서 근거 항목을 확인하지 못함"]))

# 지정폐기물이 남아 있거나 묻은 용기·물건: 담겨 있던 지정폐기물로 분류(질의회신, 해석 근거)
RESIDUE_QUOTE = "지정폐기물이 아닌 물질에 지정폐기물 잔량이 남아 있거나, 묻어 있는 경우에는 담겨 있던 지정폐기물로 분류하여야 합니다."
RESIDUE_WASH = "이 경우에도 세척 등을 통해 지정폐기물 성분이 제거된다면 재질에 따라 사업장일반폐기물로 분류하여 처리할 수 있으며"
for kind, item in [("waste_oil", "폐유가 남은 용기·물건"), ("organic_solvent", "폐유기용제가 남은 용기·물건"),
                   ("acid", "폐산이 남은 용기·물건"), ("alkali", "폐알칼리가 남은 용기·물건"),
                   ("paint", "폐페인트가 남은 용기·물건"), ("toxic_chemical", "유해화학물질이 남은 용기·물건")]:
    rules.append(rule(
        f"S3-RESIDUE-{kind.upper()}",
        [c("waste_kind", "in", ["other", "synthetic_resin", "synthetic_rubber"]),
         c("designated_residue", "eq", True), c("residue_kind", "eq", kind)],
        "QA-MOE25", "자원순환 분야 사례 14(지정폐기물 처리종류 문의) p.245", RESIDUE_QUOTE,
        supporting=[sup("QA-MOE25", "같은 사례", RESIDUE_WASH, "세척으로 성분을 없앴으면 재질에 따라 일반폐기물")],
        item=item))

# 지정폐기물이 아님: 위 규칙이 모두 확실히 거짓일 때만
rules.append({
    "id": "S3-NOT-DESIGNATED", "stage": "S3", "concludes": "NOT_DESIGNATED",
    "complement_of": [D, "NEEDS_INTERPRETATION"],
    "source": "DEC-A1", "location": "별표 1(지정폐기물의 종류)", "quote": "지정폐기물의 종류(제3조 관련)",
    "gaps": ["시행령 별표 1 제12호 '그 밖에 … 기후에너지환경부장관이 정하여 고시하는 물질'의 고시가 있는지 확인하지 못함", NOTICE_GAP],
    "review": "UNVERIFIED",
})

# ---------------------------------------------------------------- 쉬운 설명(plain)
# 법적 효력이 없는 보조 문장. 숫자는 규칙 조건에 있는 값만 쓴다(tests/test_explain.py가 검사).
SUBSTANCE = {"leach_pb": "납", "leach_cu": "구리", "leach_as": "비소", "leach_hg": "수은", "leach_cd": "카드뮴",
             "leach_cr6": "6가크롬", "leach_cn": "시안화합물", "leach_op": "유기인화합물",
             "leach_pce": "테트라클로로에틸렌", "leach_tce": "트리클로로에틸렌"}


def _num(v):
    return f"{v:g}"


def plain_for(r: dict) -> str:
    rid, item = r["id"], r.get("item", "")
    conds = {c["fact"]: c for c in r.get("when", [])}
    sub = next((f for f in conds if f in SUBSTANCE or f == "oil_content_pct"), None)
    if sub and rid not in ("S3-6-OIL-5PCT", "S3-11DA-MERCURY-RESIDUE"):
        name = SUBSTANCE.get(sub, "기름성분")
        unit = "mg/L" if sub in SUBSTANCE else "%"
        thr = f"{name} {'용출 농도가' if sub in SUBSTANCE else '함량이'} 기준({_num(conds[sub]['value'])}{unit}) 이상"
        if rid.startswith("S3-1NA-"):
            return (f"오니는 ①고시된 발생시설에서 나왔고 ②수분함량이 95% 미만이며 ③{thr}일 때 지정폐기물입니다. "
                    "세 조건이 모두 맞아야 합니다.")
        extra = ""
        if "blast_furnace_iron_slag" in conds:
            extra = " 철광석을 쓰는 용광로의 고로슬래그는 제외됩니다."
        if "dust_from_apc" in conds:
            extra = " 대기오염 방지시설에서 모은 분진만 해당하고, 소각시설 분진은 제외됩니다."
        return f"{item}은(는) {thr}이면 유해물질을 함유한 지정폐기물입니다.{extra}"
    table = {
        "S3-1GA-SYNTHETIC_RESIN": "합성수지(플라스틱)는 액체·반고체 상태일 때만 지정폐기물입니다. 고체 플라스틱 조각은 이 항목에 해당하지 않습니다.",
        "S3-1GA-SYNTHETIC_RUBBER": "합성고무는 액체·반고체 상태일 때만 지정폐기물입니다. 고체 고무는 이 항목에 해당하지 않습니다.",
        "S3-1DA-PESTICIDE": "농약 제조·판매업소에서 나온 폐농약은 지정폐기물입니다.",
        "S3-2GA-ACID": "액체 폐산은 pH 2.0 이하(강한 산성)일 때 지정폐기물입니다. pH는 시험으로 확인합니다.",
        "S3-2NA-ALKALI-LIQUID": "액체 폐알칼리는 pH 12.5 이상(강한 알칼리성)일 때 지정폐기물입니다. pH는 시험으로 확인합니다.",
        "S3-2NA-ALKALI-NAOH-KOH": "고체 수산화나트륨·수산화칼륨은 법에서 폐알칼리에 포함한다고 정해 두어 지정폐기물입니다.",
        "S3-3-STABILIZED-ASBESTOS": "고형화 처리물은 석면이 1% 이상 들어 있으면 지정폐기물입니다. 안정화·고화 처리물에도 적용되는지는 해석이 필요합니다.",
        "S3-4-SOLVENT": "폐유기용제는 종류와 관계없이 지정폐기물입니다.",
        "S3-5-PAINT": "폐페인트·폐래커는 지정폐기물입니다.",
        "S3-5GA-PAINT-MIX": "페인트·래커 제조업, 큰 도장시설, 폐기물 재활용시설에서 나온 페인트·유기용제 혼합물은 지정폐기물입니다.",
        "S3-5GA-PAINT-MIX-OTHER": "법이 정한 시설 밖에서 나온 페인트·유기용제 혼합물이 다른 지정폐기물 항목(폐유기용제 등)에 해당하는지는 법 문언만으로 정할 수 없어 전문가 확인이 필요합니다.",
        "S3-5NA-PAINT-CLEANING": "페인트 용기를 닦으려고 유기용제를 섞은 것은 지정폐기물입니다.",
        "S3-5DA-CONTAINER-WET": "남은 페인트가 마르지 않은 폐페인트 용기는 지정폐기물입니다.",
        "S3-5DA-CONTAINER-6MM": "용기 바닥에 남은 페인트가 6mm를 넘는 폐페인트 용기는 지정폐기물입니다. 완전히 마르고 6mm 이하면 제외됩니다.",
        "S3-6-WASTE-OIL": "윤활유·절삭유·작동유 같은 폐유는 지정폐기물입니다.",
        "S3-6-OIL-5PCT": "기름이 묻거나 섞인 폐기물도 기름성분이 5% 이상이면 폐유(지정폐기물)로 봅니다. 함량은 시험으로 확인합니다.",
        "S3-7GA-ASBESTOS-DEMOLITION": "석면이 1% 이상 든 제품·설비를 해체·제거할 때 나온 폐기물은 폐석면(지정폐기물)입니다.",
        "S3-7NA-ASBESTOS-PROCESSING": "슬레이트 등 석면 제품을 자르거나 갈 때 나온 부스러기와 집진 분진은 폐석면(지정폐기물)입니다.",
        "S3-7DA-ASBESTOS-WORK": "석면 제거작업에 쓴 비닐시트·마스크·작업복은 폐석면(지정폐기물)입니다.",
        "S3-8GA-PCB-LIQUID": "액체 폐기물에 PCB가 1리터당 2mg 이상 들어 있으면 지정폐기물입니다.",
        "S3-8NA-PCB-NONLIQUID": "액체가 아닌 폐기물은 PCB 용출 농도가 1리터당 0.003mg 이상이면 지정폐기물입니다.",
        "S3-9-TOXIC": "유해화학물질(인체·생태 유해성 물질, 허가·제한·금지물질, 사고대비물질)을 폐기하는 것은 지정폐기물입니다.",
        "S3-10-MEDICAL": "의료기관·시험검사기관 등에서 나온 의료폐기물은 지정폐기물입니다. 가정에서 나온 것은 여기에 해당하지 않습니다.",
        "S3-10-2-NORM": "안전기준에 맞지 않는 천연방사성 가공제품 폐기물은 방사능 농도가 그램당 10베크렐 미만이면 지정폐기물입니다.",
        "S3-11GA-MERCURY-PRODUCT": "수은이 든 폐램프(폐형광등 제외)·온도계 등 계측기·폐전지는 수은폐기물(지정폐기물)입니다.",
        "S3-11NA-MERCURY-SEPARATED": "수은함유폐기물에서 분리한 수은은 수은폐기물(지정폐기물)입니다.",
        "S3-11DA-MERCURY-RESIDUE": "수은함유폐기물 처리잔재물은 수은 용출 농도가 기준(0.005mg/L) 이상이면 지정폐기물입니다.",
        "S3-BATTERY-DAMAGED": "손상된 폐이차전지는 분류표(별표 4)에 지정폐기물 번호가 있지만 지정폐기물 종류를 정한 시행령에서 근거 항목을 찾지 못해 전문가 확인이 필요합니다.",
        "S3-NOT-DESIGNATED": "지정폐기물이 되는 경로가 하나도 해당하지 않아 사업장일반폐기물입니다. 다만 '그 밖에 장관이 고시하는 물질' 고시가 있는지는 확인하지 못했습니다.",
    }
    if rid.startswith("S3-RESIDUE-"):
        return ("지정폐기물이 아닌 용기·물건이라도 지정폐기물이 남아 있거나 묻어 있으면, 담겨 있던 지정폐기물로 분류한다는 "
                "환경부 질의회신이 있습니다. 세척해서 없앴다면 재질에 따라 일반폐기물입니다. 법 조문이 아닌 회신이 근거입니다.")
    return table[rid]


for r in rules:
    r["plain"] = plain_for(r)

OUT.write_text("# 자동 생성: tools/build_s3_rules.py — 직접 고치지 말고 생성기를 고친 뒤 다시 실행\n"
               + yaml.safe_dump({"rules": rules}, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
print(f"{len(rules)} rules → {OUT}")
