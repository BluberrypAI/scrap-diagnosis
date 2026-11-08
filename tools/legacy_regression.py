"""기존 엔진 소재별 판정표(4281행)와 새 엔진 결과를 비교한다.

    uv run python tools/legacy_regression.py            # 요약
    uv run python tools/legacy_regression.py --diff 20  # 다른 행 일부 출력

각 행의 입력 = 기본 사실(BASE) + 소재 + 답. 수치는 기존 엔진처럼 성적서 값(EVIDENCED)으로 넣는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.router import Branch, SessionState, run_engine  # noqa: E402
from app.domain.facts import Fact, FactStatus, FactStore  # noqa: E402
from app.rules.loader import load_kb  # noqa: E402
from app.rules.model import KnowledgeBase  # noqa: E402

REG = ROOT / "data" / "real" / "regression"
AS_OF = date(2026, 11, 8)


def load_rows(path: Path = REG / "material_rows.jsonl") -> tuple[dict, list[dict]]:
    meta = json.loads((path.parent / "meta.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return meta, rows


def row_store(kb: KnowledgeBase, base: dict, row: dict) -> FactStore:
    store = FactStore()
    kv = {**base, "material": row["material"], **row["answers"]}
    for k, v in kv.items():
        if k not in kb.catalog:
            continue
        fd = kb.catalog[k]
        status = FactStatus.EVIDENCED if fd.type == "number" else FactStatus.CLAIMED
        store.append(
            Fact(key=k, value=v, status=status, source_type="SIMULATION", source_ref=row["id"])
        )
    return store


# 기존 판정표 생성기(tools/material_tables.py)는 오염 사실을 기본 '아니오'로 두고 하나만 바꿔 봤다.
# 기존 엔진이 묻지 않고 끝낸 사실을 새 엔진이 물으면 이 기본값으로 답한다(추가 질문으로 집계).
WALK_DEFAULTS = {
    "designated_residue": False,
    "oil_presence": "none",
    "pcb_possible": False,
    "toxic_chemical_discard": False,
}


def check_row(kb: KnowledgeBase, base: dict, row: dict) -> tuple[str, str, int]:
    """반환: (판정, 설명, 추가 질문 수). 판정은 MATCH | FEWER_CHOICES | DIFF."""
    store = row_store(kb, base, row)
    state = SessionState()
    extra = 0
    for _ in range(8):
        step = run_engine(kb, store, state, AS_OF)
        d = step.decision
        if d.branch != Branch.ASK_FACT or d.question.key == "annex4_code":
            break
        q = d.question
        targets = q.facts if q.unit == "group" else [q.key]
        if not all(k in WALK_DEFAULTS for k in targets):
            break
        extra += 1
        for k in targets:
            store.append(
                Fact(
                    key=k,
                    value=WALK_DEFAULTS[k],
                    status=FactStatus.CLAIMED,
                    source_type="SIMULATION",
                    source_ref="walk-default",
                )
            )
    d, ev = step.decision, step.evaluation
    v, why = _compare(d, ev, row["expect"])
    return v, why, extra


def _compare(d, ev, exp) -> tuple[str, str]:
    got = f"{d.branch.value}"
    if d.branch == Branch.FINAL_REVIEW:
        got += f" {ev.decided.code}"
    elif d.branch == Branch.ASK_FACT:
        n = len([o for o in d.question.value_options if o.kind == "value"])
        got += f" {d.question.key}({n})"
    elif d.failure_reason:
        got += f" {d.failure_reason}"
    if exp["kind"] == "CODE":
        ok = d.branch == Branch.FINAL_REVIEW and ev.decided.code == exp["code"]
        return ("MATCH" if ok else "DIFF"), f"기대 {exp['code']} / 결과 {got}"
    if exp["kind"] == "CODE_CHOICE":
        if d.branch == Branch.ASK_FACT and d.question.key == "annex4_code":
            n = len([o for o in d.question.value_options if o.kind == "value"])
            if n == exp["n"]:
                return "MATCH", got
            if exp.get("multi_reason") and n < exp["n"]:
                return "FEWER_CHOICES", f"기대 선택지 {exp['n']}개 / 결과 {n}개"
        return "DIFF", f"기대 번호 선택({exp['n']}) / 결과 {got}"
    ok = d.branch == Branch.UNSUPPORTED and d.failure_reason == exp["reason"]
    return ("MATCH" if ok else "DIFF"), f"기대 {exp['reason']} / 결과 {got}"


def run(kb: KnowledgeBase | None = None, limit_diff: int = 0) -> dict:
    kb = kb or load_kb(ROOT / "data" / "real")
    meta, rows = load_rows()
    verdicts: Counter = Counter()
    by_kind: Counter = Counter()
    extra_q: Counter = Counter()
    diffs: list[str] = []
    fewer: list[str] = []
    for row in rows:
        v, why, extra = check_row(kb, meta["base"], row)
        extra_q[extra] += 1
        verdicts[v] += 1
        by_kind[(row["expect"]["kind"], v)] += 1
        line = f"{row['id']} {json.dumps(row['answers'], ensure_ascii=False)} → {why}"
        if v == "DIFF":
            diffs.append(line)
        elif v == "FEWER_CHOICES":
            fewer.append(line)
    if limit_diff:
        for line in diffs[:limit_diff]:
            print("DIFF", line)
    return {
        "rows": len(rows),
        "verdicts": dict(verdicts),
        "by_kind": {f"{k}/{v}": n for (k, v), n in sorted(by_kind.items())},
        "extra_questions": dict(sorted(extra_q.items())),
        "diffs": diffs,
        "fewer": fewer,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", type=int, default=0)
    ap.add_argument("--fewer", type=int, default=0)
    ap.add_argument("--write", action="store_true", help="data/real/regression/summary.md 작성")
    args = ap.parse_args()
    res = run(limit_diff=args.diff)
    for line in res["fewer"][: args.fewer]:
        print("FEWER", line)
    summary = {k: res[k] for k in ("rows", "verdicts", "by_kind", "extra_questions")}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.write:
        lines = [
            "# 기존 엔진 판정표 회귀 결과",
            "",
            "`uv run python tools/legacy_regression.py --write`로 생성. "
            "허용 기준은 tests/test_legacy_regression.py.",
            "",
            "```json",
            json.dumps(summary, ensure_ascii=False, indent=2),
            "```",
            "",
            f"## 다른 행 ({len(res['diffs'])})",
            *[f"- {x}" for x in res["diffs"]],
            "",
            f"## 선택지가 기존보다 적은 행 ({len(res['fewer'])}) — 앞 30개",
            *[f"- {x}" for x in res["fewer"][:30]],
            "",
        ]
        (REG / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
