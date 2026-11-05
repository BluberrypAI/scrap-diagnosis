"""문진 사용자 흐름 감사. 합성 입력만 사용하며 제품 코드와 기존 평가 자료는 바꾸지 않는다."""
from __future__ import annotations

import json
import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wastecalc.candidates import code_candidates
from wastecalc.compact import compact
from wastecalc.engine import evaluate
from wastecalc.kb import load_kb

KB = load_kb(as_of="2026-11-05")
BASE = {"material_fate": "released", "circular_resource_recognized": False,
        "law_exclusion": "none", "emission_facility": True}
CLEAN = {"designated_residue": False, "oil_presence": "none", "pcb_possible": False,
         "toxic_chemical_discard": False}


def ev(a):
    return evaluate(a, strict=True, kb=KB, as_of=KB.as_of)


def brief(r):
    return {"status": r["status"], "stage": r.get("stage"),
            "next": (r.get("next_question") or {}).get("fact"),
            "decisions": {d["stage"]: d["conclusion"] for d in r["decided"]},
            "range": next((d.get("range") for d in r["decided"] if d["stage"] == "S4"), None)}


def trace(values):
    answers, rows = {}, []
    for _ in range(65):
        r = ev(answers)
        q = r.get("next_question")
        if not q:
            return {"steps": rows, "final": brief(r), "answers": answers}
        fid = q["fact"]
        if fid in answers:
            return {"steps": rows, "loop_fact": fid, "result": brief(r), "answers": answers}
        if fid not in values:
            return {"steps": rows, "missing_fixture": fid, "result": brief(r)}
        c = compact(r, KB, answers)
        opts = c["next_question"].get("choices") or []
        sets = [sorted(code_candidates(KB, {**answers, fid: o["value"]}, ev({**answers, fid: o["value"]})))
                for o in opts if o["value"] != "UNKNOWN"]
        before = len(code_candidates(KB, answers, r))
        answers[fid] = values[fid]
        after = len(code_candidates(KB, answers, ev(answers)))
        rows.append({"fact": fid, "question": q["question"], "value": values[fid],
                     "before": before, "after": after,
                     "all_option_candidate_sets_equal": bool(sets) and all(s == sets[0] for s in sets),
                     "option_counts": [{"value": o["value"], "remaining": o.get("remaining")} for o in opts]})
    raise RuntimeError("trace exceeded bounded length")


def main():
    fixtures = {
        "clean_metal": {**BASE, **CLEAN, "waste_kind": "other", "physical_state": "solid",
                        "general_group": "51-29", "code": "51-29-01"},
        "clean_resin": {**BASE, **CLEAN, "waste_kind": "synthetic_resin", "physical_state": "solid",
                        "code": "51-03-01"},
        "small_clean_metal": {**BASE, **CLEAN, "emission_facility": False, "work_type": "none",
                              "daily_avg_kg": 100, "designated_waste_emitted": False,
                              "waste_facility": False, "public_facility": "none",
                              "waste_kind": "other", "physical_state": "solid"},
        "waste_oil": {**BASE, "waste_kind": "waste_oil", "code": "06-01-01",
                      "pcb_possible": False, "toxic_chemical_discard": False},
        "acid": {**BASE, "waste_kind": "acid", "physical_state": "liquid", **CLEAN,
                 "ph": 1, "code": "02-01-02"},
    }
    out = {"as_of": KB.as_of, "rule_db_version": KB.version,
           "scope": "synthetic fixtures; code consistency, not legal validation or user study",
           "traces": {name: trace(a) for name, a in fixtures.items()}}
    # 최종 결과에서 이미 답한 사실을 하나씩 제거해도 결과와 후속 질문이 같은지 확인.
    for t in out["traces"].values():
        if "final" not in t:
            continue
        a = t["answers"]
        t["removable_for_this_completed_path"] = [f for f in a if brief(ev({k: v for k, v in a.items() if k != f})) == t["final"]]

    full = fixtures["clean_metal"]
    out["metal_without_physical_state"] = brief(ev({k: v for k, v in full.items() if k != "physical_state"}))
    out["oil_pcb_comparison"] = {
        "not_screened": brief(ev({**BASE, "waste_kind": "waste_oil", "toxic_chemical_discard": False, "code": "06-01-01"})),
        "pcb_unknown": brief(ev({**BASE, "waste_kind": "waste_oil", "pcb_possible": "UNKNOWN", "toxic_chemical_discard": False, "code": "06-01-01"})),
        "pcb_positive": brief(ev({**BASE, "waste_kind": "waste_oil", "physical_state": "liquid",
                                   "pcb_possible": True, "pcb_mg_l": 3, "toxic_chemical_discard": False, "code": "08-01-00"})),
    }
    # S4의 모름은 이미 답한 항목을 다시 묻는지 확인한다.
    resin = fixtures["clean_resin"]
    out["s4_unknown"] = brief(ev({**resin, "code": "UNKNOWN"}))
    out["s4_catchall_unknown"] = brief(ev({**resin, "code": "51-03-99", "no_specific_code_applies": "UNKNOWN"}))
    out["s4_repeated_unknown"] = [brief(ev({**resin, "code": "UNKNOWN"})) for _ in range(3)]
    out["rubber_with_resin_code"] = brief(ev({**resin, "waste_kind": "synthetic_rubber"}))
    # HTTP 전송 계층과 분리하여 API 처리 함수의 상태 변경을 확인한다.
    import wastecalc.web.app as web
    previous_db = web.SESSION_DB
    with tempfile.TemporaryDirectory(prefix="wastecalc-audit-") as tmp:
        try:
            web.SESSION_DB = Path(tmp) / "sessions.sqlite3"
            session = web.api_start(web.StartReq(answers=resin, strict=True))
            sid = session["session_id"]
            changed = web.api_answer(sid, web.AnswerReq(fact="waste_kind", value="synthetic_rubber"))
            out["api_edit_resin_to_rubber"] = {"result": changed["result"], "answered": changed["answered"],
                                                "needs_review": changed["needs_review"]}
            web.SESSIONS.pop(sid, None)
        finally:
            web.SESSION_DB = previous_db
    nested = {**BASE, "emission_facility": False, "work_type": "none", "daily_avg_kg": 100}
    out["s2_asks_s3_compact"] = compact(ev(nested), KB, nested)
    # 정답셋 도구를 기존 파일에 쓰지 않고 현재 코드로 다시 채점한다.
    import importlib.util
    from collections import Counter
    spec = importlib.util.spec_from_file_location("case_evaluator", ROOT / "tools/evaluate_cases.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    counts, bad = Counter(), []
    for line in (ROOT / "testdata/cases.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        if case["split"] != "EVAL":
            continue
        for stage, expected in (case.get("expected") or {}).items():
            verdict, detail = module.judge(stage, expected, case)
            counts[verdict] += 1
            if verdict in {"WRONG", "OVERCONFIDENT", "OUT_OF_RANGE"}:
                bad.append({"case_id": case["case_id"], "stage": stage, "verdict": verdict, "detail": detail})
    out["current_existing_evaluator"] = {"version": module.KB.version, "as_of": module.KB.as_of,
                                         "counts": dict(counts), "bad": bad}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "audit/user_flow_audit_2026-11-05_after.json")
    target = parser.parse_args().output
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(target), "as_of": KB.as_of, "version": KB.version,
                      "traces": {name: {"questions": len(t["steps"]), "loop_fact": t.get("loop_fact"),
                                        "missing_fixture": t.get("missing_fixture")} for name, t in out["traces"].items()},
                      "current_existing_evaluator": out["current_existing_evaluator"]}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
