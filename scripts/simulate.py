"""CLI 시뮬레이터: 스크립트된 답변으로 질문 순서를 출력한다.

uv run python scripts/simulate.py data/sample/scenarios/basic.yaml [...]
uv run python scripts/simulate.py data/sample/scenarios/   # 폴더 안 전부
uv run python scripts/simulate.py --data data/real data/real/scenarios/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.simulation import simulate  # noqa: E402
from app.rules.loader import load_kb  # noqa: E402


def _scenario_files(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        out.extend(sorted(p.glob("*.yaml")) if p.is_dir() else [p])
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--data", default=str(ROOT / "data" / "sample"))
    ap.add_argument("--rules", default="rules/tables")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    kb = load_kb(args.data, args.rules)
    failed = 0
    for path in _scenario_files(args.paths):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        for sc in raw if isinstance(raw, list) else [raw]:
            res = simulate(kb, sc)
            if args.json:
                print(json.dumps(res.model_dump(mode="json"), ensure_ascii=False))
            else:
                print(f"== {res.scenario_id} ({path.name})")
                for t in res.turns:
                    if t.question:
                        top = ", ".join(f"{k}={s:.3f}" for k, s in t.score_top)
                        print(
                            f"  {t.turn:>2}. ASK {t.unit}:{t.question} -> {t.answer!r}"
                            f"   후보 {len(t.candidates)}개  [{top}]"
                        )
                    else:
                        print(
                            f"  {t.turn:>2}. {t.branch}  {t.reason}"
                            + (f" -> {t.answer}" if t.answer else "")
                        )
                print(
                    f"  결과: {res.final_branch} code={res.final_code} "
                    f"질문 {res.questions_asked}회"
                    + (f" 사유={res.failure_reason}" if res.failure_reason else "")
                )
            exp = sc.get("expect") or {}
            problems = []
            if "branch" in exp and exp["branch"] != res.final_branch:
                problems.append(f"branch {res.final_branch} != {exp['branch']}")
            if "code" in exp and exp["code"] != res.final_code:
                problems.append(f"code {res.final_code} != {exp['code']}")
            if "questions" in exp and exp["questions"] != res.questions_asked:
                problems.append(f"questions {res.questions_asked} != {exp['questions']}")
            if problems:
                failed += 1
                print("  !! 기대와 다름: " + "; ".join(problems))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
