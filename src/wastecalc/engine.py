"""판정 엔진.

- 사실 값: 확정값 / UNKNOWN(모름) / CONFLICT(자료끼리 다름)
- 규칙 평가: 3값 논리(TRUE / FALSE / UNDET)
- 결론 확정: 그 결론에 이르는 규칙 행이 실제로 성립(TRUE)할 때만. "남은 후보가 하나"라는 이유로는 확정하지 않는다.
- 모르면: 무엇을 확인하면 갈리는지(조문·조건·확인 방법)를 조립해 돌려준다.
LLM은 여기에 관여하지 않는다. 같은 입력이면 같은 출력.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .annex4 import evaluate_s4
from .recycling import evaluate_s5
from .kb import COST_RANK, KB, Condition, Rule, load_kb

UNKNOWN = "UNKNOWN"
TRUE, FALSE, UNDET = "TRUE", "FALSE", "UNDET"
SOURCES_ALLOWED = {"USER", "DOCUMENT", "TEST"}


class InputError(ValueError):
    """정해진 값 밖의 입력. 엔진은 추측하지 않고 거부한다."""


@dataclass(frozen=True)
class Answer:
    kind: str  # VALUE / UNKNOWN / CONFLICT
    values: tuple  # VALUE: (v,), CONFLICT: (v1, v2, ...)
    source: str = "USER"

    def to_json(self) -> Any:
        if self.kind == "UNKNOWN":
            return UNKNOWN
        if self.kind == "CONFLICT":
            return {"conflict": list(self.values), "source": self.source}
        return {"value": self.values[0], "source": self.source}


# ---------------------------------------------------------------- 입력 검증

def _check_value(kb: KB, fid: str, v: Any) -> Any:
    f = kb.facts[fid]
    t = f["type"]
    if t == "bool":
        if not isinstance(v, bool):
            raise InputError(f"{fid}: 참/거짓(true/false) 또는 \"UNKNOWN\"만 받습니다. 받은 값: {v!r}")
        return v
    if t == "number":
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
            raise InputError(f"{fid}: 0 이상의 숫자({f.get('unit', '')}) 또는 \"UNKNOWN\"만 받습니다. 받은 값: {v!r}")
        return v
    if t == "enum":
        if f.get("values_from") and not f["values"]:
            # 기준일에 분류표가 없어 검사할 수 없음 — 그 단계는 NO_RULES_FOR_DATE로 멈추므로 값을 쓰지 않는다
            return v
        if v not in f["values"]:
            allowed = ", ".join(f["values"])
            raise InputError(f"{fid}: 허용 값은 {allowed} 또는 \"UNKNOWN\"입니다. 받은 값: {v!r}")
        return v
    raise InputError(f"{fid}: 알 수 없는 사실 형식")


def parse_answer(kb: KB, fid: str, raw: Any) -> Answer:
    if fid not in kb.facts:
        raise InputError(f"알 수 없는 사실 id: {fid!r}. list_facts로 허용 목록을 확인하세요.")
    if kb.facts[fid].get("derived_from"):
        raise InputError(f"{fid}: 계산기가 {kb.facts[fid]['derived_from']} 판정으로 정하는 값이라 입력할 수 없습니다.")
    source = "USER"
    if isinstance(raw, dict):
        source = raw.get("source", "USER")
        if source not in SOURCES_ALLOWED:
            raise InputError(f"{fid}: source는 USER / DOCUMENT / TEST 중 하나여야 합니다.")
        if "conflict" in raw:
            vals = raw["conflict"]
            if not isinstance(vals, list) or len(vals) < 2:
                raise InputError(f"{fid}: conflict에는 서로 다른 값 두 개 이상을 목록으로 주세요.")
            checked = tuple(_check_value(kb, fid, v) for v in vals)
            if len(set(checked)) == 1:
                return Answer("VALUE", (checked[0],), source)
            return Answer("CONFLICT", checked, source)
        if "value" not in raw:
            raise InputError(f"{fid}: value 또는 conflict가 필요합니다.")
        raw = raw["value"]
    if raw == UNKNOWN:
        return Answer("UNKNOWN", (), source)
    return Answer("VALUE", (_check_value(kb, fid, raw),), source)


def parse_answers(kb: KB, raw: dict | None) -> dict[str, Answer]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise InputError("answers는 {사실 id: 값} 형태여야 합니다.")
    return {fid: parse_answer(kb, fid, v) for fid, v in raw.items()}


# ---------------------------------------------------------------- 3값 평가

def _test(op: str, actual: Any, expected: Any) -> bool:
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "in":
        return actual in expected
    if op == "not_in":
        return actual not in expected
    if op == "gte":
        return actual >= expected
    if op == "gt":
        return actual > expected
    if op == "lte":
        return actual <= expected
    if op == "lt":
        return actual < expected
    raise ValueError(op)


def eval_condition(c: Condition, answers: dict[str, Answer]) -> str:
    a = answers.get(c.fact)
    if a is None or a.kind == "UNKNOWN":
        return UNDET
    results = {_test(c.op, v, c.value) for v in a.values}
    if len(results) == 1:
        return TRUE if results.pop() else FALSE
    return UNDET  # CONFLICT이고 값에 따라 결과가 갈림


@dataclass
class RuleEval:
    rule: Rule
    status: str
    open_conditions: list[Condition]  # 아직 참/거짓이 정해지지 않은 조건(규칙 순서대로)


def eval_rule(rule: Rule, answers: dict[str, Answer]) -> RuleEval:
    results = [(c, eval_condition(c, answers)) for c in rule.when]
    if any(s == FALSE for _, s in results):
        return RuleEval(rule, FALSE, [])
    open_c = [c for c, s in results if s == UNDET]
    return RuleEval(rule, UNDET if open_c else TRUE, open_c)


def eval_stage(kb: KB, stage_id: str, answers: dict[str, Answer]) -> dict:
    stage = kb.stages[stage_id]
    rules = kb.rules_for(stage_id)
    evals: dict[str, RuleEval] = {}
    for r in rules:
        if not r.complement_of:
            evals[r.id] = eval_rule(r, answers)
    for r in rules:
        if r.complement_of:
            base = [e for e in evals.values() if e.rule.concludes in r.complement_of]
            if any(e.status == TRUE for e in base):
                evals[r.id] = RuleEval(r, FALSE, [])
            elif all(e.status == FALSE for e in base):
                evals[r.id] = RuleEval(r, TRUE, [])
            else:
                opens = [c for e in base if e.status == UNDET for c in e.open_conditions[:1]]
                evals[r.id] = RuleEval(r, UNDET, opens)

    cand_status: dict[str, str] = {}
    for cid in stage["candidates"]:
        cev = [e for e in evals.values() if e.rule.concludes == cid]
        if any(e.status == TRUE for e in cev):
            cand_status[cid] = TRUE
        elif cev and all(e.status == FALSE for e in cev):
            cand_status[cid] = FALSE
        elif not cev:
            cand_status[cid] = FALSE
        else:
            cand_status[cid] = UNDET
    # 다른 결론이 성립하면 무시되는 결론(예: 지정폐기물이 확정되면 '해석 필요'는 의미 없음)
    for cid, cand in stage["candidates"].items():
        if cand_status.get(cid) == TRUE:
            for o in cand.get("overrides", []):
                if cand_status.get(o) == TRUE:
                    cand_status[o] = FALSE
    return {"stage": stage_id, "evals": evals, "candidates": cand_status}


def with_derived(kb: KB, stage_id: str, answers: dict[str, Answer]) -> dict[str, Answer]:
    """다른 단계의 판정 결과로 정해지는 사실(derived_from)을 채운다. 정해지지 않으면 비워 둔다."""
    out = dict(answers)
    for r in kb.rules_for(stage_id):
        for c in r.when:
            f = kb.facts[c.fact]
            src = f.get("derived_from")
            if not src or c.fact in out:
                continue
            st = eval_stage(kb, src, answers)
            # 해석 자료(해설·질의회신)만으로 나온 지정 판정은 다른 단계의 근거로 쓰지 않는다
            law_designated = any(e.status == TRUE and e.rule.concludes == "DESIGNATED"
                                 and kb.sources[e.rule.source]["evidence"] == "LAW" for e in st["evals"].values())
            if st["candidates"].get("DESIGNATED") == TRUE and law_designated:
                out[c.fact] = Answer("VALUE", (True,), "DERIVED")
            elif st["candidates"].get("NOT_DESIGNATED") == TRUE:
                out[c.fact] = Answer("VALUE", (False,), "DERIVED")
    return out


# ---------------------------------------------------------------- 출력 조립

def _basis(kb: KB, rule: Rule) -> dict:
    src = kb.sources[rule.source]
    b = {
        "source_id": rule.source,
        "title": src["title"],
        "location": rule.location,
        "quote": rule.quote,
        "evidence": src["evidence"],
        "law_version": src.get("version"),
        "effective_on": src.get("effective_on"),
        "rule_id": rule.id,
        "review": rule.review,
    }
    if rule.item:
        b["item"] = rule.item
    if rule.gaps:
        b["gaps"] = rule.gaps
    if rule.supporting:
        b["supporting"] = [
            {**s, "title": kb.sources[s["source"]]["title"], "evidence": kb.sources[s["source"]]["evidence"]}
            for s in rule.supporting
        ]
    return b


OP_TEXT = {"eq": "=", "ne": "≠", "gte": "이상", "gt": "초과", "lte": "이하", "lt": "미만", "in": "중 하나", "not_in": "이외"}


def _cond_text(kb: KB, c: Condition) -> str:
    f = kb.facts[c.fact]
    if f["type"] == "bool":
        return f"{f['question']} → {'예' if c.value else '아니오'}"
    if f["type"] == "enum":
        if c.op in {"in", "not_in"}:
            labels = ", ".join(f["values"][v] for v in c.value)
            return f"{f['question']} → {labels} {OP_TEXT[c.op]}"
        label = f["values"][c.value]
        return f"{f['question']} → {label}" if c.op == "eq" else f"{f['question']} → {label} 아님"
    return f"{f['question']} → {c.value}{f.get('unit', '')} {OP_TEXT[c.op]}"


def _cond_short(kb: KB, c: Condition) -> str:
    """질문을 빼고 답 부분만: '예', '300kg/일 이상', '건설공사'."""
    full = _cond_text(kb, c)
    return full.split(" → ", 1)[1]


def value_text(kb: KB, fid: str, a: "Answer | None") -> str:
    """입력값을 사람이 읽는 말로: 예/아니오, 선택지 이름, 숫자+단위, 모름."""
    if a is None:
        return "답하지 않음"
    if a.kind == "UNKNOWN":
        return "모름"
    f = kb.facts[fid]

    def one(v):
        if f["type"] == "bool":
            return "예" if v else "아니오"
        if f["type"] == "enum":
            return f["values"].get(v, str(v))
        return f"{v:g}{f.get('unit', '')}" if isinstance(v, (int, float)) else str(v)

    if a.kind == "CONFLICT":
        return " / ".join(one(v) for v in a.values) + " (자료끼리 다름)"
    text = one(a.values[0])
    if a.source == "DERIVED":
        text += " (앞 판정 결과)"
    return text


def _because_true(kb: KB, rule: Rule, answers: dict) -> list[str]:
    """성립한 규칙: 조건마다 '입력값 → 기준 충족'."""
    out = []
    for c in rule.when:
        label = kb.facts[c.fact].get("label", c.fact)
        out.append(f"{label}: {value_text(kb, c.fact, answers.get(c.fact))} → 기준 '{_cond_short(kb, c)}' 충족")
    return out


def _because_complement(kb: KB, st: dict, rule: Rule, answers: dict) -> list[str]:
    """'나머지 모두 아님' 결론: 각 경로가 어떤 입력 때문에 해당하지 않았는지. 종류가 달라 애초에 무관한 경로는 뺀다."""
    out, seen = [], set()
    for e in st["evals"].values():
        if e.rule.concludes not in (rule.complement_of or []) or e.status != FALSE:
            continue
        first_false = next((c for c in e.rule.when if eval_condition(c, answers) == FALSE), None)
        if first_false is None or first_false.fact == "waste_kind":
            continue
        key = (first_false.fact, first_false.op, str(first_false.value))
        if key in seen:
            continue
        seen.add(key)
        label = kb.facts[first_false.fact].get("label", first_false.fact)
        path = (e.rule.plain or e.rule.location).split(". ")[0].rstrip(".")
        out.append(f"{label}: {value_text(kb, first_false.fact, answers.get(first_false.fact))} → 해당 없음 "
                   f"(이 경로는 '{_cond_short(kb, first_false)}'일 때만 해당: {path})")
    return out


def _how_to_check(kb: KB, fid: str) -> list[dict]:
    out = []
    for h in kb.facts[fid].get("how_to_check", []):
        item = {"text": h["text"]}
        if "source" in h:
            item["basis"] = {"title": kb.sources[h["source"]]["title"], "quote": h["quote"],
                             "evidence": kb.sources[h["source"]]["evidence"]}
        else:
            item["basis"] = None  # 실무 안내 — 근거 조문 없음
        out.append(item)
    return out


def _fact_card(kb: KB, fid: str, answers: dict[str, Answer]) -> dict:
    f = kb.facts[fid]
    a = answers.get(fid)
    card = {
        "fact": fid,
        "question": f["question"],
        "type": f["type"],
        "cost": f["cost"],
        "state": "MISSING" if a is None else a.kind,
        "how_to_check": _how_to_check(kb, fid),
    }
    if f["type"] == "enum":
        card["allowed_values"] = f["values"]
    if f.get("unit"):
        card["unit"] = f["unit"]
    if a is not None and a.kind == "CONFLICT":
        card["conflicting_values"] = list(a.values)
    if f.get("test"):
        card["test"] = f["test"]
    if f.get("derived_from"):
        card["derived_from"] = f["derived_from"]
    if f.get("note"):
        n = f["note"]
        card["note"] = {"text": n["text"]}
        if n.get("source"):
            card["note"]["basis"] = {"title": kb.sources[n["source"]]["title"], "quote": n["quote"]}
    return card


def _resolution(kb: KB, stage_id: str, st: dict, answers: dict[str, Answer]) -> list[dict]:
    """아직 판정되지 않은 규칙들에서 '무엇을 확인하면 갈리는지'를 사실별로 묶는다."""
    stage = kb.stages[stage_id]
    order = stage.get("question_order", [])
    fact_order = list(kb.facts)
    cards: dict[str, dict] = {}
    for e in st["evals"].values():
        if e.status != UNDET or e.rule.complement_of:
            continue
        c = e.open_conditions[0]  # 규칙에 적힌 순서대로 하나씩 묻는다
        card = cards.setdefault(c.fact, {**_fact_card(kb, c.fact, answers), "decides": []})
        others = [_cond_text(kb, oc) for oc in e.open_conditions[1:]]
        card["decides"].append({
            "if": _cond_short(kb, c),
            "then": stage["candidates"][e.rule.concludes]["label"] if not others else "다음 조건도 확인",
            "also_needs": others,
            "plain": e.rule.plain,
            "basis": _basis(kb, e.rule),
        })
        if kb.facts[c.fact]["type"] == "number" and c.op in OP_TEXT:
            card.setdefault("thresholds", []).append(
                {"value": c.value, "comparator": OP_TEXT[c.op], "unit": kb.facts[c.fact].get("unit")})

    def key(fid: str):
        card = cards[fid]
        decisive = any(not d["also_needs"] for d in card["decides"])
        return (
            {"MISSING": 0, "UNKNOWN": 1, "CONFLICT": 2}.get(card["state"], 3),
            order.index(fid) if fid in order else len(order),
            COST_RANK[card["cost"]],
            0 if decisive else 1,
            fact_order.index(fid),
        )

    return [cards[f] for f in sorted(cards, key=key)]


def _complement_note(kb: KB, stage_id: str) -> list[dict]:
    notes = []
    for r in kb.rules_for(stage_id):
        if r.complement_of:
            cands = kb.stages[stage_id]["candidates"]
            targets = "', '".join(cands[t]["label"] for t in r.complement_of)
            notes.append({
                "conclusion": cands[r.concludes]["label"],
                "when": f"'{targets}'에 이르는 조건이 모두 '아니오'로 확인될 때",
                "gaps": r.gaps,
                "basis": _basis(kb, r),
            })
    return notes


def _consult(kb: KB, stage_id: str, answers: dict, decided: list[dict], issue: str, reference: list[dict]) -> dict:
    """법 조문만으로 정할 수 없을 때: 결론 대신 문의처와 질의서 초안을 만든다."""
    conf = kb.consult or {}
    t = conf.get("targets", {})
    s3 = next((d for d in decided if d["stage"] == "S3"), None)
    em = answers.get("emission_facility")
    emission = em.values[0] if em is not None and em.kind == "VALUE" else None
    keys: list[str] = []
    if stage_id == "S0":
        keys = ["regional_circular"]
    elif stage_id == "S2":
        keys = ["local_general"]
    elif stage_id in {"S3", "S4", "S5"}:
        designated_side = stage_id == "S3" or (s3 is not None and s3["conclusion"] == "DESIGNATED")
        if designated_side:
            keys = ["regional_designated"] if emission is True else (
                ["province_designated"] if emission is False else ["regional_designated", "province_designated"])
        else:
            keys = ["local_general"]
    keys.append("epeople")
    where = []
    for k in keys:
        if k not in t:
            continue
        tt = t[k]
        w = {"name": tt["name"], "when": tt.get("when")}
        if tt.get("source"):
            w["basis"] = {"title": kb.sources[tt["source"]]["title"], "location": tt.get("location"), "quote": tt["quote"]}
        where.append(w)
    facts = [f"- {kb.facts[f].get('label', f)}: {value_text(kb, f, a)}"
             for f, a in answers.items() if a.kind != "UNKNOWN" and not kb.facts[f].get("derived_from")]
    refs = [f"- {b['title']} {b['location']}: “{b['quote']}”" for b in reference]
    draft = "\n".join(
        [conf.get("questions", {}).get(stage_id, "다음 사항을 문의드립니다."), "",
         "1. 사실관계"] + (facts or ["- (입력한 사실 없음)"]) +
        ["", "2. 쟁점", f"- {issue}", "", "3. 참고한 근거"] + (refs or ["- 없음"]) +
        ["", "4. 문의 사항", "- 위 사실관계에서 이 폐기물을 어떻게 보아야 하는지, 필요한 시험·서류가 있는지 회신 부탁드립니다."])
    return {"why": issue, "where": where, "draft": draft}


def evaluate(answers_raw: dict | None, strict: bool = True, kb: KB | None = None, as_of=None,
             allow_interpretive: bool = False) -> dict:
    """사실을 받아 단계별로 판정한다.

    strict=True: 사람이 검토(REVIEWED)하지 않은 규칙으로 나온 결론은 확정(DETERMINED)으로 내지 않고 잠정으로 낸다.
    법령이 아닌 해석 자료(해설·질의회신)만으로 나오는 결론은 기본적으로 내지 않고, 그 단계에서 멈춰
    문의처·질의서 초안(consult)을 돌려준다. allow_interpretive=True는 평가 도구가 참고 결론을 보려 할 때만 쓴다.
    """
    try:
        kb = (kb or load_kb()).at(as_of if as_of is not None else (kb.as_of if kb else None))
    except ValueError as e:
        raise InputError(str(e)) from e
    answers = parse_answers(kb, answers_raw)
    decided: list[dict] = []
    stage_id = "S0"
    result: dict[str, Any] = {}

    while True:
        stage = kb.stages[stage_id]
        if stage_id in kb.unavailable:
            result = {"status": "OUT_OF_SCOPE", "stage": stage_id, "stage_title": stage["title"],
                      "reason": "NO_RULES_FOR_DATE",
                      "message": f"기준일 {kb.as_of}에 적용할 규칙이 계산기에 없습니다({kb.unavailable[stage_id]}). "
                                 "다른 날짜의 법령으로 추측하지 않습니다."}
            break
        if stage.get("not_implemented"):
            result = {"status": "DETERMINED", "pending_stages": [{"stage": stage_id, "title": stage["title"],
                                                                 "note": "이 단계는 아직 계산기에 없습니다."}]}
            break
        if stage.get("handler") in {"annex4", "annex43"}:
            out = (evaluate_s4 if stage["handler"] == "annex4" else evaluate_s5)(kb, answers, decided)
            if "decided" in out:
                decided.append(out["decided"])
                if stage.get("terminal"):
                    result = {"status": "DETERMINED"}
                    break
                stage_id = stage["next"]
                continue
            result = out["result"]
            break
        stage_answers = with_derived(kb, stage_id, answers)
        st = eval_stage(kb, stage_id, stage_answers)
        trues = [c for c, s in st["candidates"].items() if s == TRUE]
        if len(trues) > 1:
            fired = [_basis(kb, e.rule) for e in st["evals"].values() if e.status == TRUE]
            result = {"status": "NEED_EXPERT", "stage": stage_id, "stage_title": stage["title"],
                      "reason": "RULE_OVERLAP",
                      "message": "입력한 사실로 서로 다른 결론이 동시에 성립합니다. 규칙 겹침이므로 전문가 확인이 필요합니다.",
                      "conflicting_conclusions": [stage["candidates"][c]["label"] for c in trues],
                      "fired_rules": fired,
                      "consult": _consult(kb, stage_id, stage_answers, decided,
                                          "입력한 사실로 서로 다른 결론이 동시에 성립함: "
                                          + ", ".join(stage["candidates"][c]["label"] for c in trues), fired)}
            break
        if len(trues) == 1:
            cid = trues[0]
            fired = [e.rule for e in st["evals"].values() if e.status == TRUE and e.rule.concludes == cid]
            used = sorted({c.fact for r in fired for c in r.when}) or sorted(
                {c.fact for e in st["evals"].values() if e.rule.concludes != cid for c in e.rule.when
                 if c.fact in stage_answers and stage_answers[c.fact].kind != "UNKNOWN"})
            items = list(dict.fromkeys(r.item for r in fired if r.item))
            gaps = list(dict.fromkeys(g for r in fired for g in r.gaps))
            because: list[str] = []
            for r in fired:
                because += (_because_complement(kb, st, r, stage_answers) if r.complement_of
                            else _because_true(kb, r, stage_answers))
            entry = {
                "stage": stage_id,
                "stage_title": stage["title"],
                "conclusion": cid,
                "label": stage["candidates"][cid]["label"],
                "basis": [_basis(kb, r) for r in fired],
                "items": items,
                "facts_used": {f: stage_answers[f].to_json() for f in used if f in stage_answers},
                "reviewed": all(r.review == "REVIEWED" for r in fired),
                "law_based": any(kb.sources[r.source]["evidence"] == "LAW" for r in fired),
                "gaps": gaps,
                "explanation": {"plain": list(dict.fromkeys(r.plain for r in fired if r.plain)),
                                "because": list(dict.fromkeys(because))},
            }
            cand = stage["candidates"][cid]
            if not entry["law_based"] and not allow_interpretive:
                # 해석 자료(해설·질의회신)만으로 나오는 결론은 확정하지 않는다 → 문의 안내로 멈춤
                result = {"status": "NEED_EXPERT", "stage": stage_id, "stage_title": stage["title"],
                          "reason": "INTERPRETATION_NEEDED",
                          "message": "법 조문만으로 정할 수 없어 계산기가 결론을 내지 않습니다. 아래 근거 사례를 참고해 "
                                     "관할 기관에 확인한 뒤 그 회신에 따라 처리하세요.",
                          "reference_conclusion": {"label": entry["label"], "basis": entry["basis"],
                                                   "explanation": entry["explanation"]},
                          "consult": _consult(kb, stage_id, stage_answers, decided,
                                              f"해설·질의회신 사례에 따르면 '{entry['label']}'일 수 있으나 법 조문에 직접 근거가 없음",
                                              entry["basis"])}
                break
            decided.append(entry)
            if cand.get("terminal"):
                result = {"status": cand.get("status", "DETERMINED")}
                if cand.get("status") == "NEED_EXPERT":
                    issue = "법령 문언만으로 정할 수 없는 지점: " + " / ".join(gaps)
                    result.update({"stage": stage_id, "stage_title": stage["title"], "reason": "INTERPRETATION_NEEDED",
                                   "message": issue,
                                   "consult": _consult(kb, stage_id, stage_answers, decided[:-1], issue,
                                                       entry["basis"])})
                break
            stage_id = cand["next"]
            continue
        if all(s == FALSE for s in st["candidates"].values()):
            result = {"status": "OUT_OF_SCOPE", "stage": stage_id, "stage_title": stage["title"],
                      "message": "입력한 사실로는 이 단계의 어떤 결론에도 해당하지 않습니다. "
                                 "규칙 DB 범위 밖이므로 가장 가까운 결론으로 추측하지 않습니다."}
            break

        # 아직 판정되지 않음 → 구분 기준과 확인 방법을 돌려준다
        res = _resolution(kb, stage_id, st, stage_answers)
        nxt = next((c for c in res if c["state"] == "MISSING"), None)
        via = None
        if nxt is not None and nxt.get("derived_from"):
            # 다른 단계 판정으로 정해지는 사실 → 그 단계의 다음 질문을 대신 묻는다
            via = nxt["derived_from"]
            sub = _resolution(kb, via, eval_stage(kb, via, answers), answers)
            nxt["how_to_check"] = [{"text": f"'{kb.stages[via]['title']}' 질문에 답하면 정해집니다.", "basis": None}]
            nxt = next((c for c in sub if c["state"] == "MISSING"), None)
            if nxt is None:
                nxt = next((c for c in res if c["state"] == "MISSING" and not c.get("derived_from")), None)
            if nxt is None and not allow_interpretive:
                # 이 단계가 다른 단계 판정에 달려 있는데, 그 판정이 해석 자료로만 나온다 → 그 쟁점으로 문의 안내
                sub_st = eval_stage(kb, via, answers)
                interp = [e.rule for e in sub_st["evals"].values() if e.status == TRUE
                          and kb.sources[e.rule.source]["evidence"] != "LAW" and not e.rule.complement_of]
                if interp:
                    vstage = kb.stages[via]
                    label = vstage["candidates"][interp[0].concludes]["label"]
                    basis = [_basis(kb, r) for r in interp]
                    result = {"status": "NEED_EXPERT", "stage": via, "stage_title": vstage["title"],
                              "reason": "INTERPRETATION_NEEDED",
                              "message": "법 조문만으로 정할 수 없어 계산기가 결론을 내지 않습니다. 아래 근거 사례를 참고해 "
                                         "관할 기관에 확인한 뒤 그 회신에 따라 처리하세요.",
                              "reference_conclusion": {"label": label, "basis": basis,
                                                       "explanation": {"plain": [r.plain for r in interp if r.plain],
                                                                       "because": []}},
                              "consult": _consult(kb, via, answers, decided,
                                                  f"해설·질의회신 사례에 따르면 '{label}'일 수 있으나 법 조문에 직접 근거가 없음. "
                                                  f"이 판정에 따라 '{stage['title']}'도 달라짐", basis)}
                    break
        if nxt is not None:
            status = "NEED_TEST" if nxt["cost"] == "TEST" else "NEED_INFO"
        elif any(c["state"] == "CONFLICT" for c in res):
            status = "NEED_EXPERT"
        elif res and all(c["cost"] == "TEST" for c in res):
            status = "NEED_TEST"
        else:
            status = "NEED_INFO"
        result = {
            "status": status,
            "stage": stage_id,
            "stage_title": stage["title"],
            "open_candidates": [stage["candidates"][c]["label"] for c, s in st["candidates"].items() if s == UNDET],
            "resolution": res,
            "complement": _complement_note(kb, stage_id),
            "next_question": None if nxt is None else {
                "fact": nxt["fact"], "question": nxt["question"], "type": nxt["type"],
                "allowed_values": nxt.get("allowed_values"), "unit": nxt.get("unit"),
                "test": nxt.get("test"), "asked_for_stage": via},
        }
        if status == "NEED_EXPERT":
            result["reason"] = "FACT_CONFLICT"
        break

    # 검토 전 규칙·해석 근거로만 나온 결론 처리
    weak = [d for d in decided if not d["reviewed"] or not d["law_based"] or d["gaps"]]
    if strict and weak and result["status"] == "DETERMINED":
        result = {**result, "status": "NEED_EXPERT", "reason": "UNREVIEWED_OR_INTERPRETIVE",
                  "provisional": True,
                  "message": "결론은 나왔지만, 사람이 검토하지 않은 규칙이나 법령이 아닌 해석 자료에 기대고 있어 잠정 결론으로 표시합니다."}

    final = decided[-1] if decided else None
    used_sources = sorted({b["source_id"] for d in decided for b in d["basis"]})
    return {
        **result,
        "conclusion": final["label"] if final and (result["status"] == "DETERMINED" or result.get("provisional")) else None,
        "decided": decided,
        "summary": {d["stage"]: d["label"] for d in decided},
        "weak_basis": [{"stage": d["stage"], "reviewed": d["reviewed"], "law_based": d["law_based"], "gaps": d["gaps"]}
                       for d in weak],
        "answers": {k: v.to_json() for k, v in sorted(answers.items())},
        "law_versions": {s: {"title": kb.sources[s]["title"], "version": kb.sources[s]["version"],
                             "effective_on": kb.sources[s]["effective_on"]} for s in used_sources},
        "rule_db_version": kb.version,
        "as_of": kb.as_of,
        "strict": strict,
    }
