"""scrap-web 문진 화면용 응답(어댑터).

엔진 판정은 바꾸지 않고, 결과를 scrap-web(`src/pages/survey/`)이 읽는 모양으로 바꾼다.
화면은 라디오 보기 한 단계만 그리므로 다음과 같이 맞춘다.
  - 보기가 묶여 있으면(소재 등) 묶음 → 항목, 두 질문으로 나눈다(화면 상태 `ui.group`).
  - 숫자 질문은 그 질문이 가르는 기준값으로 나눈 '구간 보기'로 바꾼다(대표값을 넣고, 구간 답이었다는 사실을 남긴다).
  - 성적서 묶음은 "모두 기준 이하 / 넘는 항목 있음 / 성적서 없음" 한 질문 + (넘으면) 어느 항목인지 한 질문.
  - 오염 체크리스트 같은 '항목별' 묶음은 한 질문씩 보낸다.
  - 보기마다 `answers`(엔진에 넣을 값)를 붙여 화면은 고른 보기의 answers를 그대로 돌려보내기만 하면 된다.

상태 없는 함수(build_view)로 두어 서버(scrap-server)가 답·화면 상태를 DB에 저장하고 호출할 수 있게 한다.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from .candidates import code_candidates, count_after
from .compact import compact
from .engine import evaluate
from .kb import KB, RULES_DIR, material

CONTRACT = "classification-view-v1"  # 응답 형식 버전. 필드를 빼거나 뜻을 바꾸면 올린다(추가는 그대로)
STAGES = ["S0", "S1", "S2", "S3", "S4", "S5"]
UI_KEY = "__ui"
TERMINAL = {"NOT_WASTE": "폐기물이 아니에요", "CIRCULAR_RESOURCE": "순환자원이에요(폐기물로 보지 않음)",
            "EXCLUDED": "폐기물관리법이 아닌 다른 법을 따라요", "HOUSEHOLD": "생활폐기물이에요(이 서비스 범위 밖)"}


@lru_cache(maxsize=1)
def r_code_labels() -> dict:
    p = RULES_DIR / "r_code_labels.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")).get("labels", {}) if p.exists() else {}


# ---------------------------------------------------------------- 질문

def _thresholds(r: dict, fact: str) -> list[tuple[float, str]]:
    """(기준값, 비교) — 비교는 규칙이 '성립'하는 쪽: 이상/초과/이하/미만."""
    card = next((c for c in r.get("resolution") or [] if c["fact"] == fact), None)
    out = {(float(t["value"]), t["comparator"]) for t in (card or {}).get("thresholds", [])}
    return sorted(out)


def _fmt(v: float, unit: str | None) -> str:
    s = f"{v:g}"
    return f"{s}{unit or ''}"


def _buckets(kb: KB, r: dict, fact: str) -> list[dict]:
    """기준값으로 나눈 구간 보기. 경계값이 어느 쪽에 속하는지는 규칙의 비교(이상·이하 등)를 따른다."""
    unit = kb.facts[fact].get("unit")
    ths = _thresholds(r, fact)
    if not ths:
        return []
    # 경계마다 '경계값이 아래 구간에 속하는가'(이하·초과 → 아래, 이상·미만 → 위)
    bounds: dict[float, bool] = {}
    for v, comp in ths:
        bounds[v] = comp in ("이하", "초과")
    pts = sorted(bounds)
    opts = []
    for i in range(len(pts) + 1):
        lo, hi = (pts[i - 1] if i > 0 else None), (pts[i] if i < len(pts) else None)
        parts = []
        if lo is not None:
            parts.append(f"{_fmt(lo, unit)} {'초과' if bounds[lo] else '이상'}")
        if hi is not None:
            parts.append(f"{_fmt(hi, unit)} {'이하' if bounds[hi] else '미만'}")
        if lo is None:
            rep = hi / 2 if hi > 0 else hi - 1
        elif hi is None:
            rep = lo * 1.5 if lo > 0 else lo + 1
        else:
            rep = (lo + hi) / 2
        opts.append({"label": " ~ ".join(parts) if len(parts) == 2 else parts[0], "value": round(rep, 6),
                     "range": True})
    return opts


def _law(q: dict) -> dict | None:
    if not q.get("law"):
        return None
    l0 = q["law"][0]
    return {"lead": f"{l0['cite']}은(는)", "quote": l0["quote"], "tail": "로 정합니다.", "cite": l0["cite"],
            "is_law": l0.get("evidence") == "LAW"}


def _opt(i: int, label: str, answers: dict, hint: str | None = None, remaining: Any = None) -> dict:
    o: dict[str, Any] = {"id": str(i), "label": label, "answers": answers}
    if hint:
        o["hint"] = hint
    if remaining is not None:
        o["remaining"] = remaining
    return o


def _question(kb: KB, r: dict, c: dict, answers_raw: dict, ui: dict, strict: bool) -> dict:
    q = c["next_question"]
    fact, g = q["fact"], q.get("group")
    title, helper, opts = q["question"], q.get("why"), []
    f = kb.facts[fact]

    # 성적서: 넘은 항목을 고르는 후속 질문
    if ui.get("report_exceed"):
        items = ui["report_exceed"]
        title = "기준을 넘은 항목을 골라 주세요"
        helper = "분류번호는 어느 항목이 넘었는지와 관계없이 정해지지만, 판정 기록에 남기기 위해 묻습니다."
        for i, it in enumerate(items):
            opts.append(_opt(i, it["label"], {it["fact"]: it["above"], UI_KEY: {"report_exceed": None}}))
        return {"fact": fact, "title": title, "helper": helper, "law": None, "options": opts, "kind": "report_item"}

    if g and g["kind"] == "one_of":
        title, helper = g["title"], g.get("help") or helper
        for i, o in enumerate(g["options"]):
            opts.append(_opt(i, o["label"], o["answers"], o.get("hint")))
        return {"fact": fact, "title": title, "helper": helper, "law": None, "options": opts, "kind": "choice"}

    if g and g["kind"] == "report":
        below, above_items, unknown = {}, [], {}
        for it in g["items"]:
            ths = _thresholds(r, it["fact"])
            unknown[it["fact"]] = "UNKNOWN"
            if not ths:
                continue
            lo = min(v for v, _ in ths)
            hi = max(v for v, _ in ths)
            comp = ths[0][1]
            if comp in ("이상", "초과"):     # 넘으면 지정 → 아래 값이 '기준 이하'
                below[it["fact"]], above = round(lo / 2, 6), round(hi * 1.5 if hi > 0 else hi + 1, 6)
            else:
                below[it["fact"]], above = round(hi * 1.5 if hi > 0 else hi + 1, 6), round(lo / 2, 6)
            above_items.append({"fact": it["fact"], "label": it["label"], "above": above})
        title, helper = "분석 성적서의 측정값이 기준 안에 있나요?", g.get("help")
        opts = [_opt(0, "모든 항목이 기준 이하예요", below),
                _opt(1, "기준을 넘는 항목이 있어요", {UI_KEY: {"report_exceed": above_items}}),
                _opt(2, "성적서가 아직 없어요", unknown, "필요한 시험을 안내해 드려요")]
        return {"fact": fact, "title": title, "helper": helper, "law": None, "options": opts, "kind": "report",
                "tests": [{"item": it["test"].get("item") or it["label"], "method": it["test"].get("method")}
                          for it in g["items"]]}

    if f["type"] == "number":
        for i, b in enumerate(_buckets(kb, r, fact)):
            rem = count_after(kb, answers_raw, fact, b["value"], strict)
            opts.append(_opt(i, b["label"], {fact: b["value"], UI_KEY: {"range": {fact: b["label"]}}}, None, rem))
        opts.append(_opt(len(opts), "모름", {fact: "UNKNOWN"}, "확인 방법이나 필요한 시험을 안내해 드려요"))
        return {"fact": fact, "title": title, "helper": helper, "law": _law(q), "options": opts, "kind": "range",
                "unit": f.get("unit")}

    choices = q.get("choices") or []
    grouped = any(ch.get("group") for ch in choices)
    chosen_group = (ui.get("group") or {}).get(fact)
    if grouped and not chosen_group:
        groups: dict[str, list] = {}
        for ch in choices:
            groups.setdefault(ch.get("group") or "모름", []).append(ch)
        hints = q.get("group_hints") or {}
        for i, (gl, members) in enumerate(groups.items()):
            if gl == "모름":
                opts.append(_opt(i, "모름", {fact: "UNKNOWN"}))
                continue
            rems = [m["remaining"] for m in members if isinstance(m.get("remaining"), int)]
            rem = (rems[0] if rems and min(rems) == max(rems) else f"{min(rems)}~{max(rems)}") if rems else None
            opts.append(_opt(i, gl, {UI_KEY: {"group": {fact: gl}}},
                             hints.get(gl) or " · ".join(m["label"] for m in members[:6]), rem))
        return {"fact": fact, "title": title, "helper": helper, "law": _law(q), "options": opts, "kind": "group"}
    if grouped:
        title = f"{title} — {chosen_group}"
        choices = [ch for ch in choices if ch.get("group") == chosen_group or ch["value"] == "UNKNOWN"]
    for i, ch in enumerate(choices):
        ans = {fact: ch["value"]}
        if grouped:
            ans[UI_KEY] = {"group": {fact: None}}
        opts.append(_opt(i, ch["label"], ans, ch.get("hint"), ch.get("remaining")))
    return {"fact": fact, "title": title, "helper": helper, "law": _law(q), "options": opts,
            "kind": "back_to_group" if grouped else "choice"}


# ---------------------------------------------------------------- 결과

def _evidence(c: dict) -> list[dict]:
    out = []
    for i, t in enumerate(c.get("trail") or [], 1):
        b = (t.get("basis") or [{}])[0]
        reason = " · ".join(f"{a['label']}: {a['value_text']}" for a in t.get("answers", [])) or (t.get("plain") or "")
        out.append({"num": f"{i:02d}", "title": t["title"], "cite": b.get("cite", ""), "quote": b.get("quote", ""),
                    "outcome": t["outcome"], "reason": reason, "plain": t.get("plain"), "because": t.get("because", []),
                    "is_law": b.get("evidence") == "LAW", "law_version": b.get("law_version")})
    return out


def _recycle(c: dict) -> dict | None:
    s5 = next((d for d in c.get("decided", []) if d["stage"] == "S5"), None)
    if not s5:
        return None
    labels = r_code_labels()
    g = s5.get("recycling_groups")
    if not g:
        return {"status": "PROHIBITED_OR_NOT_LISTED", "message": s5["label"], "notice": s5.get("why")}
    pair = lambda items: [[a["r_code"], labels.get(a["r_code"]) or a.get("definition") or ""] for a in items]  # noqa: E731
    return {"status": "ALLOWED", "free": pair(g.get("no_pre_analysis", [])), "analysis": pair(g.get("pre_analysis", [])),
            "unmarked": pair(g.get("unmarked", [])),
            "notice": "목표 재활용 유형에 따라 분석 요건이 달라집니다. 「사전 분석·확인 해당」 유형은 폐기물분석전문기관의 "
                      "분석 결과로 재활용 기준 충족을 먼저 확인해야 합니다. 실제 처리 가능 여부와 업체는 별도로 확인하세요."}


def _result(kb: KB, r: dict, c: dict, answers_raw: dict) -> dict:
    dec = {d["stage"]: d for d in r.get("decided", [])}
    as_of = r["as_of"]
    provisional = bool(r.get("provisional"))
    note = f"판정 기준일 {as_of}" + (" · 사람 검토 전 규칙에 따른 잠정 결과예요" if provisional else "")
    base = {"provisional": provisional, "status": r["status"], "as_of": as_of, "evidence": _evidence(c)}
    s2, s3, s4 = dec.get("S2"), dec.get("S3"), dec.get("S4")
    badges = []
    if s3:
        badges.append("지정폐기물" if s3["conclusion"] == "DESIGNATED" else "사업장일반폐기물")
    if s2:
        em = answers_raw.get("emission_facility")
        badges.append("배출시설 운영 사업장" if em is True or (isinstance(em, dict) and em.get("value") is True)
                      else s2["label"])
    if s4:
        names = {x["id"]: x["name"] for x in kb.annex4["codes"]}
        m = material(kb, {"material": _Ans(answers_raw.get("material"))}) if answers_raw.get("material") else None
        how = "직접 고른 번호예요. 앞 단계 판정과 맞는지 확인했어요" if s4.get("user_selected") else "법령 기준표에서 조회한 결과예요"
        return {**base, "kind": "code", "badges": badges, "code": s4["conclusion"], "name": names.get(s4["conclusion"], ""),
                "note": f"분류번호는 {how} · {note}", "recycle": _recycle(c),
                "treatment": {"waste_code": s4["conclusion"], "material": (m or {}).get("treatment_material"),
                              "material_label": (m or {}).get("label")}}
    terminal = next((d for d in dec.values() if d["conclusion"] in TERMINAL), None)
    if terminal:
        return {**base, "kind": "not_applicable", "badges": [d["label"] for d in dec.values()],
                "title": TERMINAL[terminal["conclusion"]], "message": (c["decided"][-1].get("why") if c.get("decided") else None),
                "note": note}
    kind = {"NEED_TEST": "test", "NEED_EXPERT": "authority", "OUT_OF_SCOPE": "out_of_scope"}.get(r["status"], "info")
    title = {"test": "시험 결과가 있어야 판정할 수 있어요", "authority": "관할 기관 확인이 필요해요",
             "out_of_scope": "이 계산기로 판정할 수 없어요", "info": "확인할 자료가 남아 있어요"}[kind]
    out = {**base, "kind": kind, "badges": [d["label"] for d in dec.values()], "title": title, "message": c.get("message"),
           "note": note, "to_check": c.get("how_to_resolve", [])}
    if c.get("required_test"):
        out["required_test"] = c["required_test"]
    if c.get("consult"):
        out["consult"] = c["consult"]
    if c.get("reference_conclusion"):
        out["reference"] = c["reference_conclusion"]
    return out


class _Ans:
    """kb.material()이 기대하는 최소 답 객체."""
    def __init__(self, raw):
        v = raw.get("value") if isinstance(raw, dict) else raw
        self.kind, self.values = ("VALUE", (v,)) if v not in (None, "UNKNOWN") else ("UNKNOWN", ())


# ---------------------------------------------------------------- 진입점

def split_ui(payload: dict) -> tuple[dict, dict]:
    """화면이 돌려보낸 보기의 answers에서 엔진 값과 화면 상태를 나눈다."""
    payload = dict(payload or {})
    ui = payload.pop(UI_KEY, None) or {}
    return payload, ui


def merge_ui(ui: dict, patch: dict) -> dict:
    out = {**(ui or {})}
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = {**out[k], **v}
            out[k] = {kk: vv for kk, vv in merged.items() if vv is not None}
        elif v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out


def build_view(kb: KB, answers_raw: dict, ui: dict | None = None, *, strict: bool = True, as_of=None,
               trail: list[int] | None = None) -> dict:
    """답(엔진 사실)과 화면 상태(ui)로 scrap-web 문진 화면 응답을 만든다. 상태를 저장하지 않는다."""
    ui = ui or {}
    r = evaluate(answers_raw, strict=strict, kb=kb, as_of=as_of)
    kbv = kb.at(r["as_of"])
    c = compact(r, kbv, answers_raw)
    count = len(code_candidates(kbv, answers_raw, r))
    trail = [*(trail or []), count]
    trail = [n for i, n in enumerate(trail) if i == 0 or n != trail[i - 1]]
    view: dict[str, Any] = {"contract": CONTRACT, "as_of": r["as_of"], "status": r["status"], "rule_db_version": kbv.version,
                            "provisional": bool(r.get("provisional"))}
    if c.get("next_question"):
        q = _question(kbv, r, c, answers_raw, ui, strict)
        stage = c["next_question"].get("asked_for_stage") or r.get("stage") or "S0"
        idx = STAGES.index(stage) + 1 if stage in STAGES else 1
        if c["next_question"]["fact"] == "material":
            idx = 1
        prev = trail[-2] if len(trail) > 1 else None
        view.update(phase="question", step={"index": idx, "total": len(STAGES)}, question=q, panel={
            "label": "남은 분류번호 후보", "count": count, "start": trail[0], "trail": trail,
            "excluded": (prev - count) if prev is not None and prev > count else 0,
            "purpose": c["next_question"].get("purpose"),
            "why": "보기마다 남는 후보 수를 함께 보여 드려요." if any("remaining" in o for o in q["options"])
                   else f"{c['next_question'].get('purpose') or '판정'}에 필요한 질문이에요."})
    else:
        view.update(phase="result", step={"index": len(STAGES), "total": len(STAGES)},
                    panel={"label": "남은 분류번호 후보", "count": count, "start": trail[0], "trail": trail, "excluded": 0},
                    result=_result(kbv, r, c, answers_raw))
    if (ui.get("range") or {}):
        view["range_answers"] = ui["range"]
    return view

