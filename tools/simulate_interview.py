"""문진 계획 평가: 골든셋 사실을 아는 가상 사용자로 문진을 끝까지 돌린다.

    uv run python tools/simulate_interview.py            # 요약
    uv run python tools/simulate_interview.py --detail   # 케이스별 질문 순서

측정: 결론 정확도(골든 기대 결과와 같은가), 질문 수(버튼 누름 횟수), 회사 질문 수,
계획에 없는 질문(Q-UNPLANNED), 골든 사실에 없는 값을 물은 횟수.
회사 질문은 두 경우로 잰다: 첫 문진(회사 정보 없음) / 두 번째부터(회사 정보 기억).
"""

from __future__ import annotations

import copy
import statistics
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.engine.planner import load, next_question, set_path  # noqa: E402

CASES = ROOT / "knowledge" / "cases"
COMPANY = (
    "emission_facility",
    "public_facility",
    "daily_avg_kg",
    "construction_5t",
    "site_emits_designated",
)


def golden() -> list[tuple[str, dict, tuple]]:
    table = yaml.safe_load((CASES / "decision_table.yaml").read_text(encoding="utf-8"))
    gold = yaml.safe_load((CASES / "golden.yaml").read_text(encoding="utf-8"))
    trs = {t["id"]: t for t in table["test_requirements"]}
    out = []
    for c in gold["cases"]:
        tr = trs[c["tr"]]
        f = copy.deepcopy(table["baselines"][tr["base"]])
        for k, v in tr["changes"].items():
            f[k] = {**f.get(k, {}), **v} if isinstance(v, dict) else v
        e = c["expected"]
        out.append((c["id"], f, (e["outcome"], e["code"] or None, tuple(sorted(e["flags"])))))
    return out


def truth(facts: dict, path: str):
    base, _, sub = path.partition(".")
    v = facts.get(base)
    if sub:
        v = v.get(sub) if isinstance(v, dict) else None
    return v


def simulate(stages, plan, facts: dict, prefill_company: bool) -> dict:
    answers: dict = {}
    if prefill_company:
        for k in COMPANY:
            if k in facts:
                answers[k] = facts[k]
    log, clicks, company_clicks, missing, unplanned = [], 0, 0, 0, 0
    # 묻지 않는 기본값(가정, D17)이 실제와 다르면 사용자가 판정 보드에서 고친다(한 번 누름)
    for a in plan.assume:
        for k, v in a["set"].items():
            t = truth(facts, k)
            if t is not None and str(
                t if not isinstance(t, bool) else ("yes" if t else "no")
            ) != str(v):
                set_path(answers, k, t)
                clicks += 1
                log.append(f"보드에서 고침:{k}={t}")
    for _ in range(60):
        nxt = next_question(stages, plan, answers)
        if nxt.done:
            r = nxt.result
            return {
                "result": r.key(),
                "clicks": clicks,
                "company_clicks": company_clicks,
                "missing": missing,
                "unplanned": unplanned,
                "log": log,
            }
        q = nxt.question
        is_company = q.get("scope") == "company"
        if q["id"] == "Q-UNPLANNED":
            unplanned += 1
        if q.get("kind") == "group":
            items = {i["fact"]: i for i in q["items"]}
            values = {f: truth(facts, f) for f in nxt.facts}
            if "all_yes_label" in q:
                one_click = all(v == "yes" for v in values.values())
                for f in values:
                    set_path(answers, f, "yes" if one_click else "unknown")
                clicks += 1
                company_clicks += is_company
                log.append(f"{q['id']}:{'모두 마침' if one_click else '아니요'}")
                continue
            if all(v == items[f].get("none") for f, v in values.items()):
                for f in nxt.facts:
                    set_path(answers, f, items[f]["none"])
                clicks += 1
                company_clicks += is_company
                log.append(f"{q['id']}:해당 없음")
                continue
            clicks += 1  # "해당하거나 모름" → 항목별로 하나씩
            company_clicks += is_company
            log.append(f"{q['id']}:펼침")
            for f in nxt.facts:
                v = values[f]
                if v is None:
                    missing += 1
                    v = "unknown"
                set_path(answers, f, v)
                clicks += 1
                company_clicks += is_company
                log.append(f"  {f}={v}")
            continue
        f = nxt.facts[0]
        v = truth(facts, f)
        if v is None:
            missing += 1
            v = "unknown"
        set_path(answers, f, v)
        clicks += 1
        company_clicks += is_company
        log.append(f"{q['id']}:{f}={v}")
    raise RuntimeError("질문이 60번을 넘음(계획 순환)")


def main() -> None:
    stages, plan = load()
    detail = "--detail" in sys.argv
    for prefill in (False, True):
        rows = []
        for cid, facts, exp in golden():
            s = simulate(stages, plan, facts, prefill)
            rows.append((cid, exp, s))
        ok = sum(s["result"] == exp for _, exp, s in rows)
        clicks = [s["clicks"] for _, _, s in rows]
        general = [s["clicks"] for _, exp, s in rows if exp[0] == "GENERAL"]
        title = "회사 정보 기억(두 번째 문진부터)" if prefill else "첫 문진(회사 정보 없음)"
        print(f"== {title}")
        print(f"  결론 정확도 {ok}/{len(rows)}")
        print(
            f"  질문 수: 평균 {statistics.mean(clicks):.1f}, 중앙값 {statistics.median(clicks)}, "
            f"최대 {max(clicks)}, 최소 {min(clicks)} | "
            f"일반폐기물(GENERAL) 평균 {statistics.mean(general):.1f}"
        )
        print(
            f"  회사 질문 평균 {statistics.mean(s['company_clicks'] for _, _, s in rows):.1f}, "
            f"계획 외 질문 {sum(s['unplanned'] for _, _, s in rows)}, "
            f"골든에 없는 값을 물음 {sum(s['missing'] for _, _, s in rows)}"
        )
        by_outcome = Counter()
        for _, exp, s in rows:
            by_outcome[exp[0]] += s["clicks"]
        cnt = Counter(exp[0] for _, exp, _ in rows)
        print("  결과별 평균 질문 수:", {k: round(by_outcome[k] / cnt[k], 1) for k in cnt})
        for cid, exp, s in rows:
            if s["result"] != exp:
                print(f"  ✗ {cid} 기대 {exp} / 결과 {s['result']} / {' > '.join(s['log'][-4:])}")
        if detail:
            for cid, exp, s in rows:
                print(f"  {cid} ({s['clicks']}) {exp[0]} {exp[1] or ''}: {' > '.join(s['log'])}")


if __name__ == "__main__":
    main()
