"""판정 결과를 사람이 읽을 안내문으로 바꾼다. 정해진 틀만 쓴다(LLM 없음).

구성: 한 줄 결론 → 단계별 결론과 '왜'(쉬운 설명 + 입력값과 기준 비교) → 아직 확인할 것 →
근거 원문(조문 그대로) → 용어 풀이. 쉬운 설명은 법적 효력이 없고 근거 원문이 우선한다.
"""
from __future__ import annotations

STATUS_TITLE = {
    "DETERMINED": "판정 완료",
    "NEED_INFO": "확인이 더 필요합니다",
    "NEED_TEST": "시험·분석 결과가 필요합니다",
    "NEED_EXPERT": "전문가 확인이 필요합니다",
    "OUT_OF_SCOPE": "계산기가 판정할 수 없는 범위입니다",
}
EVIDENCE = {"LAW": "법령", "OFFICIAL_GUIDE": "공식 지침", "QA": "질의회신·해설 사례"}
STATE = {"MISSING": "아직 답 안 함", "UNKNOWN": "모름으로 답함", "CONFLICT": "자료끼리 다름"}


def _headline(r: dict) -> str:
    summary = r.get("summary") or {}
    if r["status"] == "DETERMINED" or r.get("provisional"):
        tail = " (잠정)" if r.get("provisional") else ""
        return " → ".join(summary.values()) + tail
    if r.get("resolution"):
        return f"'{r['stage_title']}'을(를) 정하려면 확인이 더 필요합니다."
    return r.get("message", "")


def render_text(r: dict, glossary: dict | None = None) -> str:
    L: list[str] = [f"■ {STATUS_TITLE.get(r['status'], r['status'])}", _headline(r), ""]
    sources: dict[tuple, dict] = {}

    def keep(b: dict) -> None:
        sources.setdefault((b["title"], b["location"]), b)

    # ---------- 단계별 결론과 이유
    for d in r["decided"]:
        item = f" — {', '.join(d['items'])}" if d.get("items") else ""
        L.append(f"▶ {d['stage_title']}: {d['label']}{item}")
        exp = d.get("explanation") or {}
        for p in exp.get("plain", []):
            L.append(f"   왜: {p}")
        for b in exp.get("because", []):
            L.append(f"   · {b}")
        for g in d.get("gaps", []):
            L.append(f"   ※ 확인하지 못한 점: {g}")
        for n in d.get("mapping_notes", []):
            L.append(f"   ※ 적용한 제외 조항: {n}")
        for b in d.get("basis", []):
            keep(b)
        L.append("")

    if r.get("message") and r.get("resolution") is None:
        L += [r["message"], ""]
    if r.get("provisional"):
        L += ["※ 아직 사람이 검토하지 않은 규칙이나 해석 자료에 기댄 결론이라 잠정 결론으로 표시합니다.", ""]
    for p in r.get("pending_stages", []):
        L += [f"※ 다음 단계 '{p['title']}'는 아직 계산기에 없습니다.", ""]

    # ---------- 아직 확인할 것
    if r.get("resolution"):
        if r.get("message"):
            L += [r["message"], ""]
        L.append(f"▷ '{r['stage_title']}'을(를) 정하려면 아래 중 하나가 확인되어야 합니다.")
        for i, c in enumerate(r["resolution"], 1):
            L.append(f"{i}) {c['question']}  [{STATE.get(c['state'], c['state'])}]")
            if c.get("derived_from"):
                L.append("   이 항목은 다음 단계 질문에 답하면 정해집니다.")
            if c["state"] == "CONFLICT":
                L.append(f"   자료마다 값이 다릅니다: {c['conflicting_values']} — 어느 자료가 맞는지 확인하세요.")
            shown = c["decides"][:5]
            for dd in shown:
                tail = f" (함께 필요: {'; '.join(dd['also_needs'])})" if dd["also_needs"] else ""
                L.append(f"   · '{dd['if']}'이면 → {dd['then']}{tail}")
                if dd.get("plain"):
                    L.append(f"     왜: {dd['plain']}")
                keep(dd["basis"])
            if len(c["decides"]) > len(shown):
                L.append(f"   · 그 밖에 {len(c['decides']) - len(shown)}개 경우가 더 있습니다(JSON의 decides 참고).")
            if c.get("test"):
                t = c["test"]
                L.append(f"   필요한 시험: {t['item']} — {t['method']} (결과서에 받을 것: {t['report']})")
            opts = c.get("allowed_values") or c.get("specific_codes")
            if c["fact"] in {"code", "general_group", "no_specific_code_applies"} and opts:
                L.append(f"   {'다른 세부 번호' if c.get('specific_codes') else '고를 수 있는 번호'} ({len(opts)}개):")
                for k, v in list(opts.items())[:25]:
                    hint = (c.get("guide_hints_2023") or {}).get(k)
                    L.append(f"     - {v}" + (f"  — 뜻(2023 설명서): {hint}" if hint else ""))
                if len(opts) > 25:
                    L.append(f"     … 외 {len(opts) - 25}개 (JSON 참고)")
            for h in c["how_to_check"]:
                src = f" (근거: {h['basis']['title']})" if h.get("basis") else ""
                L.append(f"   확인 방법: {h['text']}{src}")
            if c.get("note"):
                L.append(f"   참고: {c['note']['text']}")
        for n in r.get("complement", []):
            L.append(f"※ {n['when']}에만 '{n['conclusion']}'(으)로 정합니다.")
            keep(n["basis"])
        L.append("")
        if r.get("next_question"):
            q = r["next_question"]
            via = f" ['{q['asked_for_stage']}' 판정을 위해]" if q.get("asked_for_stage") else ""
            L.append(f"다음 질문: {q['question']}{via}")
            if q.get("test"):
                L.append(f"  → 시험이 필요합니다: {q['test']['item']} ({q['test']['method']}). 결과를 받아 입력하세요.")
            L.append("")

    # ---------- 문의 안내
    if r.get("consult"):
        cs = r["consult"]
        L.append("▷ 계산기가 정하지 않는 지점입니다. 관할 기관에 확인하세요.")
        L.append(f"   이유: {cs['why']}")
        if r.get("reference_conclusion"):
            rc = r["reference_conclusion"]
            L.append(f"   참고(확정 아님): 사례상으로는 '{rc['label']}'일 수 있습니다.")
            for b in rc.get("basis", []):
                keep(b)
        for w in cs["where"]:
            L.append(f"   문의처: {w['name']}" + (f" — {w['when']}" if w.get("when") else ""))
            if w.get("basis"):
                L.append(f"     (관할 근거: {w['basis']['title']} {w['basis']['location']})")
        L.append("   질의서 초안:")
        L += ["     " + x for x in cs["draft"].splitlines()]
        L.append("")

    # ---------- 근거 원문
    if sources:
        L.append("근거 원문 (쉬운 설명보다 이 원문이 우선합니다)")
        for b in sources.values():
            tag = EVIDENCE.get(b.get("evidence"), b.get("evidence", ""))
            L.append(f"- {b['title']} {b['location']} [{tag}]: “{b['quote']}”")
            for s in b.get("supporting", []):
                L.append(f"  보충: {s['title']} {s['location']}: “{s['quote']}”")
        L.append("")

    # ---------- 용어 풀이 (안내문에 실제로 나온 용어만)
    body = "\n".join(L)
    terms = [(t, d) for t, d in (glossary or r.get("glossary") or {}).items() if t in body]
    if terms:
        L.append("용어 풀이")
        for t, d in terms:
            L.append(f"- {t}: {d}")
        L.append("")

    versions = "; ".join(f"{v['title']} {v['version']}" for v in r["law_versions"].values()) or "아직 적용된 조문 없음"
    L.append(f"기준일 {r.get('as_of')} · 규칙 DB {r['rule_db_version']} · 적용 법령 판: {versions}")
    return "\n".join(L)
