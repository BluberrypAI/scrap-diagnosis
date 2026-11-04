"""판정 결과를 사람이 읽을 문장으로 바꾼다. 정해진 틀만 쓴다(LLM 없음)."""
from __future__ import annotations

STATUS_TITLE = {
    "DETERMINED": "판정 완료",
    "NEED_INFO": "확인이 더 필요합니다",
    "NEED_TEST": "시험·분석 결과가 필요합니다",
    "NEED_EXPERT": "전문가 확인이 필요합니다",
    "OUT_OF_SCOPE": "계산기 규칙 범위 밖입니다",
}


def _basis_line(b: dict) -> str:
    tag = {"LAW": "법령", "OFFICIAL_GUIDE": "공식 지침", "QA": "질의회신·해설 사례"}.get(b["evidence"], b["evidence"])
    return f"{b['title']} {b['location']} [{tag}] “{b['quote']}”"


def render_text(r: dict) -> str:
    lines = [f"■ {STATUS_TITLE.get(r['status'], r['status'])}"]

    for d in r["decided"]:
        facts = ", ".join(f"{k}={v if v == 'UNKNOWN' else v.get('value', v.get('conflict'))}"
                          for k, v in d["facts_used"].items())
        item = f" — {', '.join(d['items'])}" if d.get("items") else ""
        lines.append(f"- {d['stage_title']}: {d['label']}{item}  (입력 사실: {facts or '없음'})")
        for g in d.get("gaps", []):
            lines.append(f"    확인 못 한 근거: {g}")
        if d.get("user_selected"):
            lines.append("    (사용자가 법령 명칭 목록에서 고른 번호 — 앞 단계 판정과의 일치만 엔진이 확인함)")
        for n in d.get("mapping_notes", []):
            lines.append(f"    적용한 제외 조항: {n}")
        for a in d.get("allowed_types", []):
            pre = {True: "사전 분석·확인 필요", False: "사전 분석 불필요", None: a["pre_analysis_text"]}[a["pre_analysis_required"]]
            lines.append(f"    · {a['r_code']} [{pre}] {a['definition'] or ''}")
        if d.get("guide_definition_2023"):
            lines.append(f"    참고(2023 설명서, 구판 기준): {d['guide_definition_2023']}")
        for b in d["basis"]:
            lines.append(f"    근거: {_basis_line(b)}")
            for s in b.get("supporting", []):
                lines.append(f"    보충: {s['title']} {s['location']} “{s['quote']}”")

    if r.get("message"):
        lines.append("")
        lines.append(r["message"])

    if r.get("pending_stages"):
        for p in r["pending_stages"]:
            lines.append(f"- 다음 단계 '{p['title']}'는 아직 계산기에 없습니다.")

    if r.get("resolution"):
        lines.append("")
        lines.append(f"'{r['stage_title']}'을(를) 정하려면 아래 중 하나가 확인되어야 합니다.")
        for i, c in enumerate(r["resolution"], 1):
            state = {"MISSING": "아직 답 안 함", "UNKNOWN": "모름으로 답함", "CONFLICT": "자료끼리 다름"}[c["state"]]
            lines.append(f"{i}) {c['question']}  [{state}]")
            if c["state"] == "CONFLICT":
                lines.append(f"    서로 다른 값: {c['conflicting_values']} — 어느 자료가 맞는지 확인하세요.")
            if c.get("test"):
                t = c["test"]
                lines.append(f"    필요한 시험: {t['item']} — {t['method']} (보고: {t['report']})")
            opts = c.get("allowed_values") or c.get("specific_codes")
            if c["fact"] in {"code", "general_group", "no_specific_code_applies"} and opts:
                label = "다른 세부 번호" if c.get("specific_codes") else "고를 수 있는 번호"
                lines.append(f"    {label} ({len(opts)}개):")
                for k, v in list(opts.items())[:25]:
                    hint = c.get("guide_hints_2023", {}).get(k)
                    lines.append(f"      - {v}" + (f"  ※ 2023 설명서: {hint}" if hint else ""))
                if len(opts) > 25:
                    lines.append(f"      … 외 {len(opts) - 25}개 (JSON 참고)")
            if c.get("derived_from"):
                lines.append("    이 항목은 아래 단계의 판정 결과로 정해집니다.")
            shown = c["decides"][:6]
            for d in shown:
                tail = f" (함께 필요: {'; '.join(d['also_needs'])})" if d["also_needs"] else ""
                lines.append(f"    · '{d['if']}'이면 ⇒ {d['then']}{tail}")
                lines.append(f"      근거: {_basis_line(d['basis'])}")
            if len(c["decides"]) > len(shown):
                rest = len(c["decides"]) - len(shown)
                lines.append(f"    · 그 밖에 {rest}개 경우가 더 있습니다(JSON의 decides 참고).")
            for h in c["how_to_check"]:
                src = f" (근거: {h['basis']['title']})" if h["basis"] else " (실무 안내)"
                lines.append(f"    확인 방법: {h['text']}{src}")
            if c.get("note"):
                lines.append(f"    참고: {c['note']['text']}")
        for n in r.get("complement", []):
            lines.append(f"※ {n['when']}에만 '{n['conclusion']}'로 정합니다. 근거: {_basis_line(n['basis'])}")
            for g in n.get("gaps", []):
                lines.append(f"   (이 결론의 한계: {g})")

    if r.get("next_question"):
        lines.append("")
        q = r["next_question"]
        via = f" ['{q['asked_for_stage']}' 단계 판정을 위해]" if q.get("asked_for_stage") else ""
        lines.append(f"다음 질문: {q['question']}{via}")
        if q.get("test"):
            lines.append(f"  → 시험이 필요합니다: {q['test']['item']} ({q['test']['method']}). 결과를 받아 입력하세요.")

    if r.get("weak_basis") and r["status"] in {"DETERMINED", "NEED_EXPERT"}:
        lines.append("")
        lines.append("주의: 이 결론에 쓰인 규칙 중 사람이 아직 검토하지 않았거나 해석 자료에 기댄 것이 있습니다.")

    lines.append("")
    versions = "; ".join(f"{v['title']} {v['version']}" for v in r["law_versions"].values()) or "아직 적용된 조문 없음"
    lines.append(f"규칙 DB {r['rule_db_version']} · 적용 법령 판: {versions}")
    return "\n".join(lines)
