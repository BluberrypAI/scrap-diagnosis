"""LLM 사실 추출 평가: 기존 엔진의 질의회신 사례(testdata/cases.jsonl) 중 facts 라벨이 있는 것.

    uv run python scripts/eval_extractor.py [--legacy C:/Users/zxc20/re_project/resource_engine]

질의 원문(question_quote)을 사용자 발화로 넣고 추출 결과를 라벨과 비교한다.
- 기존 라벨의 waste_kind는 새 카탈로그에 없으므로
  추출된 material의 waste_kind(기존 materials.yaml)로 비교
- 라벨이 드물어(사례당 1~3개) 재현율은 참고값이다. 라벨에 없는 추출은 '추가 추출'로만 센다.
- 소재 분류 보조 지표(material_group_fallback): waste_kind 라벨이 있는데 소재를 뽑지 못한 경우,
  뽑은 material_group이 그 waste_kind를 가진 소재들의 분류(기존 materials.yaml group)에 드는지 센다.
  waste_kind 'other'처럼 여러 분류에 걸친 종류는 따로(unique_group_*) 본다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.extractor import extract  # noqa: E402
from app.agent.llm_client import make_client  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.rules.loader import load_kb  # noqa: E402


def load_cases(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 기존 파일에 깨진 줄이 있다(방어적으로 건너뜀)
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy", default="C:/Users/zxc20/re_project/resource_engine")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--report", default=str(ROOT / "var" / "eval_extractor.json"))
    args = ap.parse_args()
    legacy = Path(args.legacy)
    settings = get_settings()
    llm = make_client(settings)
    if llm is None:
        print("LLM 설정이 없습니다(.env)")
        return 2
    kb = load_kb(ROOT / "data" / "real")
    mats = yaml.safe_load((legacy / "rules" / "materials.yaml").read_text(encoding="utf-8"))
    kind_of = {k: v.get("waste_kind") for k, v in mats["materials"].items()}
    groups_of_kind: dict[str, set[str]] = {}
    for v in mats["materials"].values():
        if v.get("waste_kind") and v.get("group"):
            groups_of_kind.setdefault(v["waste_kind"], set()).add(v["group"])
    cases = [c for c in load_cases(legacy / "testdata" / "cases.jsonl") if c.get("facts")]

    def run(c: dict) -> dict:
        text = c["question_quote"]
        res, calls = extract(
            llm,
            kb,
            text,
            effective={},
            last_question=None,
            recent=[],
            message_id=c["case_id"],
            prompt_version=settings.prompt_version,
        )
        got = {f.key: f.value for f in res.facts if f.is_known}
        rows = []
        for k, v in c["facts"].items():
            if k == "waste_kind":
                m = got.get("material")
                kind = kind_of.get(m) if m else None
                g = got.get("material_group")
                rows.append(
                    {
                        "key": k,
                        "expected": v,
                        "got": f"material={m}({kind}) material_group={g}",
                        "comparable": True,
                        "hit": kind == v,
                        "material": m,
                        "group": g,
                        "expected_groups": sorted(groups_of_kind.get(v, ())),
                    }
                )
            elif k in kb.catalog:
                g = got.get(k)
                rows.append(
                    {
                        "key": k,
                        "expected": v,
                        "got": g,
                        "comparable": True,
                        "hit": str(g).lower() == str(v).lower(),
                    }
                )
            else:
                rows.append(
                    {"key": k, "expected": v, "got": None, "comparable": False, "hit": False}
                )
        return {
            "case_id": c["case_id"],
            "text": text[:120],
            "rows": rows,
            "extracted": {k: str(v) for k, v in got.items()},
            "rejected": [(r["key"], r["reason"]) for r in res.rejected],
            "attempts": res.attempts,
            "errors": res.errors,
            "latency_ms": sum(x.latency_ms for x in calls),
        }

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(run, cases))

    comp = [r for x in results for r in x["rows"] if r["comparable"]]
    hits = sum(1 for r in comp if r["hit"])
    kind_rows = [r for r in comp if r["key"] == "waste_kind"]
    no_mat = [r for r in kind_rows if not r["material"]]
    g_comp = [r for r in no_mat if r["expected_groups"]]
    g_unique = [r for r in g_comp if len(r["expected_groups"]) == 1]

    def g_hit(r: dict) -> bool:
        return r["group"] in r["expected_groups"]

    kind_ok = sum(1 for r in kind_rows if r["hit"] or (not r["material"] and g_hit(r)))
    fallback = {
        "waste_kind_labels": len(kind_rows),
        "no_material": len(no_mat),
        "comparable": len(g_comp),  # 그 waste_kind를 가진 소재가 있는 라벨
        "group_hit": sum(1 for r in g_comp if g_hit(r)),
        "group_wrong": sum(1 for r in g_comp if r["group"] and not g_hit(r)),
        "group_empty": sum(1 for r in g_comp if not r["group"]),
        "unique_group_comparable": len(g_unique),
        "unique_group_hit": sum(1 for r in g_unique if g_hit(r)),
        # 소재로 맞히거나, 소재가 없을 때 분류로 맞힌 waste_kind 라벨
        "material_or_group_hit": f"{kind_ok}/{len(kind_rows)}",
    }
    by_key = Counter((r["key"], r["hit"]) for r in comp)
    rejected = sum(len(x["rejected"]) for x in results)
    extracted = sum(len(x["extracted"]) for x in results)
    summary = {
        "cases": len(results),
        "labeled_facts": sum(len(x["rows"]) for x in results),
        "comparable_facts": len(comp),
        "value_accuracy": f"{hits}/{len(comp)}",
        "by_key": {f"{k}:{'hit' if h else 'miss'}": n for (k, h), n in sorted(by_key.items())},
        "material_group_fallback": fallback,
        "extracted_total": extracted,
        "guard_rejected": rejected,
        "guard_rejection_rate": round(rejected / (rejected + extracted), 3)
        if rejected + extracted
        else 0.0,
        "retries": sum(1 for x in results if x["attempts"] > 1),
        "llm_errors": sum(1 for x in results if x["errors"]),
        "avg_latency_ms": int(sum(x["latency_ms"] for x in results) / max(len(results), 1)),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    misses = [
        (x["case_id"], r) for x in results for r in x["rows"] if r["comparable"] and not r["hit"]
    ]
    for cid, r in misses[:15]:
        print("MISS", cid, r["key"], "기대", r["expected"], "/ 추출", r["got"])
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
