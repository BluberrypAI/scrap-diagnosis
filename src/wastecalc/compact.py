"""대화용 간략 응답.

엔진 결과(evaluate)는 근거 원문과 모든 경우의 수를 담아 수만~십만 자가 될 수 있다.
대화 중에는 다음 질문에 필요한 것만 보낸다: 상태, 지금까지 결론, 다음 질문(보기·왜 묻는지), 모름 항목의 확인 방법.
근거 원문과 경우의 수 전체는 explain 도구(전체 결과)로 받는다. 판정 내용은 바뀌지 않는다.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from .kb import KB, RULES_DIR

MAX_CHOICES = 60
MAX_OTHER_QUESTIONS = 5
MAX_LISTED_CANDIDATES = 12   # 후보가 이 수 이하일 때만 번호 목록을 같이 보낸다
MAX_LAW_QUOTES = 2           # 질문 옆에 보여 줄 조문이 이보다 많으면 생략(답에 따라 갈리는 경우가 많음)


def _choices(kb: KB, fid: str, allowed: dict | None) -> list[dict] | None:
    f = kb.facts[fid]
    if f["type"] == "bool":
        opts = [{"value": True, "label": "예"}, {"value": False, "label": "아니오"}]
    elif f["type"] == "enum":
        values = allowed if allowed is not None else f["values"]
        hints = f.get("value_hints", {})
        if fid == "code":
            from .annex4 import _guide_definitions

            hints = {k: f"(2023 설명서 뜻풀이, 구판 참고) {v}" for k, v in _guide_definitions().items()}
        group_of = {v: g for g, vs in f.get("value_groups", {}).items() for v in vs}
        opts = []
        for k, v in (list(values.items()) if f.get("value_groups") else list(values.items())[:MAX_CHOICES]):
            o = {"value": k, "label": v}
            if k in hints:
                o["hint"] = hints[k]
            if k in group_of:
                o["group"] = group_of[k]
            opts.append(o)
    else:
        return None  # 숫자: 값을 직접 입력
    return opts + [{"value": "UNKNOWN", "label": "모름"}]


def _law(card: dict) -> list[dict] | None:
    """이 질문이 가르는 조문(적을 때만). 화면에서 질문 옆에 '○○은 “…”로 규정합니다'로 보여 준다."""
    seen: dict[tuple, dict] = {}
    for d in card.get("decides", []):
        b = d.get("basis") or {}
        if b.get("quote"):
            seen.setdefault((b.get("title"), b.get("location"), b["quote"]),
                            {"cite": f"{b.get('title', '')} {b.get('location', '')}".strip(), "quote": b["quote"],
                             "evidence": b.get("evidence")})
    if not seen or len(seen) > MAX_LAW_QUOTES:
        return None
    return list(seen.values())


def _value_text(kb: KB, fid: str, j: Any) -> str:
    from .engine import InputError, parse_answer, value_text

    try:
        return value_text(kb, fid, parse_answer(kb, fid, j))
    except InputError:
        return str(j)


def _trail(kb: KB, r: dict) -> list[dict]:
    """판정 근거를 단계 순서대로: 무엇을 답해서 → 어떤 조문으로 → 어떤 결론이 났는지."""
    out = []
    for d in r.get("decided", []):
        out.append({
            "stage": d["stage"], "title": d["stage_title"], "outcome": d["label"],
            "plain": ((d.get("explanation") or {}).get("plain") or [None])[0],
            # '아님' 결론은 원문이 표 제목뿐이라, 경로마다 왜 해당하지 않았는지를 같이 보낸다
            "because": (d.get("explanation") or {}).get("because", [])[:6],
            "answers": [{"fact": f, "question": kb.facts[f]["question"], "label": kb.facts[f].get("label", f),
                         "value_text": _value_text(kb, f, j)}
                        for f, j in (d.get("facts_used") or {}).items() if not kb.facts[f].get("derived_from")],
            "basis": [{"cite": f"{b['title']} {b['location']}", "quote": b["quote"], "evidence": b.get("evidence"),
                       "law_version": b.get("law_version")} for b in d.get("basis", [])[:2]],
        })
    return out


def _recycling_groups(allowed: list[dict]) -> dict:
    """별표 4의3의 '사전 분석·확인' 칸으로 묶는다. 같은 R코드가 양쪽 칸에 있을 수 있다(예: R-10)."""
    groups: dict[str, list] = {"no_pre_analysis": [], "pre_analysis": [], "unmarked": []}
    for a in allowed:
        key = {False: "no_pre_analysis", True: "pre_analysis"}.get(a["pre_analysis_required"], "unmarked")
        if all(x["r_code"] != a["r_code"] for x in groups[key]):
            groups[key].append({"r_code": a["r_code"], "definition": a["definition"]})
    return {k: v for k, v in groups.items() if v}


def _why(card: dict) -> str | None:
    """왜 묻는지 한 줄. 경우가 많으면 요약."""
    decides = card.get("decides") or []
    plains = list(dict.fromkeys(d["plain"] for d in decides if d.get("plain")))
    if not plains:
        return None
    if len(plains) > 2:
        return "답에 따라 확인할 법적 기준이 달라집니다. 해당 조건만 이어서 확인합니다."
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


@lru_cache(maxsize=1)
def question_groups() -> dict:
    """rules/question_groups.yaml: 화면에서 여러 사실을 한 번에 묻는 묶음과 사업장 공통 사실. 판정에는 쓰지 않는다."""
    p = RULES_DIR / "question_groups.yaml"
    if not p.exists():
        return {"groups": {}, "site_facts": []}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _no_value(f: dict) -> Any:
    if f["type"] == "bool":
        return False
    if f["type"] == "enum" and "none" in f.get("values", {}):
        return "none"
    return None


def _group_question(kb: KB, r: dict, nq: dict, res: list[dict]) -> dict | None:
    """다음 질문이 묶음에 속하고, 묶음 안에 지금 필요한 미답 사실이 2개 이상이면 한 화면용 묶음을 만든다."""
    answered = set(r.get("answers", {}))
    cards = {c["fact"]: c for c in res}
    for gid, g in question_groups().get("groups", {}).items():
        if nq["fact"] not in g["facts"]:
            continue
        missing = [f for f in g["facts"] if f in kb.facts and f not in answered]
        if g["kind"] != "one_of":  # 지금 판정 경로에 실제로 걸린 사실만(관계없는 항목은 묻지 않음)
            missing = [f for f in missing if f == nq["fact"] or (f in cards and cards[f]["state"] == "MISSING")]
        if len(missing) < 2:
            return None
        out: dict[str, Any] = {"id": gid, "kind": g["kind"], "title": g["title"], "help": g.get("help"),
                               "facts": missing}
        if g["kind"] == "one_of":
            if set(g["facts"]) - set(missing):
                return None
            none = g["none"]
            opts = [{"label": none["label"], "answers": dict(none["answers"])}]
            opts += [{"label": o["label"], "hint": o.get("hint"), "answers": dict(o["answers"])} for o in g.get("options", [])]
            ef = g.get("expand_enum")
            if ef:
                opts += [{"label": label, "answers": {**none["answers"], ef: v}}
                         for v, label in kb.facts[ef]["values"].items() if v != none["answers"].get(ef)]
            if g.get("unknown"):
                opts.append({"label": "모름", "answers": dict(g["unknown"]["answers"])})
            out["options"] = opts
        elif g["kind"] == "each":
            items = []
            for f in missing:
                card = cards.get(f, {})
                item = {"fact": f, "label": kb.facts[f].get("label", f), "question": kb.facts[f]["question"],
                        "choices": _choices(kb, f, card.get("allowed_values")),
                        "how_to_check": [h["text"] for h in (card or kb.facts[f]).get("how_to_check", [])]}
                if card:
                    item["why"] = _why(card)
                    law = _law(card)
                    if law:
                        item["law"] = law
                items.append(item)
            out["items"] = items
            no = {f: _no_value(kb.facts[f]) for f in missing}
            if all(v is not None for v in no.values()):
                out["all_no"] = {"label": g.get("all_no_label", "모두 아니오"), "answers": no}
        elif g["kind"] == "report":
            items = []
            for f in missing:
                fact, card = kb.facts[f], cards.get(f, {})
                item = {"fact": f, "label": fact.get("label", f), "unit": fact.get("unit"),
                        "test": {k: fact["test"][k] for k in ("item", "method", "report") if k in fact.get("test", {})}}
                thr = _thresholds(card) if card else []
                if thr:
                    item["thresholds"] = thr
                items.append(item)
            out.update(items=items, has_report_label=g.get("has_report_label", "성적서가 있어요"),
                       no_report_label=g.get("no_report_label", "아직 없어요"))
        return out
    return None


def material_first(kb: KB, r: dict) -> dict | None:
    """문진 정책: 폐기물 종류도 소재도 아직 없으면 엔진의 다음 질문 대신 소재를 먼저 묻는다.

    법 판단 엔진(evaluate)은 법 단계 순서를 그대로 두고, 사용자에게 보여 줄 질문 순서만 여기서 바꾼다.
    소재를 답하면 apply_material이 폐기물 종류와 본질적 사실을 채운다(법 판단은 하지 않음).
    """
    nq = r.get("next_question")
    given = r.get("answers", {})
    if nq and "material" in kb.facts and "material" not in given and "waste_kind" not in given:
        mf = kb.facts["material"]
        return {"fact": "material", "question": mf["question"], "type": "enum", "allowed_values": None,
                "unit": None, "test": None, "asked_for_stage": None}
    return nq


def compact(r: dict, kb: KB, answers: dict | None = None) -> dict:
    """answers(원래 입력)를 주면 남은 분류번호 후보 수와 보기별 남는 수도 붙인다."""
    out: dict[str, Any] = {k: r[k] for k in ("status", "summary", "conclusion", "as_of", "strict", "rule_db_version")
                           if k in r}
    if r.get("required_test"):
        out["required_test"] = r["required_test"]
    for k in ("reason", "message", "provisional", "stage", "stage_title"):
        if r.get(k) is not None:
            out[k] = r[k]
    out["assessment_scope"] = r.get("assessment_scope", "classification")
    out["assessment_complete"] = r.get("assessment_complete", False)
    if not r.get("next_question"):
        out["checks"] = r.get("checks", [])
    if r.get("reporting"):
        out["reporting"] = {k: ({f: v for f, v in item.items() if f != "resolution"} if isinstance(item, dict) else item)
                            for k, item in r["reporting"].items()}
    out["decided"] = [{
        "stage": d["stage"], "label": d["label"],
        **({"user_selected": d["user_selected"]} if "user_selected" in d else {}),
        "why": " ".join((d.get("explanation") or {}).get("plain", [])) or None,
        "because": (d.get("explanation") or {}).get("because", [])[:4],
        **({"gaps": d["gaps"]} if d.get("gaps") else {}),
        **({"allowed_types": [a["r_code"] + (" (사전 분석 필요)" if a["pre_analysis_required"] else "")
                              for a in d["allowed_types"]],
            "recycling_groups": _recycling_groups(d["allowed_types"])} if d.get("allowed_types") else {}),
    } for d in r.get("decided", [])]
    if not r.get("next_question"):  # 판정 근거는 끝났거나 멈췄을 때만(대화 중 응답 크기를 줄임)
        out["trail"] = _trail(kb, r)
    if answers is not None:
        from .candidates import code_candidates

        cands = code_candidates(kb, answers, r)
        names = {c["id"]: c["name"] for c in kb.annex4["codes"]}
        out["candidates"] = {"count": len(cands), "what": "남은 별표 4 분류번호 후보"}
        if len(cands) <= MAX_LISTED_CANDIDATES:
            out["candidates"]["codes"] = [{"code": c, "name": names.get(c, "")} for c in cands]

    res = r.get("resolution") or []
    nq = material_first(kb, r)
    if nq:
        card = next((c for c in res if c["fact"] == nq["fact"]), None)
        fact = kb.facts[nq["fact"]]
        purpose_stage = nq.get("asked_for_stage") or r.get("stage")
        purpose = {"S0": "폐기물 해당 여부 확인", "S1": "적용 법률 확인", "S2": "사업장 해당 여부 확인",
                   "S3": "지정 사유와 위험 조건 확인", "S4": "세부 분류번호 구분", "S5": "재활용 조건 확인",
                   "S6": "신고·처리계획 대상 확인"}.get(purpose_stage, "분류 조건 확인")
        q: dict[str, Any] = {"fact": nq["fact"], "question": nq["question"],
                             "choices": _choices(kb, nq["fact"], nq.get("allowed_values")), "purpose": purpose,
                             "how_to_check": [h["text"] for h in (card or fact).get("how_to_check", [])]
                                             or ["물질의 재질·발생 공정과 기존 신고서·분석결과를 확인하세요. 확실하지 않으면 모름을 선택하세요."],
                             "why": purpose + "에 필요한 질문입니다."}
        if kb.facts[nq["fact"]]["type"] == "number":
            q["unit"] = kb.facts[nq["fact"]].get("unit")
        if nq["fact"] == "material" and kb.materials:
            # 묶음 보기의 설명(예: 플라스틱·고무 → "PP, PE, PVC …")
            q["group_hints"] = {g["label"]: g.get("hint", "") for g in kb.materials.get("groups", {}).values()}
        if card:
            q["why"] = _why(card) or q["why"]
            if card.get("note"):
                q["note"] = card["note"]["text"]
            thr = _thresholds(card)
            if thr:
                q["thresholds"] = thr
            law = _law(card)
            if law:
                q["law"] = law
        if answers is not None and q["choices"]:
            from .candidates import count_after

            for o in q["choices"]:
                if o["value"] != "UNKNOWN":
                    o["remaining"] = count_after(kb, answers, nq["fact"], o["value"], r.get("strict", True))
        if nq.get("test"):
            q["test"] = {k: nq["test"][k] for k in ("item", "method", "report") if k in nq["test"]}
        if nq.get("asked_for_stage"):
            q["asked_for_stage"] = nq["asked_for_stage"]
        grp = _group_question(kb, r, nq, res)
        if grp:
            q["group"] = grp
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
    if c.get("reporting"):
        for key, title in (("general_notice", "배출자 신고"), ("designated_plan", "지정폐기물 처리계획 확인")):
            item = c["reporting"][key]
            L.append(f"{title}: {item['label']}" + (" (잠정)" if item.get("provisional") else ""))
        if not q:
            L.append(c["reporting"]["scope"])
    L.append(c["more"])
    return "\n".join(L)
