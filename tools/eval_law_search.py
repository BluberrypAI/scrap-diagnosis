"""법령 검색(search_law) 평가: knowledge/law/search_eval.yaml로 검색 방식을 비교한다.

    uv run python tools/eval_law_search.py            # 기준선(바이그램 겹침)과 현재 방식 비교
    uv run python tools/eval_law_search.py --misses   # 틀린 검색어와 상위 3개도 출력
    uv run python tools/eval_law_search.py --split test   # 보류 평가셋(검색 방식을 다 고친 뒤에만)

지표 (도구는 상위 3개만 돌려주므로 3에서 자른다)
- Hit@1 · Hit@3: 정답 조문 중 하나가 1위 · 상위 3개 안에 있는 비율 (정답이 있는 검색어만)
- MRR@3: 첫 정답 순위의 역수 평균, 3위 밖이면 0
- 빈 결과 정답률: negative 검색어에서 0건을 돌려준 비율
- 오답 0건률: 정답이 있는데 0건을 돌려준 비율 (낮을수록 좋음)
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.llm.law_search import LawIndex  # noqa: E402
from app.llm.tools import law_units  # noqa: E402

EVAL = ROOT / "knowledge" / "law" / "search_eval.yaml"
K = 3

Search = Callable[[str], list[str]]


def baseline(units: list[dict]) -> Search:
    """2026-11-21 develop(f427bd3)의 search_law를 그대로 옮긴 비교 기준."""

    def bigrams(s: str) -> set[str]:
        t = re.sub(r"\s+", "", s or "").lower()
        return {t[i : i + 2] for i in range(len(t) - 1)} or ({t} if t else set())

    docs = [(u["id"], bigrams(u["ref"] + " " + u["text"][:2000])) for u in units]

    def search(query: str) -> list[str]:
        q = bigrams(query)
        if not q:
            return []
        scored = [(len(q & b) / len(q), i) for i, b in docs]
        scored = [(s, i) for s, i in scored if s > 0.2]
        scored.sort(key=lambda x: -x[0])
        return [i for _, i in scored[:K]]

    return search


def current(units: list[dict]) -> Search:
    index = LawIndex(units)
    return lambda q: [u["id"] for u in index.search(q, K)]


def evaluate(search: Search, queries: list[dict]) -> tuple[dict, list[tuple[dict, list[str]]]]:
    by_style: dict[str, dict[str, float]] = {}
    misses = []
    for q in queries:
        got = search(q["query"])[:K]
        rel = set(q["relevant"])
        s = by_style.setdefault(q["style"], {"n": 0, "hit1": 0, "hit3": 0, "rr": 0, "empty": 0})
        s["n"] += 1
        s["empty"] += not got
        if rel:
            rank = next((i + 1 for i, g in enumerate(got) if g in rel), None)
            s["hit1"] += rank == 1
            s["hit3"] += rank is not None
            s["rr"] += 1 / rank if rank else 0
            if rank is None:
                misses.append((q, got))
        elif got:
            misses.append((q, got))
    return by_style, misses


def summarize(by_style: dict) -> dict[str, str]:
    pos = [v for k, v in by_style.items() if k != "negative"]
    n = sum(v["n"] for v in pos)
    neg = by_style.get("negative", {"n": 0, "empty": 0})
    row = {
        "Hit@1": sum(v["hit1"] for v in pos) / n,
        "Hit@3": sum(v["hit3"] for v in pos) / n,
        "MRR@3": sum(v["rr"] for v in pos) / n,
        "빈 결과 정답률": neg["empty"] / neg["n"] if neg["n"] else 0,
        "오답 0건률": sum(v["empty"] for v in pos) / n,
    }
    for k, v in by_style.items():
        if k != "negative":
            row[f"Hit@3 {k}({v['n']})"] = v["hit3"] / v["n"]
    return {k: f"{v:.2f}" for k, v in row.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--misses", action="store_true")
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    args = ap.parse_args()

    spec = yaml.safe_load(EVAL.read_text(encoding="utf-8"))
    queries = spec["queries"] if args.split == "dev" else spec["test"]
    units = law_units()
    known = {u["id"] for u in units}
    bad = [r for q in spec["queries"] + spec["test"] for r in q["relevant"] if r not in known]
    if bad:
        print("평가셋에 없는 조문 id:", bad)
        return 1

    results = {}
    for name, make in (("baseline", baseline), ("bm25", current)):
        by_style, misses = evaluate(make(units), queries)
        results[name] = (summarize(by_style), misses)

    print(
        f"평가셋 v{spec['version']} {args.split} · 검색어 {len(queries)}개"
        f" · 조문 단위 {len(units)}개\n"
    )
    keys = list(results["baseline"][0])
    print(f"{'지표':<20}{'baseline':>10}{'bm25':>10}")
    for k in keys:
        print(f"{k:<20}{results['baseline'][0][k]:>10}{results['bm25'][0][k]:>10}")

    if args.misses:
        for name, (_, misses) in results.items():
            print(f"\n--- {name} 틀린 검색어 {len(misses)}개")
            for q, got in misses:
                print(f"[{q['style']}] {q['query']}")
                print(f"    정답 {q['relevant'] or '(0건)'}")
                print(f"    결과 {got or '(0건)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
