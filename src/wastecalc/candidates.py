"""남은 분류번호 후보(시행규칙 별표 4) 세기.

화면의 '남은 후보 N개', 'N개를 M개로 줄이는 질문'을 위한 것이다. 판정에는 쓰지 않는다.
후보 = 지금까지의 답과 모순되지 않는 별표 4 번호(지정·사업장일반, 생활폐기물 번호 제외).

- 폐기물 아님·적용 제외·생활폐기물·해석 필요 등 번호가 없는 결론이면 0개.
- S4에서 번호를 묻는 중이면 그 보기들, 정해졌으면 1개.
- 그 전에는 S3(지정폐기물) 규칙 중 아직 거짓이 아닌 것들이 가리키는 번호 범위 + (지정 아님이 가능하면) 일반 번호 범위.
확률이나 '가능성 %'는 내지 않는다. 법령 문언으로 정해지는 범위만 센다.
"""
from __future__ import annotations

from typing import Any

from .annex4 import general_material_options
from .engine import FALSE, eval_stage, evaluate, parse_answers, with_derived
from .kb import KB

NO_CODE = {"NOT_WASTE", "CIRCULAR_RESOURCE", "EXCLUDED", "HOUSEHOLD", "NEEDS_INTERPRETATION"}


def _pool(kb: KB, section: str, prefixes: list[str] | None = None) -> list[str]:
    excluded = set(kb.s4_map.get("excluded_codes", []))
    return [c["id"] for c in kb.annex4["codes"] if c["section"] == section and c["id"] not in excluded
            and (prefixes is None or any(c["id"].startswith(p) for p in prefixes))]


def _designated_prefixes(kb: KB, rule_ids: list[str]) -> list[str]:
    m = kb.s4_map["designated"]
    out: list[str] = []
    for rid in rule_ids:
        keys = [k for k in m if rid.startswith(k)]
        if keys:
            out += m[max(keys, key=len)]
    return list(dict.fromkeys(out))


def code_candidates(kb: KB, answers_raw: dict, r: dict) -> list[str]:
    """evaluate 결과 r과 그 입력으로 남은 별표 4 번호 목록. kb는 r의 기준일 보기(KB.at)."""
    decided = r.get("decided", [])
    s4 = next((d for d in decided if d["stage"] == "S4"), None)
    if s4 is not None:
        return [s4["conclusion"]]
    if r["status"] == "OUT_OF_SCOPE":
        return []
    if any(d["conclusion"] in NO_CODE for d in decided):
        return []
    if r.get("stage") == "S4":
        nq = r.get("next_question") or {}
        if nq.get("fact") == "code" and nq.get("allowed_values"):
            return list(nq["allowed_values"])
        if nq.get("fact") == "no_specific_code_applies":
            code = answers_raw.get("code")
            return [code] if isinstance(code, str) else []
        if r.get("candidates"):
            return list(r["candidates"])
    from .engine import apply_material
    from .kb import material

    answers = with_derived(kb, "S3", apply_material(kb, parse_answers(kb, answers_raw)))
    mat = material(kb, answers)
    mat_codes = (mat or {}).get("codes") or {}
    st = eval_stage(kb, "S3", answers)
    out: list[str] = []
    if st["candidates"].get("DESIGNATED") != FALSE:
        ids = [e.rule.id for e in st["evals"].values() if e.rule.concludes == "DESIGNATED" and e.status != FALSE]
        prefixes = _designated_prefixes(kb, ids)
        if prefixes:
            pool = _pool(kb, "DESIGNATED", prefixes)
            if mat_codes.get("DESIGNATED"):
                # 소재 자체가 사유인 경로는 소재 번호로, 그 밖의 사유(오염 등)는 그 사유의 번호를 그대로 둔다
                own = [c for c in pool if any(c.startswith(p) for p in mat_codes["DESIGNATED"])]
                other_ids = [i for i in ids if not any(c.startswith(p) for p in mat_codes["DESIGNATED"]
                                                       for c in _pool(kb, "DESIGNATED", _designated_prefixes(kb, [i])))]
                pool = list(dict.fromkeys(own + _pool(kb, "DESIGNATED", _designated_prefixes(kb, other_ids))))
            out += pool
    if st["candidates"].get("NOT_DESIGNATED") != FALSE:
        kind = answers.get("waste_kind")
        kv = kind.values[0] if kind is not None and kind.kind == "VALUE" else None
        _, conditional_codes = general_material_options(kb, answers)
        pre = conditional_codes or (list(mat_codes["GENERAL"]) if mat_codes.get("GENERAL") else (
            kb.s4_map["general_by_kind"].get(kv) if kv else None))
        if not pre:
            g = answers.get("general_group")
            pre = [g.values[0]] if g is not None and g.kind == "VALUE" else None
        out += _pool(kb, "GENERAL", pre)
    return list(dict.fromkeys(out))


def count_after(kb: KB, answers_raw: dict, fact: str, value: Any, strict: bool) -> int:
    """fact=value로 답했을 때 남는 번호 수."""
    trial = {**answers_raw, fact: value}
    rr = evaluate(trial, strict=strict, kb=kb, as_of=kb.as_of)
    return len(code_candidates(kb, trial, rr))
