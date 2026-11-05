"""요청 범위와 항목별 완료 여부. 한 항목의 결론을 전체 완료로 확대하지 않는다."""
from __future__ import annotations

from .reporting import assess_reporting

COMPLETE = {"DETERMINED", "PROVISIONAL", "FACT_CONFIRMED", "NOT_APPLICABLE", "NOT_REQUESTED"}


def finish_assessment(kb, answers, result, include_reporting):
    result["assessment_scope"] = "classification_and_reporting" if include_reporting else "classification"
    classification_complete = result["status"] == "DETERMINED" or bool(result.get("provisional"))
    if include_reporting:
        reporting = assess_reporting(kb, answers, result, result["strict"])
        result["reporting"] = reporting
        for key in ("general_notice", "designated_plan"):
            for basis in reporting[key].get("basis", []):
                sid = basis["source_id"]
                src = kb.sources[sid]
                result["law_versions"][sid] = {"title": src["title"], "version": src["version"], "effective_on": src["effective_on"]}
        incomplete = [reporting[k] for k in ("general_notice", "designated_plan") if reporting[k]["status"] != "DETERMINED"]
        if classification_complete and incomplete:
            cards = [c for item in incomplete for c in item.get("resolution", [])]
            expert = any(item["status"] == "NEED_EXPERT" for item in incomplete)
            unsupported = any(item["status"] == "OUT_OF_SCOPE" for item in incomplete)
            nxt = None if expert or unsupported else next((c for c in cards if c["state"] == "MISSING"), None)
            result.update(status="OUT_OF_SCOPE" if unsupported else "NEED_EXPERT" if expert else "NEED_INFO",
                          stage="S6", stage_title="신고·처리계획 확인 대상", reason="REPORTING_INCOMPLETE",
                          message="분류 결과와 별도로 신고·처리계획 확인 대상 여부를 확인해야 합니다.", resolution=cards,
                          next_question=None if nxt is None else {"fact": nxt["fact"], "question": nxt["question"],
                          "type": nxt["type"], "unit": nxt.get("unit"), "allowed_values": nxt.get("allowed_values"), "test": None})

    decisions = {d["stage"]: d for d in result["decided"]}
    terminal = any(d["conclusion"] in {"NOT_WASTE", "CIRCULAR_RESOURCE", "EXCLUDED", "HOUSEHOLD"} for d in decisions.values())
    checks = []

    def add(key, title, status, label, **extra):
        checks.append({"key": key, "title": title, "status": status, "label": label, **extra})

    def stage_check(key, title, stage):
        d = decisions.get(stage)
        if d:
            weak = not d["reviewed"] or not d["law_based"] or bool(d["gaps"])
            add(key, title, "PROVISIONAL" if weak else "DETERMINED", d["label"])
        elif terminal:
            add(key, title, "NOT_APPLICABLE", "앞 단계 결과에 따라 적용되지 않음")
        else:
            asked = (result.get("next_question") or {}).get("asked_for_stage")
            current = stage == result.get("stage") or stage == asked
            add(key, title, result["status"] if current else "WAITING", "확인 필요" if current else "앞선 판단 확인 후 검토")

    if "S1" in decisions:
        stage_check("applicability", "폐기물관리법 적용 여부", "S1")
    elif terminal:
        last = result["decided"][-1]
        add("applicability", "폐기물관리법 적용 여부", "PROVISIONAL" if not last["reviewed"] else "DETERMINED", last["label"])
    else:
        add("applicability", "폐기물관리법 적용 여부", result["status"] if result.get("stage") in {"S0", "S1"} else "WAITING", "확인 필요")
    kind = answers.get("waste_kind")
    if kind and kind.kind == "VALUE":
        add("kind", "발생물질 종류", "FACT_CONFIRMED", kb.facts["waste_kind"]["values"][kind.values[0]], source=kind.source)
    elif terminal:
        add("kind", "발생물질 종류", "NOT_APPLICABLE", "후속 분류 대상 아님")
    else:
        add("kind", "발생물질 종류", "NEED_EXPERT" if kind and kind.kind == "CONFLICT" else "NEED_INFO", "자료로 확인할 종류가 남아 있음")
    stage_check("designation", "지정폐기물 여부", "S3")
    stage_check("code", "폐기물 세부분류번호", "S4")
    for key, title in (("general_notice", "사업장폐기물 배출자 신고"), ("designated_plan", "지정폐기물 처리계획 확인")):
        if not include_reporting:
            add(key, title, "NOT_REQUESTED", "이번 판정에서 요청하지 않음")
        else:
            item = result["reporting"][key]
            status = "PROVISIONAL" if item.get("provisional") else item["status"]
            if item.get("conclusion") == "NOT_APPLICABLE":
                status = "NOT_APPLICABLE"
            add(key, title, status, item["label"])
    stage_check("recycling", "재활용 가능 유형", "S5")
    result["checks"] = checks
    result["assessment_complete"] = classification_complete and all(c["status"] in COMPLETE for c in checks)
    if not result["assessment_complete"]:
        result["conclusion"] = None
    return result
