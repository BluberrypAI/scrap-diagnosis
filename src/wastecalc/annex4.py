"""S4: 시행규칙 별표 4 분류번호.

1) 앞 단계(S3) 결과로 번호 범위를 좁힌다: 지정폐기물이면 성립한 별표 1 항목 → 별표 4 그룹,
   사업장일반폐기물이면 폐기물 종류 → 51-xx 그룹(모르면 그룹을 묻는다).
2) 범위 안 번호가 하나면 그대로 정한다. 여럿이면 법령 명칭 목록에서 고르게 한다.
3) 고른 번호가 범위 밖이면 앞 판정과 모순 → 전문가 확인. '그 밖의' 번호는 다른 번호에 해당하지 않는다는 확인을 받는다.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from typing import Any

from .kb import KB, ROOT, general_units

STAGE = "S4"


@lru_cache(maxsize=1)
def _guide_definitions() -> dict[str, str]:
    """2023 분류 설명서(구판)의 번호별 정의. 참고용으로만 보여 준다."""
    path = ROOT / "data" / "code_interpretations.csv"
    out: dict[str, str] = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("topic") == "definition" and r.get("code") and r.get("source_id") == "GUIDE23":
                out.setdefault(r["code"], r["source_quote"])
    return out


def _is_catch_all(name: str) -> bool:
    return name.startswith("그 밖의") or name.startswith("그 밖에")


def _code_index(kb: KB) -> dict[str, dict]:
    return {c["id"]: c for c in kb.annex4["codes"]}


def _code_basis(kb: KB, code: dict) -> dict:
    src = kb.sources["RULE-A4"]
    return {"source_id": "RULE-A4", "title": src["title"], "location": f"별표 4 {code['id']}",
            "quote": f"{code['id']} {code['name']}", "evidence": src["evidence"], "law_version": src["version"],
            "effective_on": src["effective_on"], "rule_id": f"ANNEX4-{code['id']}", "review": "REVIEWED"}


def _designated_prefixes(kb: KB, fired: list[str]) -> tuple[list[str], list[str]]:
    m = kb.s4_map["designated"]
    keep = list(fired)
    notes = []
    for ex in kb.s4_map.get("designated_exclusions", []):
        hit = [f for f in keep if any(f.startswith(p) for p in ex["if_any_fired"])]
        dropped = [f for f in keep if f.startswith(ex["drop"])]
        if hit and dropped and len(dropped) < len(keep):
            keep = [f for f in keep if not f.startswith(ex["drop"])]
            notes.append(ex["basis"])
    prefixes: list[str] = []
    for f in keep:
        keys = [k for k in m if f.startswith(k)]
        if keys:
            prefixes += m[max(keys, key=len)]
    return list(dict.fromkeys(prefixes)), notes


def _card(fid: str, kb: KB, answers: dict, allowed: dict[str, str], extra: dict | None = None) -> dict:
    f = kb.facts[fid]
    a = answers.get(fid)
    card = {"fact": fid, "question": f["question"], "type": f["type"], "cost": f["cost"],
            "state": "MISSING" if a is None else a.kind, "allowed_values": allowed, "decides": [],
            "how_to_check": [{"text": h["text"], "basis": None} for h in f.get("how_to_check", [])]
                            or [{"text": "기존 신고서의 분류번호와 아래 세부분류 명칭을 대조하세요. 구분하기 어려우면 관할 기관에 확인하세요.", "basis": None}]}
    if extra:
        card.update(extra)
    return card


def _open(kb: KB, card: dict, open_labels: list[str], message: str | None = None) -> dict:
    r = {"status": "NEED_INFO", "stage": STAGE, "stage_title": kb.stages[STAGE]["title"],
         "open_candidates": open_labels, "resolution": [card], "complement": [],
         "next_question": {"fact": card["fact"], "question": card["question"], "type": card["type"],
                           "allowed_values": card["allowed_values"], "unit": None, "test": None,
                           "asked_for_stage": None}}
    if message:
        r["message"] = message
    if card["fact"] == "code":
        r["candidates"] = list(card["allowed_values"])
    if card["state"] in {"UNKNOWN", "CONFLICT"}:
        r["next_question"] = None
        r["message"] = message or "지금 자료로는 구분하기 어렵습니다. 확인 방법을 살펴본 뒤 답을 수정해 이어 가세요."
        if card["state"] == "CONFLICT":
            r.update(status="NEED_EXPERT", reason="FACT_CONFLICT")
    return r


def _expert(kb: KB, reason: str, message: str, **extra: Any) -> dict:
    return {"status": "NEED_EXPERT", "stage": STAGE, "stage_title": kb.stages[STAGE]["title"],
            "reason": reason, "message": message, **extra}


def _classification_check(kb: KB, answers: dict, s3: dict) -> dict | None:
    """지정 여부가 같아도 번호 범위·금지 조건을 바꿀 수 있는 미확인 규칙은 남긴다."""
    from .engine import UNDET, _resolution, eval_stage

    fired = [b["rule_id"] for b in s3["basis"]]
    current = set(_designated_prefixes(kb, fired)[0])

    def restrictions(ids):
        return {p["id"] for p in kb.s5_rules.get("prohibitions", [])
                if any(r.startswith(pre) for r in ids for pre in p["when"].get("s3_fired", []))}

    current_restrictions = restrictions(fired)
    st = eval_stage(kb, "S3", answers)
    pending = {}
    possible = set(current)
    for rid, e in st["evals"].items():
        if (e.status != UNDET or e.rule.concludes != "DESIGNATED" or e.rule.complement_of
                or kb.sources[e.rule.source]["evidence"] != "LAW"):
            continue
        extended = fired + [rid]
        prefixes = set(_designated_prefixes(kb, extended)[0])
        if prefixes != current or restrictions(extended) != current_restrictions:
            pending[rid] = e
            possible.update(prefixes)
    if not pending:
        return None
    cards = _resolution(kb, "S3", {**st, "evals": pending}, answers)
    nxt = next((c for c in cards if c["state"] == "MISSING"), None)
    status = "NEED_TEST" if (nxt and nxt["cost"] == "TEST") or (not nxt and all(c["cost"] == "TEST" for c in cards)) else "NEED_INFO"
    if not nxt and any(c["state"] == "CONFLICT" for c in cards):
        status = "NEED_EXPERT"
    excluded = set(kb.s4_map.get("excluded_codes", []))
    return {"status": status, "stage": STAGE, "stage_title": kb.stages[STAGE]["title"],
            "reason": "CLASSIFICATION_INCOMPLETE", "resolution": cards,
            "message": "지정폐기물에는 해당하지만, 분류번호나 재활용 금지·제한을 바꿀 수 있는 조건을 더 확인해야 합니다.",
            "candidates": [c["id"] for c in kb.annex4["codes"] if c["section"] == "DESIGNATED"
                           and c["id"] not in excluded and any(c["id"].startswith(p) for p in possible)],
            "next_question": None if nxt is None else {
                "fact": nxt["fact"], "question": nxt["question"], "type": nxt["type"],
                "allowed_values": nxt.get("allowed_values"), "test": nxt.get("test"),
                "unit": nxt.get("unit"), "asked_for_stage": "S3"}}


def _all_reasons_match_material(kb: KB, s3: dict, mat_prefixes: list[str]) -> bool:
    """성립한 지정 사유마다 그 번호 범위가 소재 번호와 겹치는지."""
    m = kb.s4_map["designated"]
    for b in s3.get("basis", []):
        keys = [k for k in m if b["rule_id"].startswith(k)]
        rng = m[max(keys, key=len)] if keys else []
        if not any(c["id"].startswith(r) and any(c["id"].startswith(p) for p in mat_prefixes)
                   for c in kb.annex4["codes"] for r in rng):
            return False
    return True


def general_material_options(kb: KB, answers: dict) -> tuple[str | None, list[str]]:
    material_answer = answers.get("material")
    material_id = material_answer.values[0] if material_answer and material_answer.kind == "VALUE" else None
    question = kb.s4_map.get("general_material_questions", {}).get(material_id)
    if not question:
        return None, []
    codes = kb.s4_map["general_code_by_answer"][question]
    answer = answers.get(question)
    return question, ([codes[answer.values[0]]] if answer and answer.kind == "VALUE"
                      else list(dict.fromkeys(codes.values())))


def evaluate_s4(kb: KB, answers: dict, decided: list[dict]) -> dict:
    """반환: {"decided": entry} 또는 {"result": 미확정 결과}"""
    from .kb import material as _material

    s3 = next(d for d in decided if d["stage"] == "S3")
    designated = s3["conclusion"] == "DESIGNATED"
    mat = _material(kb, answers)
    mat_codes = (mat or {}).get("codes") or {}
    codes = _code_index(kb)
    excluded = set(kb.s4_map.get("excluded_codes", []))
    map_note: list[str] = []
    used_facts: dict[str, Any] = {}
    material_question, material_options = general_material_options(kb, answers)

    if designated:
        check = _classification_check(kb, answers, s3)
        if check:
            return {"result": check}
        fired = [b["rule_id"] for b in s3["basis"]]
        prefixes, map_note = _designated_prefixes(kb, fired)
        section = "DESIGNATED"
        if not prefixes:
            return {"result": _expert(kb, "MAPPING_MISSING",
                                      "지정폐기물로 판정됐지만 해당 별표 4 그룹 대응표가 없습니다.", fired_rules=fired)}
    elif mat and mat.get("no_general_code"):
        return {"result": _expert(
            kb, "NO_MIXTURE_RULE",
            "여러 소재가 섞여 나누기 어려운 폐기물의 분류번호를 정하는 법령 규정을 확인하지 못해 번호를 정하지 않습니다. "
            "나눌 수 있으면 소재별로 따로 문진하고, 어렵다면 섞인 소재와 대략의 비율을 정리해 관할 시·군·구에 확인하세요.")}
    elif mat and mat.get("code_needs_test"):
        spec = kb.materials.get("code_tests", {}).get(mat["code_needs_test"], {})
        return {"result": {"status": "NEED_TEST", "stage": STAGE, "stage_title": kb.stages[STAGE]["title"],
                           "reason": "CODE_NEEDS_TEST", "message": spec.get("message", "번호를 정하려면 시험·확인이 필요합니다."),
                           "required_test": spec.get("test")}}
    elif material_question:
        answer = answers.get(material_question)
        if answer is None or answer.kind != "VALUE":
            labels = kb.facts[material_question]["values"]
            card = _card(material_question, kb, answers, labels)
            return {"result": {**_open(kb, card, material_options), "candidates": material_options}}
        section = "GENERAL"
        prefixes = material_options
        used_facts["material"] = answers["material"].to_json()
        used_facts[material_question] = answer.to_json()
    elif mat_codes.get("GENERAL"):
        # 소재가 별표 4 번호를 정한다(예: 고철 → 51-29-01). 그룹 목록을 묻지 않는다.
        section = "GENERAL"
        prefixes = list(mat_codes["GENERAL"])
        used_facts["material"] = answers["material"].to_json()
    else:
        section = "GENERAL"
        kind = answers.get("waste_kind")
        kind_v = kind.values[0] if kind is not None and kind.kind == "VALUE" else None
        prefixes = kb.s4_map["general_by_kind"].get(kind_v, []) if kind_v else []
        if kind_v:
            used_facts["waste_kind"] = kind.to_json()
        if not prefixes:
            g = answers.get("general_group")
            units = general_units(kb.annex4)
            allowed = {k: f"{k} {v}" for k, v in units.items()}
            if g is None or g.kind != "VALUE":
                card = _card("general_group", kb, answers, allowed)
                return {"result": _open(kb, card, ["사업장일반폐기물 분류 그룹 선택"])}
            prefixes = [g.values[0]]
            used_facts["general_group"] = g.to_json()

    candidates = [c for c in kb.annex4["codes"] if c["section"] == section and c["id"] not in excluded
                  and any(c["id"].startswith(p) for p in prefixes)]
    if not candidates:
        return {"result": _expert(kb, "NO_CODE_IN_RANGE", f"번호 범위 {prefixes}에 해당하는 별표 4 번호가 없습니다.")}
    if designated and mat_codes.get("DESIGNATED") and _all_reasons_match_material(kb, s3, mat_codes["DESIGNATED"]):
        # 지정 사유가 모두 소재 자체에서 나온 경우에만(예: 액상 PP → 01-01-02) 소재 번호로 좁힌다.
        # 기름·PCB·유해화학물질 등 다른 사유가 하나라도 있으면 좁히지 않는다(그 사유의 번호를 지우지 않음).
        narrowed = [c for c in candidates if any(c["id"].startswith(p) for p in mat_codes["DESIGNATED"])]
        if narrowed:
            candidates = narrowed
            used_facts["material"] = answers["material"].to_json()
    allowed = {c["id"]: f"{c['id']} {c['name']}" for c in candidates}
    guide = _guide_definitions()
    hints = {cid: guide[cid] for cid in allowed if cid in guide}

    a = answers.get("code")
    user_selected = False
    if len(candidates) == 1 and (a is None or a.kind == "UNKNOWN"):
        chosen = candidates[0]
    elif a is None or a.kind == "UNKNOWN":
        card = _card("code", kb, answers, allowed, {"guide_hints_2023": hints,
                                                    "range": prefixes, "designated": designated})
        return {"result": _open(kb, card, list(allowed.values()))}
    elif a.kind == "CONFLICT":
        return {"result": _expert(kb, "FACT_CONFLICT", f"자료마다 분류번호가 다릅니다: {list(a.values)}",
                                  candidates=allowed)}
    else:
        cid = a.values[0]
        if cid not in allowed:
            return {"result": _expert(
                kb, "CODE_MISMATCH",
                f"고른 번호 {codes[cid]['id']} {codes[cid]['name']}은(는) 앞 단계 판정"
                f"({'지정폐기물' if designated else '사업장일반폐기물'}, 범위 {', '.join(prefixes)})과 맞지 않습니다. "
                "입력한 사실이나 기존 서류의 번호 중 어느 쪽이 맞는지 확인하세요.",
                candidates=allowed)}
        chosen = codes[cid]
        user_selected = True
        used_facts["code"] = a.to_json()

    if _is_catch_all(chosen["name"]) and len(candidates) > 1:
        conf = answers.get("no_specific_code_applies")
        specific = {k: v for k, v in allowed.items() if not _is_catch_all(codes[k]["name"])}
        if conf is None or conf.kind != "VALUE":
            card = _card("no_specific_code_applies", kb, answers, {},
                         {"specific_codes": specific, "allowed_values": None})
            return {"result": _open(kb, card, [allowed[chosen["id"]]],
                                    "'그 밖의' 번호는 같은 분류의 다른 번호에 해당하지 않을 때만 씁니다.")}
        if conf.values[0] is False:
            card = _card("code", kb, answers, specific, {"guide_hints_2023": hints, "range": prefixes})
            return {"result": _open(kb, card, list(specific.values()),
                                    "다른 세부 번호에 해당한다고 답했으므로 그 번호를 고르세요.")}
        used_facts["no_specific_code_applies"] = conf.to_json()

    entry = {
        "stage": STAGE,
        "stage_title": kb.stages[STAGE]["title"],
        "conclusion": chosen["id"],
        "label": f"{chosen['id']} {chosen['name']}",
        "basis": [_code_basis(kb, chosen)],
        "items": [],
        "facts_used": used_facts,
        "reviewed": kb.s4_map.get("review") == "REVIEWED",
        "law_based": True,
        "gaps": [],
        "user_selected": user_selected,
        "range": prefixes,
        "candidates_considered": len(candidates),
        "mapping_notes": map_note,
    }
    if chosen["id"] in guide:
        entry["guide_definition_2023"] = guide[chosen["id"]]
    plain = [f"앞 단계에서 '{s3['label']}'(으)로 정해져, 시행규칙 별표 4의 {', '.join(prefixes)} 범위 번호만 해당할 수 있습니다."]
    if user_selected:
        plain.append("이 번호는 명칭을 보고 직접 고르신 것이며, 계산기는 앞 단계 판정과 맞는지만 확인했습니다.")
    elif len(candidates) == 1:
        plain.append("이 범위에는 번호가 하나뿐이라 그대로 정했습니다.")
    if _is_catch_all(chosen["name"]) and len(candidates) > 1:
        plain.append("'그 밖의' 번호는 같은 분류의 다른 번호에 해당하지 않는다고 확인하셨기 때문에 씁니다.")
    because = [f"분류번호: {chosen['id']} {chosen['name']}"]
    if chosen["id"] in guide:
        because.append(f"2023 설명서의 뜻풀이(구판 기준 참고): {guide[chosen['id']]}")
    entry["explanation"] = {"plain": plain, "because": because}
    return {"decided": entry}
