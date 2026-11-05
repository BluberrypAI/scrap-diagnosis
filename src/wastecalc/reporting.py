"""분류 결과와 구별되는 최초 배출자 신고·지정폐기물 처리계획 대상 검토."""
from __future__ import annotations

from datetime import date

from .kb import source_valid

LABELS = {"REQUIRED": "대상", "NOT_REQUIRED": "확인한 배출 조건에서 대상 기준 미충족",
          "NOT_APPLICABLE": "현재 배출물에 적용되는 절차 아님"}


class _Check:
    def __init__(self, kb, answers, strict, section):
        self.kb, self.answers, self.strict, self.section = kb, answers, strict, section
        self.cards = {}

    def basis(self, spec):
        source = self.kb.sources[self.kb.reporting["source"]]
        return {"source_id": self.kb.reporting["source"], "title": source["title"],
                "location": spec["location"], "quote": spec["quote"], "evidence": source["evidence"],
                "law_version": source["version"], "effective_on": source["effective_on"],
                "rule_id": "REPORTING-" + self.section, "review": self.kb.reporting["review"]}

    def read(self, fid, spec):
        from .engine import _fact_card
        a = self.answers.get(fid)
        if a is not None and a.kind == "VALUE":
            return a.values[0]
        card = _fact_card(self.kb, fid, self.answers)
        card["decides"] = [{"if": "법정 조건에 해당", "then": "신고·처리계획 대상 여부",
                            "also_needs": [], "plain": "배출물 분류와 별도로 배출량·사업장 조건을 확인합니다.",
                            "basis": self.basis(spec)}]
        self.cards[fid] = card
        return None

    def finish(self, conclusion=None, why="", spec=None, status=None):
        conflict = any(c["state"] == "CONFLICT" for c in self.cards.values())
        if conflict:
            conclusion, status = None, "NEED_EXPERT"
            why = "자료의 값이 서로 다릅니다. 같은 종류·기간·배출 범위의 자료인지 확인하세요."
        if conclusion is not None:
            return {"status": "DETERMINED", "conclusion": conclusion, "label": LABELS[conclusion], "why": why,
                    "provisional": self.strict and self.kb.reporting["review"] != "REVIEWED",
                    "basis": [self.basis(s) for s in spec.get("items", [spec])] if spec else []}
        return {"status": status or "NEED_INFO", "conclusion": None, "label": why or "확인할 자료가 남아 있습니다.",
                "why": why, "resolution": list(self.cards.values()),
                "basis": [self.basis(spec)] if spec else []}


def _general(c):
    spec = c.kb.reporting["general"]
    shared = c.read("reporting_shared", spec["basis"])
    if shared is None:
        return c.finish()
    if shared != "none":
        return c.finish(status="NEED_EXPERT", why="공동처리 대표자·구성원은 대표 신고 여부와 법정 예외를 기관에 확인해야 합니다.")
    daily = c.read("reporting_general_daily_kg", spec["basis"])
    if daily is not None and daily >= spec["other_daily_kg"]:
        return c.finish("REQUIRED", "제외 항목을 뺀 하루 평균량이 일반 기준 이상입니다.", spec["other_basis"])
    if daily is not None and daily >= spec["facility_daily_kg"]:
        # 어느 한 시설에 해당하면 나머지 시설 질문은 불필요하다.
        facility = c.read("emission_facility", spec["basis"])
        if facility is True:
            return c.finish("REQUIRED", "배출시설이 있고 신고대상 하루 평균량이 시설 기준 이상입니다.", spec["basis"])
        public = c.read("public_facility", spec["basis"])
        if public is not None and public != "none":
            return c.finish("REQUIRED", "해당 공공처리시설의 신고대상 하루 평균량이 기준 이상입니다.", spec["basis"])
        waste = c.read("waste_facility", spec["basis"])
        if waste is True:
            return c.finish("REQUIRED", "폐기물처리시설의 신고대상 하루 평균량이 기준 이상입니다.", spec["basis"])
    work = c.read("work_type", spec["work_basis"])
    total = c.read("reporting_work_total_ton", spec["work_basis"]) if work in {"construction", "series"} else None
    if total is not None and total >= spec["work_total_ton"]:
        return c.finish("REQUIRED", "제외 항목을 뺀 공사·작업 전체량이 기준 이상입니다. 실제 신고 주체는 계약 관계와 함께 확인하세요.", spec["work_basis"])
    if c.cards:
        return c.finish()
    return c.finish("NOT_REQUIRED", "확인한 신고대상량과 사업장·공사 조건은 기준에 미달합니다. 변경신고 및 다른 배출물의 의무는 별도입니다.", spec["basis"])


def _plan(c, code):
    spec = c.kb.reporting["plan"]
    intermediate = c.read("reporting_intermediate", spec["excluded_basis"])
    if intermediate is None:
        return c.finish()
    if intermediate == "other_intermediate":
        return c.finish("NOT_REQUIRED", "확인한 물질은 제18조의2제1항 본문의 중간가공 폐기물 제외 대상입니다. 물질 지위가 불명확하면 기관 확인이 필요합니다.", spec["excluded_basis"])
    shared = c.read("reporting_shared", spec["excluded_basis"])
    if shared is None:
        return c.finish()
    if shared != "none":
        return c.finish(status="NEED_EXPERT", why="공동처리에서는 대표자의 확인 의무와 적용 예외를 기관에 확인해야 합니다.")
    always = spec["unconditional"]
    hit = next((b for b in always["items"] if code.startswith(b["prefix"])), None)
    if hit:
        return c.finish("REQUIRED", "현재 분류한 물질은 배출량과 무관하게 처리계획 확인 대상인 종류입니다.", hit)
    group = next((g for g in spec["groups"].values() if any(code.startswith(p) for p in g["prefixes"])), None)
    if group is None:
        return c.finish(status="NEED_EXPERT", why="이 번호의 처리계획 적용 기준 또는 별도 고시를 확보하지 못했습니다.", spec=spec["unverified_notice"])
    monthly = c.read("reporting_current_monthly_kg", group)
    if monthly is not None and monthly >= group["per_kind_kg"]:
        return c.finish("REQUIRED", "현재 종류의 사업장 전체 월평균량이 해당 종류 기준 이상입니다.", group)
    inventory = c.read("reporting_designated_inventory", group)
    if inventory is None:
        return c.finish()
    if inventory == "single":
        if monthly is None:
            return c.finish()
        return c.finish("NOT_REQUIRED", "다른 지정폐기물 종류가 없다는 확인과 입력한 월평균량을 기준으로 미달합니다. 별도 고시·변경확인·확인 주체의 예외는 독립 검토 범위입니다.", group)
    # 전체 묶음별 자료를 받는 경우 현재 한 종류의 값은 추가로 요구하지 않는다.
    c.cards.pop("reporting_current_monthly_kg", None)
    unconditional = c.read("reporting_unconditional_designated", always)
    if unconditional is True:
        return c.finish("REQUIRED", "사업장에 배출량과 무관한 확인 대상 종류가 있습니다.", always)
    for g in spec["groups"].values():
        maximum = c.read(g["max_fact"], g)
        total = c.read(g["sum_fact"], g) if g.get("sum_fact") else None
        if maximum is not None and total is not None and total < maximum:
            return c.finish(status="NEED_EXPERT", why="묶음 합계가 종류별 최댓값보다 작습니다. 기간·종류·중복 합산 여부를 확인하세요.", spec=g)
        if maximum is not None and maximum >= g["per_kind_kg"]:
            return c.finish("REQUIRED", "묶음 안의 종류별 월평균량 중 기준 이상인 종류가 있습니다.", g)
        if total is not None and total >= g["combined_kg"]:
            return c.finish("REQUIRED", "해당 법정 묶음의 월평균 합계가 기준 이상입니다.", g)
    notice = c.read("reporting_other_designated_notice", spec["unverified_notice"])
    if notice is True:
        return c.finish(status="NEED_EXPERT", why="별도 고시 대상의 배출량 기준과 적용 조건은 기관 확인이 필요합니다.", spec=spec["unverified_notice"])
    if c.cards:
        return c.finish()
    return c.finish("NOT_REQUIRED", "확인한 사업장 전체 종류·묶음별 월평균량이 기준에 미달합니다.", group)


def assess_reporting(kb, answers, result, strict):
    empty = {"status": "WAITING", "conclusion": None, "label": "분류 판단이 먼저 필요합니다.", "resolution": []}
    out = {"general_notice": dict(empty), "designated_plan": dict(empty),
           "scope": "현재 배출물의 종류에 해당하는 최초 절차 검토입니다. 다른 배출물·변경신고·변경확인·공동처리의 의무까지 면제한다는 뜻은 아닙니다."}
    decisions = {d["stage"]: d for d in result["decided"]}
    if any(d["conclusion"] in {"NOT_WASTE", "CIRCULAR_RESOURCE", "EXCLUDED", "HOUSEHOLD"} for d in decisions.values()):
        for key in ("general_notice", "designated_plan"):
            out[key] = {"status": "DETERMINED", "conclusion": "NOT_APPLICABLE", "label": LABELS["NOT_APPLICABLE"],
                        "why": "앞 단계에서 현재 배출물은 이 계산기의 사업장폐기물 절차 대상에서 벗어났습니다."}
        return out
    if "S4" not in decisions:
        return out
    if not kb.reporting or not source_valid(kb.sources[kb.reporting["source"]], date.fromisoformat(kb.as_of)):
        for key in ("general_notice", "designated_plan"):
            out[key] = {"status": "OUT_OF_SCOPE", "conclusion": None, "label": "이 기준일의 신고 규칙이 없습니다."}
        return out
    designated = decisions["S3"]["conclusion"] == "DESIGNATED"
    key = "designated_plan" if designated else "general_notice"
    other = "general_notice" if designated else "designated_plan"
    out[other] = {"status": "DETERMINED", "conclusion": "NOT_APPLICABLE", "label": LABELS["NOT_APPLICABLE"],
                  "why": "현재 배출물의 지정 여부에 따라 적용하는 절차가 다릅니다. 사업장의 다른 종류에 대한 의무는 별도입니다."}
    checker = _Check(kb, answers, strict, key)
    out[key] = _plan(checker, decisions["S4"]["conclusion"]) if designated else _general(checker)
    return out
