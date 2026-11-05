"""판정 기록 — 이후 단계(시설 추천·수거·처리 지원)가 읽는 고정 형식.

화면용 응답(compact)과 별개다. 이후 단계는 이 기록만 읽고, 다음 규칙을 지킨다.
  "status가 DETERMINED이고 trust.level이 기준 이상인 항목만 자동으로 쓴다. 나머지는 사람 확인으로 보낸다."

- 항목마다 상태·값·근거·쓰인 사실(출처 포함)·신뢰 수준을 따로 낸다. 한 항목의 결론을 전체로 확대하지 않는다.
- 신뢰 수준은 그 결론에 쓰인 요소 중 가장 약한 것으로 정한다(확률·가중치 없음).
- 같은 입력(정규화한 답)·기준일·규칙 버전이면 같은 record_hash가 나온다.
형식: schemas/assessment_record.schema.json
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .engine import apply_material, parse_answers
from .kb import KB, material

RECORD_VERSION = "1"
ENGINE_VERSION = "0.2.0"

ITEMS = (("waste_status", "S0", "폐기물 해당 여부"), ("applicable_law", "S1", "폐기물관리법 적용 여부"),
         ("business_waste", "S2", "사업장폐기물 여부"), ("designated", "S3", "지정폐기물 여부"),
         ("code", "S4", "분류번호(시행규칙 별표 4)"), ("recycling", "S5", "재활용 가능 유형(별표 4의3)"))
TERMINAL = {"NOT_WASTE", "CIRCULAR_RESOURCE", "EXCLUDED", "HOUSEHOLD"}
FACT_RANK = {"TEST": 3, "DOCUMENT": 2, "USER": 1, "MATERIAL": 1}  # 소재에서 채운 사실은 사용자 진술 수준
HAZARD_FACTS = ("physical_state", "oil_presence", "oil_content_pct", "pcb_possible", "toxic_chemical_discard",
                "designated_residue", "residue_kind", "ph")


def _fact_json(a) -> dict:
    if a.kind == "UNKNOWN":
        return {"state": "UNKNOWN", "source": a.source}
    if a.kind == "CONFLICT":
        return {"state": "CONFLICT", "values": list(a.values), "source": a.source}
    return {"state": "VALUE", "value": a.values[0], "source": a.source}


def _trust(d: dict, facts: dict[str, dict]) -> dict:
    sources = [f["source"] for f in facts.values() if f["source"] in FACT_RANK]
    weakest = min(sources, key=lambda s: FACT_RANK[s]) if sources else None
    t = {"rules": "REVIEWED" if d["reviewed"] else "UNVERIFIED",
         "basis": "LAW" if d["law_based"] else "INTERPRETIVE",
         "facts": {"MATERIAL": "USER"}.get(weakest, weakest),
         "gaps": list(d.get("gaps") or [])}
    if "user_selected" in d:
        t["selection"] = "USER_SELECTED" if d["user_selected"] else "AUTO"
    reasons = []
    if t["rules"] != "REVIEWED":
        reasons.append("사람 검토 전 규칙")
    if t["basis"] != "LAW":
        reasons.append("법령이 아닌 해설·질의회신 근거")
    if t["gaps"]:
        reasons.append("근거 미확보 지점 있음")
    weak_input = []
    if t["facts"] == "USER":
        weak_input.append("사용자 진술에 기댄 사실")
    if t.get("selection") == "USER_SELECTED":
        weak_input.append("사용자가 목록에서 고른 번호")
    t["level"] = "low" if reasons else ("medium" if weak_input else "high")
    t["reasons"] = reasons + weak_input
    return t


def _basis(b: dict) -> dict:
    return {k: b.get(k) for k in ("source_id", "title", "location", "quote", "evidence", "law_version", "rule_id", "review")}


def _item(kb: KB, d: dict, answers: dict) -> dict:
    facts = {f: _fact_json(answers[f]) for f in (d.get("facts_used") or {}) if f in answers
             and not kb.facts[f].get("derived_from")}
    trust = _trust(d, facts)
    out = {"status": "DETERMINED" if trust["rules"] == "REVIEWED" and trust["basis"] == "LAW" and not trust["gaps"]
           else "PROVISIONAL",
           "value": d["conclusion"], "label": d["label"], "basis": [_basis(b) for b in d.get("basis", [])],
           "facts_used": facts, "trust": trust}
    if d["stage"] == "S3" and d["conclusion"] == "DESIGNATED":
        out["reasons"] = [b["rule_id"] for b in d.get("basis", [])]
    if d["stage"] == "S4":
        name = next((c["name"] for c in kb.annex4["codes"] if c["id"] == d["conclusion"]), "")
        out.update(code=d["conclusion"], name=name, how="USER_SELECTED" if d.get("user_selected") else "AUTO")
    if d["stage"] == "S5":
        out["allowed"] = [{"r_code": a["r_code"], "pre_analysis_required": a["pre_analysis_required"]}
                          for a in d.get("allowed_types", [])]
        out["prohibited"] = d["conclusion"] == "PROHIBITED"
    return out


def _open_items(kb: KB, r: dict) -> list[dict]:
    out, seen = [], set()
    nq = r.get("next_question")
    cards = list(r.get("resolution") or [])
    if nq and all(c["fact"] != nq["fact"] for c in cards):
        cards.insert(0, {"fact": nq["fact"], "question": nq["question"], "state": "MISSING",
                         "cost": kb.facts[nq["fact"]]["cost"], "test": nq.get("test")})
    for c in cards:
        if c["state"] not in {"MISSING", "UNKNOWN", "CONFLICT"} or c["fact"] in seen or c.get("derived_from"):
            continue
        seen.add(c["fact"])
        item = {"fact": c["fact"], "question": c["question"], "state": c["state"],
                "need": {"USER": "USER", "DOCUMENT": "DOCUMENT", "TEST": "TEST"}.get(c.get("cost"), "USER")}
        if c.get("test"):
            item["test"] = {k: c["test"][k] for k in ("item", "method") if k in c["test"]}
        out.append(item)
    if r.get("required_test"):
        out.append({"fact": None, "question": r.get("message") or "시험이 필요합니다.", "state": "MISSING", "need": "TEST",
                    "test": {k: r["required_test"][k] for k in ("item", "method") if k in r["required_test"]}})
    if r.get("consult"):
        out.append({"fact": None, "question": r["consult"]["why"], "state": "AUTHORITY", "need": "AUTHORITY"})
    return out


def record_hash(kb: KB, answers_raw: dict, as_of: str) -> str:
    norm = {f: a.to_json() for f, a in sorted(parse_answers(kb, answers_raw).items())}
    payload = {"answers": norm, "as_of": as_of, "rule_db_version": kb.version, "record_version": RECORD_VERSION}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def build_record(kb: KB, answers_raw: dict, r: dict) -> dict:
    """evaluate 결과 r과 그 입력(answers_raw)으로 판정 기록을 만든다. kb는 r의 기준일 보기(KB.at)."""
    answers = apply_material(kb, parse_answers(kb, answers_raw))
    decided = {d["stage"]: d for d in r.get("decided", [])}
    terminal = any(d["conclusion"] in TERMINAL for d in decided.values())
    items: dict[str, Any] = {}
    for key, stage, title in ITEMS:
        if stage in decided:
            items[key] = {"title": title, **_item(kb, decided[stage], answers)}
        else:
            current = r.get("stage") == stage or (r.get("next_question") or {}).get("asked_for_stage") == stage
            items[key] = {"title": title, "status": "NOT_APPLICABLE" if terminal else "OPEN",
                          **({"waiting_for": r.get("reason") or r["status"]} if current and not terminal else {})}
    if r.get("reporting"):
        for key in ("general_notice", "designated_plan"):
            rep = r["reporting"].get(key) or {}
            st = rep.get("status")
            status = ("NOT_APPLICABLE" if rep.get("conclusion") == "NOT_APPLICABLE" else
                      "PROVISIONAL" if st == "DETERMINED" and rep.get("provisional") else
                      "DETERMINED" if st == "DETERMINED" else "OPEN")
            items[key] = {"title": {"general_notice": "사업장폐기물 배출자 신고 대상",
                                    "designated_plan": "지정폐기물 처리계획 확인 대상"}[key],
                          "status": status, "value": rep.get("conclusion"), "label": rep.get("label"),
                          "basis": [_basis(b) for b in rep.get("basis", [])]}
    m = material(kb, answers)
    hazards = {f: (_fact_json(answers[f]) if f in answers else {"state": "NOT_ASKED"}) for f in HAZARD_FACTS
               if f in kb.facts}
    return {
        "record_version": RECORD_VERSION,
        "engine_version": ENGINE_VERSION,
        "rule_db_version": kb.version,
        "as_of": r["as_of"],
        "record_hash": record_hash(kb, answers_raw, r["as_of"]),
        "status": r["status"],
        "complete": bool(r.get("assessment_complete")) or (r["status"] == "DETERMINED"),
        "material": ({"id": m["id"], "label": m["label"], "composite": bool(m.get("composite")),
                      "catalog_review": kb.materials.get("review", "UNVERIFIED")} if m else None),
        "items": items,
        "hazards": hazards,
        "open_items": _open_items(kb, r),
        "use_rule": "status가 DETERMINED이고 trust.level이 기준 이상인 항목만 자동으로 쓰고, 나머지는 사람 확인으로 보낸다.",
    }
