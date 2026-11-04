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
            "how_to_check": [{"text": h["text"], "basis": None} for h in f.get("how_to_check", [])]}
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
    return r


def _expert(kb: KB, reason: str, message: str, **extra: Any) -> dict:
    return {"status": "NEED_EXPERT", "stage": STAGE, "stage_title": kb.stages[STAGE]["title"],
            "reason": reason, "message": message, **extra}


def evaluate_s4(kb: KB, answers: dict, decided: list[dict]) -> dict:
    """반환: {"decided": entry} 또는 {"result": 미확정 결과}"""
    s3 = next(d for d in decided if d["stage"] == "S3")
    designated = s3["conclusion"] == "DESIGNATED"
    codes = _code_index(kb)
    excluded = set(kb.s4_map.get("excluded_codes", []))
    map_note: list[str] = []
    used_facts: dict[str, Any] = {}

    if designated:
        fired = [b["rule_id"] for b in s3["basis"]]
        prefixes, map_note = _designated_prefixes(kb, fired)
        section = "DESIGNATED"
        if not prefixes:
            return {"result": _expert(kb, "MAPPING_MISSING",
                                      "지정폐기물로 판정됐지만 해당 별표 4 그룹 대응표가 없습니다.", fired_rules=fired)}
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
    allowed = {c["id"]: f"{c['id']} {c['name']}" for c in candidates}
    guide = _guide_definitions()
    hints = {cid: guide[cid] for cid in allowed if cid in guide}

    a = answers.get("code")
    user_selected = False
    if len(candidates) == 1 and (a is None or a.kind != "VALUE"):
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
    return {"decided": entry}
