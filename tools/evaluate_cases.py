"""정답셋(testdata/cases.jsonl)으로 계산기를 단계별로 채점한다.

사례에는 기관 질의에 적힌 사실만 들어 있어, S0부터 끝까지 돌리면 대부분 앞 단계 사실 부족으로 멈춘다.
그래서 기관이 결론을 말한 단계마다 그 단계만 따로 평가한다.

판정:
  CORRECT        기관과 같은 결론
  WRONG          기관과 다른 결론을 냄            ← 0이어야 함
  STOPPED        계산기가 정하지 못하고 멈춤(질문·시험 안내) — 틀린 것은 아님
  CORRECT_STOP   기관이 유보(UNDECIDED)했고 계산기도 멈춤
  OVERCONFIDENT  기관은 유보했는데 계산기가 결론을 냄  ← 검토 대상
  NOT_COMPARABLE 계산기 범위 밖 결론 형식
S4는 계산기가 번호를 고르지 않으므로, 기관 번호가 계산기 범위(후보) 안에 있는지로 본다(IN_RANGE / OUT_OF_RANGE).
S5는 기관 번호의 별표 4의3 결과와 비교한다(기관이 든 R코드가 계산기 허용 목록에 모두 있으면 CORRECT).

실행: python tools/evaluate_cases.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wastecalc.annex4 import _designated_prefixes  # noqa: E402
from wastecalc.engine import TRUE, eval_stage, parse_answers, with_derived  # noqa: E402
from wastecalc.kb import general_units, load_kb  # noqa: E402

KB = load_kb()
CASES = ROOT / "testdata" / "cases.jsonl"
OUT_CSV = ROOT / "testdata" / "eval_results.csv"
OUT_MD = ROOT / "testdata" / "eval_report.md"
CODES = {c["id"]: c for c in KB.annex4["codes"]}


def year_of(case: dict) -> tuple[int | None, str]:
    """회신·선고 연도(없으면 자료 발행 연도 추정)와 그 근거."""
    s = case["source"]
    d = s.get("answered_on") or ""
    if re.match(r"\d{4}", d):
        return int(d[:4]), "회신·선고일"
    m = re.search(r"add-case-(\d{2,4})[도두]", s["file"])
    if m:
        y = int(m.group(1))
        return (y + 1900 if y > 50 else y + 2000) if y < 100 else y, "사건번호"
    f = s["file"]
    if "tc-moe-qa-casebook-2025" in f:
        return 2025, "사례집 발간(2023~2025 질의)"
    if "wonju-qa-2026" in f:
        return 2025, "사례집(2021~2025 민원)"
    if "classification-guide-2023" in f:
        return 2023, "설명서 발간"
    if "recycling-qa" in f:
        return 2017, "사례집 발간"
    if f.endswith(".hwp"):
        return 2009, "사례집(2001~2009)"
    return None, "미상"


def stage_result(stage: str, facts: dict) -> str | None:
    answers = parse_answers(KB, facts)
    st = eval_stage(KB, stage, with_derived(KB, stage, answers))
    trues = [c for c, s in st["candidates"].items() if s == TRUE]
    return trues[0] if len(trues) == 1 else None


def s4_range(facts: dict) -> tuple[list[str] | None, str | None]:
    answers = parse_answers(KB, facts)
    st = eval_stage(KB, "S3", answers)
    trues = [c for c, s in st["candidates"].items() if s == TRUE]
    if trues == ["DESIGNATED"]:
        fired = [e.rule.id for e in st["evals"].values() if e.status == TRUE and e.rule.concludes == "DESIGNATED"]
        return _designated_prefixes(KB, fired)[0], "DESIGNATED"
    if trues == ["NOT_DESIGNATED"]:
        kind = facts.get("waste_kind")
        pre = KB.s4_map["general_by_kind"].get(kind) if isinstance(kind, str) else None
        return (pre or list(general_units(KB.annex4))), "NOT_DESIGNATED"
    return None, None


def s5_engine(code: str) -> tuple[str, set[str]]:
    row = next((r for r in KB.annex43["rows"] if r["code"] == code), None)
    for p in KB.s5_rules["prohibitions"]:
        if p["kind"] == "PROHIBITED" and any(code.startswith(x) for x in p["when"].get("codes_prefix", [])):
            return "PROHIBITED", set()
    if row is None or not row["cells"]:
        return "NOT_LISTED", set()
    if all(c["prohibited"] for c in row["cells"]):
        return "PROHIBITED", set()
    return "ALLOWED_TYPES", {rc for c in row["cells"] for rc in c["r_codes"]}


def judge(stage: str, expected, case: dict) -> tuple[str, str]:
    facts = case.get("facts") or {}
    if stage in {"S0", "S1", "S2", "S3"}:
        got = stage_result(stage, facts)
        if expected == "UNDECIDED":
            return ("CORRECT_STOP" if got is None else "OVERCONFIDENT"), str(got)
        if got is None:
            return "STOPPED", "결론 없음"
        return ("CORRECT" if got == expected else "WRONG"), got
    if stage == "S4":
        if expected in (None, "UNDECIDED"):
            return "NOT_COMPARABLE", ""
        code = expected if isinstance(expected, str) else None
        if code not in CODES:
            return "NOT_COMPARABLE", f"현행 별표 4에 없는 번호 {expected}"
        prefixes, s3 = s4_range(facts)
        if prefixes is None:
            return "STOPPED", "S3 미정 → 번호 범위 없음"
        inside = any(code.startswith(p) for p in prefixes)
        return ("IN_RANGE" if inside else "OUT_OF_RANGE"), f"{s3} 범위 {prefixes[:6]}"
    if stage == "S5":
        code = (case.get("expected") or {}).get("S4") or facts.get("code")
        if not isinstance(code, str) or code not in CODES:
            return "NOT_COMPARABLE", "기관 번호 없음"
        concl, allowed = s5_engine(code)
        exp = expected if isinstance(expected, dict) else {"conclusion": expected}
        if exp.get("conclusion") != concl:
            return "WRONG", f"계산기 {concl}"
        want = set(exp.get("allowed_types") or [])
        if want and not want <= allowed:
            return "WRONG", f"기관 R코드 {sorted(want - allowed)}가 계산기 허용 목록에 없음"
        return "CORRECT", concl
    return "NOT_COMPARABLE", ""


# 보조 평가용 가정: 질의에 언급되지 않은 '공통 위험'은 없다고 본다. 계산기 본 동작에는 쓰지 않는다.
ASSUME_ABSENT = {"circular_resource_recognized": False, "direct_reinput": False,
                 "pcb_possible": False, "toxic_chemical_discard": False}


def with_assumptions(case: dict) -> dict:
    facts = dict(case.get("facts") or {})
    for k, v in ASSUME_ABSENT.items():
        facts.setdefault(k, v)
    if "oil_presence" not in facts and facts.get("waste_kind") not in {"waste_oil", "edible_oil", None}:
        facts["oil_presence"] = "none"
    return {**case, "facts": facts}


def main() -> None:
    cases = [json.loads(l) for l in CASES.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = []
    assumed_rows = []
    for c in cases:
        for stage, exp in sorted((c.get("expected") or {}).items()):
            if stage in {"S0", "S1", "S2", "S3"}:
                v, d = judge(stage, exp, with_assumptions(c))
                assumed_rows.append({"case_id": c["case_id"], "split": c["split"], "stage": stage,
                                     "expected": json.dumps(exp, ensure_ascii=False), "verdict": v, "detail": d})
    for c in cases:
        y, ybasis = year_of(c)
        for stage, exp in sorted((c.get("expected") or {}).items()):
            verdict, detail = judge(stage, exp, c)
            rows.append({"case_id": c["case_id"], "split": c["split"], "stage": stage,
                         "expected": json.dumps(exp, ensure_ascii=False), "verdict": verdict, "detail": detail,
                         "year": y, "year_basis": ybasis, "legacy_code": c.get("legacy_code"),
                         "source": c["source"]["file"].split("/")[-1]})
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    def table(sel, key):
        cnt = defaultdict(Counter)
        for r in sel:
            cnt[key(r)][r["verdict"]] += 1
        verdicts = ["CORRECT", "IN_RANGE", "CORRECT_STOP", "STOPPED", "WRONG", "OUT_OF_RANGE", "OVERCONFIDENT",
                    "NOT_COMPARABLE"]
        lines = ["| 구분 | " + " | ".join(verdicts) + " |", "|---" * (len(verdicts) + 1) + "|"]
        for k in sorted(cnt, key=str):
            lines.append(f"| {k} | " + " | ".join(str(cnt[k][v]) for v in verdicts) + " |")
        return "\n".join(lines)

    def era(y):
        if y is None:
            return "연도 미상"
        if y < 2016:
            return "~2015 (재활용 유형 제도 이전)"
        if y < 2023:
            return "2016~2022"
        return "2023~"

    ev = [r for r in rows if r["split"] == "EVAL"]
    bad = [r for r in rows if r["verdict"] in {"WRONG", "OUT_OF_RANGE", "OVERCONFIDENT"}]
    md = ["# 정답셋 평가 결과", "",
          f"사례 {len(cases)}건 중 단계 기대값이 있는 판정 {len(rows)}개 (EVAL {len(ev)}개). "
          f"규칙 DB `{KB.version}`, 기준일 {KB.as_of}(현행 법령으로 채점), strict 해제(규칙 검토 여부와 무관하게 결론만 비교).", "",
          "## EVAL — 단계별", table(ev, lambda r: r["stage"]), "",
          "## DEV — 단계별 (규칙 작성 때 본 사례, 참고용)", table([r for r in rows if r["split"] == "DEV"], lambda r: r["stage"]), "",
          "## 전체 — 회신 시기별", "회신 당시 법령이 현행과 다를 수 있으므로 오래된 사례의 불일치는 법령 변경 때문일 수 있다.", "",
          table(rows, lambda r: era(r["year"])), "",
          "## 검토가 필요한 판정 (WRONG / OUT_OF_RANGE / OVERCONFIDENT)", ""]
    for r in bad:
        md.append(f"- `{r['case_id']}` {r['stage']} {r['verdict']} — 기관 {r['expected']} / 계산기 {r['detail']} "
                  f"({r['year']} {r['year_basis']}, {r['split']})")
    abad = [r for r in assumed_rows if r["verdict"] in {"WRONG", "OVERCONFIDENT"}]
    md += ["", "## 보조 평가 — 언급 없는 공통 위험을 '없음'으로 가정 (S0~S3)",
           f"가정: {ASSUME_ABSENT} + 기름 관련 종류가 아니면 oil_presence=none. "
           "계산기 실제 동작이 아니라 규칙 논리만 보는 참고 지표다.", "",
           table([r for r in assumed_rows if r["split"] == "EVAL"], lambda r: r["stage"]), "",
           "가정 평가에서 검토가 필요한 판정:", ""]
    for r in abad:
        md.append(f"- `{r['case_id']}` {r['stage']} {r['verdict']} — 기관 {r['expected']} / 계산기 {r['detail']} ({r['split']})")
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
