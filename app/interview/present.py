"""문진 상태 → 응답(질문 카드·판정 보드·결과 카드·인계 객체). DB를 모르는 순수 함수다.

판정은 규칙 엔진(app/engine/flow.py)과 다음 질문 계산기(app/engine/planner.py)가 정하고,
여기서는 그 결과를 화면 계약(ui-v1)과 인계 계약(diagnosis-handoff-v1) 모양으로 바꾸기만 한다.
문장은 knowledge/flow/plan.yaml·outcomes.yaml의 사람이 쓴 고정 문장을 쓴다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from app.engine.flow import TV, UNASKED, Result, evaluate, lookup
from app.engine.kb import KB
from app.engine.planner import Next, next_question, question_facts, set_path, with_unasked
from app.interview import catalog as cat

KST = timezone(timedelta(hours=9))

SOURCE_LABELS = {
    "UTTERANCE": "말함",
    "SCREENING": "묶음 답",
    "PROFILE": "기업 정보",
    "PROFILE_CONFIRMED": "기업 정보(확인됨)",
    "DERIVED": "자동",
    "DOCUMENT": "서류",
    "ASSUMED": "기본값(고칠 수 있음)",
}
NONE_ALL_LABEL = "모두 해당 없음"
EXPAND_LABEL = "해당하는 게 있어요 / 잘 모르겠어요"


@dataclass
class FactState:
    """사실 하나의 유효 값과 출처(마지막 기록)."""

    value: Any
    status: str  # CLAIMED | EVIDENCED | DECLARED_UNKNOWN
    source_type: str
    at: datetime | None = None
    turn_id: str | None = None
    source_ref: str | None = None  # 서류 값: "문서id@v버전"
    quote: str | None = None  # 말로 답한 근거 문구


@dataclass
class Step:
    """지금 상태에서 계산한 한 턴."""

    branch: str  # ASK_FACT | REQUEST_EVIDENCE | FINAL_REVIEW | UNSUPPORTED
    next: Next
    facts: dict  # 판정에 넣은 사실(UNASKED·자동 채움 포함)
    question: dict | None = None
    plan_question: dict | None = None
    asked_facts: list[str] = field(default_factory=list)
    requested_documents: list[dict] = field(default_factory=list)  # REQUEST_EVIDENCE일 때
    sub_branch: str | None = None  # CONFIRM_GUESS: 말로 한 답을 버튼으로 확인


def answers_of(states: dict[str, FactState]) -> dict:
    answers: dict = {}
    for path, st in states.items():
        set_path(answers, path, "unknown" if st.status == "DECLARED_UNKNOWN" else st.value)
    return answers


def compute(
    kb: KB, states: dict[str, FactState], expanded: list[str], pending: list[dict] | None = None
) -> Step:
    answers = answers_of(states)
    nxt = next_question(kb.stages, kb.plan, answers)
    facts = with_unasked(kb.plan, answers)
    if nxt.done:
        branch = "UNSUPPORTED" if nxt.result.outcome == "INSUFFICIENT_INFO" else "FINAL_REVIEW"
        return Step(branch, nxt, facts)
    # 말로 한 답 중 확인이 필요한 것(추측·지정 가능성을 지우는 답)을 계획된 질문보다 먼저 확인한다
    for p in pending or []:
        if lookup(facts, p["fact"]) == UNASKED:
            card = confirm_card(kb, p)
            return Step("ASK_FACT", nxt, facts, card, None, [p["fact"]], sub_branch="CONFIRM_GUESS")
    q = nxt.question
    if q.get("kind") == "evidence":
        # 질문 대신 서류를 요청한다. 값은 업로드 → 검수 → 적용으로만 들어온다
        return Step(
            "REQUEST_EVIDENCE",
            nxt,
            facts,
            None,
            q,
            list(nxt.facts),
            requested_documents(kb, nxt.facts),
        )
    question = render_question(kb, q, nxt.facts, states, facts, expanded)
    asked = question["facts"]
    return Step("ASK_FACT", nxt, facts, question, q, asked)


CONFIRM_PREFIX = "confirm:"


def confirm_card(kb: KB, p: dict) -> dict:
    """말로 한 답을 확인하는 카드: [예] [아니요] [모름]. 키는 'confirm:사실'."""
    catalog = kb.plan.catalog
    s = cat.spec(catalog, p["fact"]) or {"label": p["fact"]}
    label = cat.value_label(catalog, p["fact"], p["value"])
    lead = "확인할게요." if p.get("reason") == "risky" else f"'{p.get('quote', '')}'라고 하셨어요."
    opts = [
        {"label": f"예, {label}", "value": p["value"], "kind": "value"},
        {"label": "아니요", "value": None, "kind": "expand"},
        {"label": "모름", "value": None, "kind": "unknown"},
    ]
    return {
        "key": CONFIRM_PREFIX + p["fact"],
        "unit": "fact",
        "facts": [p["fact"]],
        "options": opts,
        "text": f"{lead} {s['label']}: {label}, 맞나요?",
        "help": (
            "말로 답한 값은 판정에 쓰기 전에 한 번 확인해요. "
            "아니면 '아니요'를 눌러 다시 골라 주세요."
        ),
        "input": "choice",
        "value_type": cat.value_type(s) if "type" in s else None,
        "allow_unknown": True,
        "allow_free_number": False,
        "measure_unit": None,
        "items": [],
        "answered_items": [],
        "terms": [],
        "guide": None,
        "plan_id": None,
    }


def requested_documents(kb: KB, paths: list[str]) -> list[dict]:
    """요청할 서류를 서류 종류별로 묶는다: [{evidence_type, label, facts, fact_labels}]."""
    catalog = kb.plan.catalog
    docs: dict[str, dict] = {}
    for p in paths:
        s = cat.spec(catalog, p) or {}
        ev = s.get("evidence") or {"type": "DOCUMENT", "label": "서류"}
        d = docs.setdefault(
            ev["type"],
            {"evidence_type": ev["type"], "label": ev["label"], "facts": [], "fact_labels": []},
        )
        d["facts"].append(p)
        d["fact_labels"].append(s.get("label", p))
    return list(docs.values())


# ---- 질문 카드 -------------------------------------------------------------------------------


def _single(kb: KB, path: str, text: str | None, help_: str | None, facts: dict) -> dict:
    catalog = kb.plan.catalog
    s = cat.spec(catalog, path) or {"type": "enum", "label": path, "values": {}}
    allowed = None
    if path == "input_form":
        material = lookup(facts, "material")
        allowed = (catalog["input_form"].get("allowed_by_material") or {}).get(material)
    opts = cat.options(catalog, path, allowed)
    return {
        "key": path,
        "unit": "fact",
        "facts": [path],
        "options": opts,
        "text": text or s["label"],
        "help": help_,
        "input": cat.input_kind(s),
        "value_type": cat.value_type(s),
        "allow_unknown": any(o["kind"] == "unknown" for o in opts),
        "allow_free_number": s["type"] == "number",
        "measure_unit": s.get("unit"),
        "items": [],
        "answered_items": [],
        "terms": [],
        "guide": None,
    }


PICKED = "pick:"  # case.expanded 안에서 체크 방식으로 고른 항목 표시("pick:사실")


def question_basis(kb: KB, facts: dict, ask: list[str], limit: int = 3) -> list[dict]:
    """이 질문의 답을 기다리는 규칙(아직 참·거짓이 정해지지 않은 규칙)의 근거 조문."""
    want, out, seen = set(ask), [], set()
    for st in kb.stages:
        for rule in st.rules:
            unknowns: set[str] = set()
            if evaluate(rule.when, facts, unknowns) is not TV.UNKNOWN or not unknowns & want:
                continue
            for b in rule.basis:
                unit = b.get("unit") or ""
                if not unit or unit in seen:
                    continue
                seen.add(unit)
                key, _, rest = unit.partition("/")
                ref = f"{kb.law_names.get(key, key)} {rest.replace('/', ' ')}".strip()
                out.append({"id": unit, "type": "LAW", "ref": ref, "excerpt": b.get("quote")})
                if len(out) >= limit:
                    return out
    return out


def with_why(kb: KB, card: dict, q: dict, facts: dict, ask: list[str]) -> dict:
    """질문 아래에 보일 '왜 묻는지'(guide.reason)와 펼쳐 볼 근거 조항(basis)."""
    if q.get("why"):
        card["guide"] = {"background": None, "reason": q["why"], "actions": [], "if_unknown": None}
    card["basis"] = question_basis(kb, facts, ask)
    return card


def apply_variant(q: dict, facts: dict) -> dict:
    """조건이 맞는 첫 variant로 문장·이유·도움말·선택지를 바꾼 질문(판정 사실은 그대로)."""
    for v in q.get("variants") or []:
        if evaluate(v["when"], facts, set()) is TV.TRUE:
            return {**q, **{k: v[k] for k in v if k != "when"}}
    return q


def render_question(
    kb: KB,
    q: dict,
    ask: list[str],
    states: dict[str, FactState],
    facts: dict,
    expanded: list[str],
) -> dict:
    q = apply_variant(q, facts)
    return with_why(kb, _render_question(kb, q, ask, states, facts, expanded), q, facts, ask)


def _render_question(
    kb: KB,
    q: dict,
    ask: list[str],
    states: dict[str, FactState],
    facts: dict,
    expanded: list[str],
) -> dict:
    catalog = kb.plan.catalog
    if q.get("kind") != "group":
        out = _single(kb, ask[0], q.get("text"), q.get("help"), facts)
        if q.get("allowed"):
            keep = {str(cat.norm(v)) for v in q["allowed"]}
            out["options"] = [
                o for o in out["options"] if o["kind"] != "value" or str(o["value"]) in keep
            ]
        labels = {str(cat.norm(k)): v for k, v in (q.get("option_labels") or {}).items()}
        for o in out["options"]:
            if o["kind"] == "value" and str(o["value"]) in labels:
                o["label"] = labels[str(o["value"])]
        out["plan_id"] = q["id"]
        return out
    items = {i["fact"]: i for i in q["items"]}
    answered = [
        {
            "key": f,
            "label": items[f]["label"],
            "value_label": cat.value_label(catalog, f, lookup(facts, f)),
        }
        for f in items
        if f in states
    ]
    if q["id"] in expanded and "all_yes_label" not in q:
        # 펼친 묶음: 남은 항목을 하나씩 단일 질문으로 묻는다
        item = items[ask[0]]
        picked = PICKED + ask[0] in expanded
        text = (item.get("ask_picked") if picked else None) or item.get("ask") or item["label"]
        out = _single(kb, ask[0], text, q.get("help"), facts)
        if picked:
            # 체크 방식으로 '해당한다'고 고른 항목: 세부 값만 묻는다('해당 없음' 값은 빼고)
            none = str(cat.norm(item.get("none")))
            out["options"] = [
                o for o in out["options"] if o["kind"] != "value" or str(o["value"]) != none
            ]
        out.update(plan_id=q["id"], group=q["id"], answered_items=answered)
        return out
    if "all_yes_label" in q:
        none_value = {f: "yes" for f in ask}
        opts = [
            {"label": q["all_yes_label"], "value": none_value, "kind": "none_all"},
            {"label": q.get("not_all_label", EXPAND_LABEL), "value": None, "kind": "expand"},
        ]
    else:
        none_value = {f: str(items[f]["none"]) for f in ask}
        opts = [
            {"label": NONE_ALL_LABEL, "value": none_value, "kind": "none_all"},
            {"label": EXPAND_LABEL, "value": None, "kind": "expand"},
        ]
    return {
        "key": q["id"],
        "plan_id": q["id"],
        "unit": "group",
        "facts": list(ask),
        "options": opts,
        "text": q.get("text") or "",
        "help": q.get("help"),
        "input": "group",
        "value_type": None,
        "allow_unknown": False,
        "allow_free_number": False,
        "measure_unit": None,
        "items": [{"key": f, "label": items[f]["label"]} for f in ask],
        "answered_items": answered,
        # 체크 방식: 해당하는 항목만 골라 kind=some으로 보낸다(고르지 않은 항목은 해당 없음)
        "allow_pick": "all_yes_label" not in q and len(ask) > 1,
        "terms": [],
        "guide": None,
    }


def group_none_values(kb: KB, q: dict, ask: list[str]) -> dict[str, str]:
    if "all_yes_label" in q:
        return {f: "yes" for f in ask}
    items = {i["fact"]: i for i in q["items"]}
    return {f: str(items[f]["none"]) for f in ask}


# ---- 판정 결과 -------------------------------------------------------------------------------


def deciding_rule(result: Result) -> str | None:
    for t in reversed(result.trace):
        if t.get("rule") and t["rule"] != "on_no_match" and "blocked" not in t:
            return t["rule"]
    return None


def basis(kb: KB, result: Result) -> list[dict]:
    """판정 경로에서 참이 된 규칙의 근거 조문(중복 제거)."""
    rules = {r.id: r for s in kb.stages for r in s.rules}
    out, seen = [], set()
    for t in result.trace:
        rule = rules.get(t.get("rule") or "")
        if rule is None or "blocked" in t:
            continue
        for b in rule.basis:
            unit = b.get("unit") or ""
            if not unit or unit in seen:
                continue
            seen.add(unit)
            key, _, rest = unit.partition("/")
            ref = f"{kb.law_names.get(key, key)} {rest.replace('/', ' ')}".strip()
            out.append(
                {
                    "id": f"B{len(out) + 1}",
                    "type": "LAW",
                    "unit": unit,
                    "ref": ref,
                    "excerpt": b.get("quote"),
                    "rule_id": rule.id,
                }
            )
    return out


def outcome_info(kb: KB, result: Result) -> dict:
    return kb.outcomes["outcomes"].get(result.outcome, {})


def public_code(result: Result) -> str | None:
    """사용자·인계에 내보내는 분류번호. 범위 밖 후보 코드는 내보내지 않는다(D15)."""
    return result.code if result.outcome == "GENERAL" else None


def assumptions(kb: KB, result: Result, states: dict | None = None) -> list[str]:
    """결과에 붙일 안내: 플래그 문장 + 묻지 않고 둔 기본값(가정) 문장."""
    texts = kb.outcomes.get("flags") or {}
    out = [texts.get(f, f) for f in result.flags]
    for a in kb.plan.assume:
        if states is not None and not any(k in states for k in a["set"]) and a.get("note"):
            out.append(a["note"])
    return out


def result_card(kb: KB, result: Result, states: dict | None = None) -> dict:
    info = outcome_info(kb, result)
    code = public_code(result)
    name = kb.outcomes["codes"].get(code) if code else None
    rule = deciding_rule(result)
    reason = (kb.outcomes.get("rule_reasons") or {}).get(rule or "") or info.get("reason")
    conclusion = (info.get("conclusion") or "").format(code=code or "", name=name or "")
    return {
        "result_type": info.get("result_type", "NO_CODE"),
        "code": code,
        "name": name,
        "category": info.get("category"),
        "outcome": None if code else result.outcome,
        "conclusion": conclusion,
        "next_step": info.get("next_step"),
        "review": "UNVERIFIED",
        "assumptions": assumptions(kb, result, states),
        "reason": None if code else reason,
        "designated": None,
    }


def verdict_view(kb: KB, step: Step) -> dict:
    r = step.next.result
    final = step.branch == "FINAL_REVIEW"
    code = public_code(r) if final else None
    info = outcome_info(kb, r) if final else {}
    return {
        "outcome": r.outcome if final else None,
        "waste_code": code,
        "waste_name": kb.outcomes["codes"].get(code) if code else None,
        "category": info.get("category"),
        "flags": list(r.flags) if final else [],
        "blocking_facts": list(r.blocking_facts),
        "rule_id": deciding_rule(r) if final else None,
        "rationale": basis(kb, r) if final else [],
        "candidates": [],
        "conditions": [],
        "review": "UNVERIFIED",
    }


# ---- 판정 보드 -------------------------------------------------------------------------------


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(KST).isoformat(timespec="seconds")


def assumed_keys(kb: KB) -> set[str]:
    return {k for a in kb.plan.assume for k in a["set"]}


def irrelevant(kb: KB, facts: dict) -> set[str]:
    """질문 조건(ask_if)이 거짓이 되어 더는 해당 없는 사실(예: 형태를 캔에서 바꾼 뒤 캔 내용물)."""
    out: set[str] = set()
    for q in kb.plan.questions:
        if q.get("ask_if") and evaluate(q["ask_if"], facts, set()) is TV.FALSE:
            out |= set(question_facts(q))
    return out


def edit_options(kb: KB, path: str, facts: dict) -> list[dict]:
    allowed = None
    if path == "input_form":  # 형태는 재질에 맞는 것만 고를 수 있다
        material = lookup(facts, "material")
        allowed = (kb.plan.catalog["input_form"].get("allowed_by_material") or {}).get(material)
    # 고치기 하나로 '모름'까지 고를 수 있게 모름 선택지(kind=unknown)도 준다(2026-11-21)
    return [
        {"label": o["label"], "value": o["value"], "kind": o["kind"]}
        for o in cat.options(kb.plan.catalog, path, allowed)
    ]


def known_facts(kb: KB, states: dict[str, FactState], facts: dict) -> list[dict]:
    """값이 정해진 사실: 답한 것 + 자동으로 채운 것 + 기본값(가정). 카탈로그 순서.

    더는 해당 없는 답(질문 조건이 거짓이 된 사실)은 보이지 않는다.
    """
    catalog = kb.plan.catalog
    hidden, assumed = irrelevant(kb, facts), assumed_keys(kb)
    out = []
    for path in cat.all_paths(catalog):
        v = lookup(facts, path)
        st = states.get(path)
        if st is None and (v is None or v == UNASKED):
            continue
        if path in hidden:
            continue
        s = cat.spec(catalog, path) or {}
        status = st.status if st else "DERIVED"
        source = st.source_type if st else ("ASSUMED" if path in assumed else "DERIVED")
        out.append(
            {
                "key": path,
                "label": s.get("label", path),
                "value": "unknown" if status == "DECLARED_UNKNOWN" else v,
                "value_label": cat.value_label(catalog, path, v),
                "status": status,
                "source_type": source,
                "source_label": SOURCE_LABELS.get(source, source),
                "quote": st.quote if st else None,
                "recorded_at": iso(st.at) if st else None,
                # 서류로만 받는 값은 버튼으로 고칠 수 없다(서류 검수로만 바뀜)
                "editable": source not in ("DERIVED", "DOCUMENT")
                and not cat.is_document_fact(catalog, path),
                "edit": {
                    "input": cat.input_kind(s) if s else "choice",
                    "value_type": cat.value_type(s) if s else None,
                    "unit": s.get("unit"),
                    "options": edit_options(kb, path, facts),
                },
            }
        )
    return out


def board(kb: KB, step: Step, states: dict[str, FactState], questions_asked: int, max_q: int):
    catalog = kb.plan.catalog
    if step.branch in ("ASK_FACT", "REQUEST_EVIDENCE"):
        reason = "MISSING" if step.branch == "ASK_FACT" else "NEEDS_EVIDENCE"
        pending = [
            {"key": f, "label": (cat.spec(catalog, f) or {}).get("label", f), "reason": reason}
            for f in step.asked_facts
        ]
    else:
        pending = [
            {
                "key": f,
                "label": (cat.spec(catalog, f) or {}).get("label", f),
                "reason": "DECLARED_UNKNOWN",
            }
            for f in step.next.result.blocking_facts
        ]
        if step.branch == "FINAL_REVIEW":
            pending = []
    return {
        "facts": known_facts(kb, states, step.facts),
        "pending": pending,
        "progress": {"questions_asked": questions_asked, "max_questions": max_q},
        "candidates_count": 0,
        "top_candidates": [],
        "documents_needed": step.requested_documents,
    }


def message(kb: KB, step: Step) -> str:
    if step.branch == "ASK_FACT":
        return step.question["text"]
    if step.branch == "REQUEST_EVIDENCE":
        return step.plan_question.get("text") or "확인할 서류를 올려 주세요."
    if step.branch == "FINAL_REVIEW":
        card = result_card(kb, step.next.result)
        return " ".join(x for x in (card["conclusion"], card["next_step"]) if x)
    catalog = kb.plan.catalog
    labels = [(cat.spec(catalog, f) or {}).get("label", f) for f in step.next.result.blocking_facts]
    shown = ", ".join(labels[:3]) + (f" 외 {len(labels) - 3}개" if len(labels) > 3 else "")
    return kb.outcomes["unsupported"]["message"].format(facts=shown)


# ---- 인계 객체 -------------------------------------------------------------------------------


def handoff(
    kb: KB,
    *,
    case_id: str,
    version: int,
    result: Result,
    states: dict[str, FactState],
    facts: dict,
    started_at: datetime,
    confirmed_at: datetime,
    as_of: str,
    profile_version: str | None,
) -> dict:
    info = outcome_info(kb, result)
    code = public_code(result)
    notes = assumptions(kb, result, states)
    known = {
        f["key"]: {
            "value": f["value"],
            "status": f["status"],
            "source_type": f["source_type"],
        }
        for f in known_facts(kb, states, facts)
        if f["status"] != "DECLARED_UNKNOWN"
    }
    confirmed_keys = sorted(p for p, s in states.items() if s.source_type == "PROFILE_CONFIRMED")
    rule = deciding_rule(result)
    reason = (kb.outcomes.get("rule_reasons") or {}).get(rule or "") or info.get("reason")
    summary = info.get("summary") or ""
    if not code and reason:
        summary = f"{reason} {summary}".strip()
    return {
        "contract": "diagnosis-handoff-v1",
        "case_id": case_id,
        "verdict_version": version,
        "result_type": info.get("result_type", "NO_CODE"),
        "waste_code": code,
        "waste_name": kb.outcomes["codes"].get(code) if code else None,
        "category": info.get("category"),
        "outcome": None if code else result.outcome,
        "route_guidance": {"action": info.get("action"), "summary": summary, "notes": notes},
        "facts": known,
        "evidence": [
            {"fact": p, "document_id": (s.source_ref or "").split("@")[0]}
            for p, s in states.items()
            if s.source_type == "DOCUMENT" and s.status == "EVIDENCED"
        ],
        "basis": basis(kb, result),
        "review": "UNVERIFIED",
        "timestamps": {
            "diagnosis_started_at": iso(started_at),
            "confirmed_at": iso(confirmed_at),
            "as_of": as_of,
        },
        "kb": {"kb_version": kb.version, "table_id": None, "table_version": None},
        "inputs": {
            "company_profile_version": profile_version,
            "confirmed_profile_keys": confirmed_keys,
        },
        "assumptions": notes,
        "flags": list(result.flags),
        "rule_id": rule,
        "designated": None,
        "recycling": recycling(
            kb,
            case_id=case_id,
            version=version,
            code=code,
            as_of=as_of,
            route=info.get("action") == "RECOMMEND_ROUTE",
        ),
    }


def recycling(
    kb: KB, *, case_id: str, version: int, code: str | None, as_of: str, route: bool
) -> dict:
    """재활용 가능 유형(recycling-types-v1). 별표 4의3 조회일 뿐 분류 판정이나 시설 허가가 아니다.

    status: table_listed(표에 있음) | not_applicable(일반 경로 대상 아님)
            | not_covered(표 자료 없음) | out_of_date(법 기준일이 별표 시행일보다 앞섬)
    """
    table = kb.recycling
    base = {
        "contract": "recycling-types-v1",
        "case_id": case_id,
        "verdict_version": version,
        "waste_code": code,
        "as_of": as_of,
        "facility_permit_verified": False,
    }
    if not code or not route:
        return {**base, "status": "not_applicable"}
    row = table.rows.get(code) if table else None
    if row is None:
        return {**base, "status": "not_covered"}
    source = {**table.source, "unit": row["unit"]}
    if as_of < table.source["law_effective_from"]:
        return {**base, "status": "out_of_date", "source": source}
    checksum = hashlib.sha256(
        json.dumps([row["text"], table.notes], ensure_ascii=False).encode()
    ).hexdigest()
    return {
        **base,
        "status": "table_listed",
        "types": row["types"],
        "source": source,
        "pages": [],  # 법령 API 본문에서 읽어 쪽 번호가 없다
        "notes": table.notes[:10],
        "version": table.version,
        "checksum": checksum,
    }


def today_kst() -> str:
    return datetime.now(KST).date().isoformat()
