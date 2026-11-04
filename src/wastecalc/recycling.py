"""S5: 재활용 가능 유형.

1) 금지·제한 판정을 먼저 한다(법 제13조의2제2항, 시행규칙 제14조의3제2항, 시행령 별표 4의3).
2) 금지가 아니면 시행규칙 별표 4의3 표에서 S4 번호의 행을 찾아 허용 R코드와 사전 분석·확인 필요 여부를 낸다.
3) 표에 행이 없으면 비고 제2호: 재활용환경성평가 승인을 받아야 재활용할 수 있다.
"""
from __future__ import annotations

from .kb import KB

STAGE = "S5"


def _b(kb: KB, src_id: str, location: str, quote: str, rule_id: str, review: str = "UNVERIFIED") -> dict:
    src = kb.sources[src_id]
    return {"source_id": src_id, "title": src["title"], "location": location, "quote": quote,
            "evidence": src["evidence"], "law_version": src["version"], "effective_on": src["effective_on"],
            "rule_id": rule_id, "review": review}


def _matches(when: dict, code: str, fired: list[str], kind: str | None) -> bool:
    if any(code.startswith(p) for p in when.get("codes_prefix", [])):
        return True
    if any(f.startswith(p) for f in fired for p in when.get("s3_fired", [])):
        return True
    return kind is not None and kind in when.get("waste_kind", [])


def evaluate_s5(kb: KB, answers: dict, decided: list[dict]) -> dict:
    s3 = next(d for d in decided if d["stage"] == "S3")
    s4 = next(d for d in decided if d["stage"] == "S4")
    code = s4["conclusion"]
    fired = [b["rule_id"] for b in s3["basis"]] if s3["conclusion"] == "DESIGNATED" else []
    kw = answers.get("waste_kind")
    kind = kw.values[0] if kw is not None and kw.kind == "VALUE" else None
    rules = kb.s5_rules
    review_ok = rules.get("review") == "REVIEWED"
    table = {r["code"]: r for r in kb.annex43["rows"]}
    row = table.get(code)
    r_defs = kb.r_codes["codes"]

    entry = {"stage": STAGE, "stage_title": kb.stages[STAGE]["title"], "items": [], "facts_used": {},
             "reviewed": review_ok, "law_based": True, "gaps": [], "code": code}

    hits = [p for p in rules["prohibitions"] if _matches(p["when"], code, fired, kind)]
    prohibited = [p for p in hits if p["kind"] == "PROHIBITED"]
    restricted = [p for p in hits if p["kind"] == "RESTRICTED"]

    table_prohibited = bool(row) and any(c["prohibited"] for c in row["cells"])
    table_types = [] if not row else [
        {"r_codes": c["r_codes"], "pre_analysis": c["pre_analysis"]} for c in row["cells"] if not c["prohibited"]]

    if prohibited:
        p = prohibited[0]
        entry.update({
            "conclusion": "PROHIBITED", "label": f"재활용 금지 — {p['label']}",
            "basis": [_b(kb, b["source"], b["location"], b["quote"], p["id"]) for b in p["basis"]],
            "explanation": {"plain": [f"'{p['label']}'은(는) 법에서 재활용을 금지한 폐기물입니다."],
                            "because": [f"분류번호 {code}가 금지 대상({p['label']})에 해당"]},
        })
        if table_types and not table_prohibited:
            # 법의 금지가 표보다 우선한다. 표와 다르면 검토 대상으로 남긴다.
            entry["gaps"].append(f"별표 4의3 표는 {code}에 재활용 유형을 두지만 금지 규정({p['id']})이 우선 적용됨 — 검토 필요")
        return {"decided": entry}

    if row is None or not row["cells"]:  # 표에 행이 없거나, 행은 있지만 유형 칸이 비어 있음(예: 51-99-00)
        n = rules["notes"]["not_listed"]
        entry.update({
            "conclusion": "NOT_LISTED",
            "label": "재활용 가능 유형이 정해지지 않음 — 재활용환경성평가 승인을 받아야 재활용 가능",
            "basis": [_b(kb, n["source"], n["location"], n["quote"], "S5-NOT-LISTED")],
            "explanation": {"plain": ["이 분류번호는 법이 재활용 방법을 정해 두지 않았습니다. "
                                      "재활용하려면 재활용환경성평가를 받아 승인을 받아야 합니다."],
                            "because": [f"시행규칙 별표 4의3 표에 {code}의 재활용 유형이 없음"]},
        })
        return {"decided": entry}

    if table_prohibited and not table_types:
        entry.update({
            "conclusion": "PROHIBITED", "label": "재활용 금지(별표 4의3 표)",
            "basis": [_b(kb, "RULE-A43", f"별표 4의3 {code} (p.{row['page']})", f"{code} 재활용 금지",
                         f"ANNEX43-{code}", "REVIEWED")],
            "gaps": ["시행규칙 제14조의3제2항의 금지 사유 중 어느 것에 해당하는지 대응표에 없음 — 표의 '재활용 금지' 표기만 따름"],
            "explanation": {"plain": ["재활용 가능 유형 표에서 이 분류번호는 '재활용 금지'로 정해져 있습니다."],
                            "because": [f"시행규칙 별표 4의3 {code}: 재활용 금지"]},
        })
        return {"decided": entry}

    allowed = []
    for cell in table_types:
        pre = cell["pre_analysis"]
        for rc in cell["r_codes"]:
            allowed.append({"r_code": rc, "definition": r_defs.get(rc),
                            "pre_analysis_required": {"해당": True, "해당없음": False}.get(pre),
                            "pre_analysis_text": pre or "원문에 표기 없음"})
    notes = [rules["notes"]["allowed_only"]]
    if any(a["pre_analysis_required"] for a in allowed):
        notes.append(rules["notes"]["pre_analysis"])
    if any(a["r_code"] == "R-10" for a in allowed):
        notes.append(rules["notes"]["r10"])
    basis = [_b(kb, "RULE-A43", f"별표 4의3 {code} (p.{row['page']})",
                " / ".join(f"{', '.join(c['r_codes'])} [사전 분석·확인: {c['pre_analysis'] or '표기 없음'}]"
                           for c in table_types), f"ANNEX43-{code}", "REVIEWED")]
    basis += [_b(kb, n["source"], n["location"], n["quote"], "S5-NOTE") for n in notes]
    if restricted:
        for p in restricted:
            basis += [_b(kb, b["source"], b["location"], b["quote"], p["id"]) for b in p["basis"]]
            entry["gaps"].append(f"재활용 제한 대상: {p['label']}")
    if any(a["pre_analysis_text"] == "원문에 표기 없음" for a in allowed):
        entry["gaps"].append(f"별표 4의3 원문에서 {code}의 사전 분석·확인 필요 여부 칸이 비어 있음")
    uniq = list(dict.fromkeys(a["r_code"] for a in allowed))
    plain = ["이 분류번호는 법이 정한 아래 재활용 방법으로만 재활용할 수 있습니다. "
             "목록에 없는 방법으로 재활용하려면 재활용환경성평가 승인이 필요합니다."]
    if any(a["pre_analysis_required"] for a in allowed):
        plain.append("'사전 분석·확인 필요' 방법은 재활용하기 전에 폐기물분석전문기관의 결과 등으로 재활용 기준을 "
                     "충족하는지 확인해야 합니다.")
    if restricted:
        plain.insert(0, "제한된 용도의 제품·원료로는 재활용할 수 없는 물질이 든 폐기물입니다.")
    because = [f"{a['r_code']}: {a['definition'] or ''}" for a in allowed if a["r_code"] != "R-10"]
    if "R-10" in uniq:
        because.append("R-10: 위 방법으로 재활용하기 위한 중간가공 폐기물을 만드는 방법")
    entry.update({
        "conclusion": "RESTRICTED" if restricted else "ALLOWED_TYPES",
        "label": ("재활용 제한 — " if restricted else "") + "재활용 가능 유형: " + ", ".join(uniq),
        "allowed_types": allowed,
        "outside_types": [_b(kb, o["source"], o["location"], o["quote"], "S5-OUTSIDE") for o in rules["outside_types"]],
        "basis": basis,
        "explanation": {"plain": plain, "because": list(dict.fromkeys(because))},
    })
    return {"decided": entry}
