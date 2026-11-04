"""대화용 간략 응답.

엔진 결과(evaluate)는 근거 원문과 모든 경우의 수를 담아 수만~십만 자가 될 수 있다.
대화 중에는 다음 질문에 필요한 것만 보낸다: 상태, 지금까지 결론, 다음 질문(보기·왜 묻는지), 모름 항목의 확인 방법.
근거 원문과 경우의 수 전체는 explain 도구(전체 결과)로 받는다. 판정 내용은 바뀌지 않는다.
"""
from __future__ import annotations

from typing import Any

from .kb import KB

MAX_CHOICES = 60
MAX_OTHER_QUESTIONS = 5


def _choices(kb: KB, fid: str, allowed: dict | None) -> list[dict] | None:
    f = kb.facts[fid]
    if f["type"] == "bool":
        opts = [{"value": True, "label": "예"}, {"value": False, "label": "아니오"}]
    elif f["type"] == "enum":
        values = allowed if allowed is not None else f["values"]
        opts = [{"value": k, "label": v} for k, v in list(values.items())[:MAX_CHOICES]]
    else:
        return None  # 숫자: 값을 직접 입력
    return opts + [{"value": "UNKNOWN", "label": "모름"}]


def _why(card: dict) -> str | None:
    """왜 묻는지 한 줄. 경우가 많으면 요약."""
    decides = card.get("decides") or []
    plains = list(dict.fromkeys(d["plain"] for d in decides if d.get("plain")))
    if not plains:
        return None
    if len(plains) > 2:
        return f"답에 따라 적용되는 법 기준이 달라집니다({len(decides)}가지 경우). 고른 뒤 해당 기준만 확인합니다."
    return " ".join(plains)


def _thresholds(card: dict) -> list[str]:
    return list(dict.fromkeys(f"{t['value']:g}{t.get('unit') or ''} {t['comparator']}" for t in card.get("thresholds", [])))


def _card_brief(kb: KB, card: dict, with_help: bool) -> dict:
    out: dict[str, Any] = {"fact": card["fact"], "question": card["question"], "state": card["state"]}
    if with_help:
        out["how_to_check"] = [h["text"] for h in card.get("how_to_check", [])]
        if card.get("test"):
            out["test"] = {k: card["test"][k] for k in ("item", "method") if k in card["test"]}
        if card.get("conflicting_values"):
            out["conflicting_values"] = card["conflicting_values"]
    return out


def compact(r: dict, kb: KB) -> dict:
    out: dict[str, Any] = {k: r[k] for k in ("status", "summary", "conclusion", "as_of", "strict", "rule_db_version")
                           if k in r}
    for k in ("reason", "message", "provisional", "stage", "stage_title"):
        if r.get(k) is not None:
            out[k] = r[k]
    out["decided"] = [{
        "stage": d["stage"], "label": d["label"],
        "why": " ".join((d.get("explanation") or {}).get("plain", [])) or None,
        "because": (d.get("explanation") or {}).get("because", [])[:4],
        **({"gaps": d["gaps"]} if d.get("gaps") else {}),
        **({"allowed_types": [a["r_code"] + (" (사전 분석 필요)" if a["pre_analysis_required"] else "")
                              for a in d["allowed_types"]]} if d.get("allowed_types") else {}),
    } for d in r.get("decided", [])]

    res = r.get("resolution") or []
    nq = r.get("next_question")
    if nq:
        card = next((c for c in res if c["fact"] == nq["fact"]), None)
        q: dict[str, Any] = {"fact": nq["fact"], "question": nq["question"],
                             "choices": _choices(kb, nq["fact"], nq.get("allowed_values"))}
        if kb.facts[nq["fact"]]["type"] == "number":
            q["unit"] = kb.facts[nq["fact"]].get("unit")
        if card:
            q["why"] = _why(card)
            thr = _thresholds(card)
            if thr:
                q["thresholds"] = thr
        if nq.get("test"):
            q["test"] = {k: nq["test"][k] for k in ("item", "method", "report") if k in nq["test"]}
        if nq.get("asked_for_stage"):
            q["asked_for_stage"] = nq["asked_for_stage"]
        out["next_question"] = q
    # 아직 답하지 않은 다른 질문(한 번에 묻고 싶을 때)과 모름·충돌 항목의 확인 방법
    others = [c for c in res if c["state"] == "MISSING" and (not nq or c["fact"] != nq["fact"])
              and not c.get("derived_from")]
    if others:
        out["other_open_questions"] = [_card_brief(kb, c, False) for c in others[:MAX_OTHER_QUESTIONS]]
    stuck = [c for c in res if c["state"] in {"UNKNOWN", "CONFLICT"}]
    if stuck:
        out["how_to_resolve"] = [_card_brief(kb, c, True) for c in stuck]
    if r.get("consult"):
        cs = r["consult"]
        out["consult"] = {"why": cs["why"], "where": [w["name"] + (f" ({w['when']})" if w.get("when") else "")
                                                      for w in cs["where"]],
                          "draft": cs["draft"]}
    if r.get("reference_conclusion"):
        out["reference_conclusion"] = r["reference_conclusion"]["label"] + " (참고 사례상, 확정 아님)"
    if r.get("pending_stages"):
        out["pending_stages"] = [p["title"] for p in r["pending_stages"]]
    out["more"] = "근거 원문·경우의 수 전체는 explain 도구로 받으세요."
    return out


def render_compact(c: dict) -> str:
    """간략 응답의 짧은 안내문."""
    L = [f"상태: {c['status']}" + (" (잠정)" if c.get("provisional") else "")]
    if c.get("summary"):
        L.append("지금까지: " + " → ".join(c["summary"].values()))
    if c.get("message") and not c.get("next_question"):
        L.append(c["message"])
    last = c["decided"][-1] if c.get("decided") else None
    if last and not c.get("next_question") and not c.get("consult"):
        if last.get("why"):
            L.append(f"왜: {last['why']}")
        for b in last.get("because", []):
            L.append(f"· {b}")
        if last.get("allowed_types"):
            L.append("재활용 가능 유형: " + ", ".join(last["allowed_types"]))
        for g in last.get("gaps", []):
            L.append(f"※ {g}")
    q = c.get("next_question")
    if q:
        L.append("")
        L.append(f"다음 질문: {q['question']}")
        if q.get("choices") and len(q["choices"]) <= 12:
            L.append("보기: " + " / ".join(f"{i}) {o['label']}" for i, o in enumerate(q["choices"], 1)))
        elif q.get("choices"):
            L.append(f"보기 {len(q['choices'])}개 (JSON의 next_question.choices)")
        elif q.get("unit") is not None:
            L.append(f"숫자로 입력({q['unit']}) 또는 모름")
        if q.get("why"):
            L.append(f"왜 묻나요: {q['why']}")
        if q.get("test"):
            L.append(f"시험 필요: {q['test']['item']} — {q['test']['method']}")
    if c.get("consult"):
        L.append("")
        L.append(f"확인이 필요한 이유: {c['consult']['why']}")
        if c.get("reference_conclusion"):
            L.append(f"참고: {c['reference_conclusion']}")
        L.append("문의처: " + " / ".join(c["consult"]["where"]))
        L.append("질의서 초안은 JSON의 consult.draft에 있습니다.")
    for h in c.get("how_to_resolve", []):
        L.append(f"[모름/불일치] {h['question']} → " + " / ".join(h.get("how_to_check", [])))
    L.append(c["more"])
    return "\n".join(L)
