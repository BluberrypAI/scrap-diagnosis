"""판정 규칙 초안 검사·채점·비교.

    uv run python tools/compare_flows.py check <draft_dir>          # 형식·사실·인용 검사
    uv run python tools/compare_flows.py score <draft_dir>          # 골든셋 채점
    uv run python tools/compare_flows.py diff <draft_a> <draft_b>   # 행동 비교(입력 같고 결론 다름)

이 도구는 골든셋(knowledge/cases)을 읽는다. 규칙 작성자에게 보여 주지 않는다.
"""

from __future__ import annotations

import copy
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.engine.flow import FlowError, load_flow, norm, run  # noqa: E402

FACTS = ROOT / "knowledge" / "flow" / "facts.yaml"
LAW = ROOT / "knowledge" / "law" / "articles"
CASES = ROOT / "knowledge" / "cases"


def catalog() -> dict[str, dict]:
    return {f["id"]: f for f in yaml.safe_load(FACTS.read_text(encoding="utf-8"))["facts"]}


def law_units() -> dict[str, str]:
    out = {}
    for f in LAW.glob("*.json"):
        doc = json.loads(f.read_text(encoding="utf-8"))
        for u in doc["units"]:
            out[f"{doc['key']}/{u['id']}"] = u["text"]
    return out


def squeeze(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def values_of(f: dict) -> set | None:
    if f["type"] == "bool3":
        return {"yes", "no", "unknown"}
    if f["type"] == "enum":
        return {norm(v) for v in f["values"]}
    return None


def walk_conditions(cond, out):
    if isinstance(cond, dict):
        if "fact" in cond:
            out.append(cond)
        for k in ("all", "any"):
            for c in cond.get(k, []):
                walk_conditions(c, out)
        if "not" in cond:
            walk_conditions(cond["not"], out)


def check(draft: Path) -> list[str]:
    errors = []
    try:
        stages = load_flow(draft)
    except (FlowError, KeyError, yaml.YAMLError) as e:
        return [f"로드 실패: {e}"]
    cat, units = catalog(), law_units()
    for st in stages:
        for r in st.rules:
            conds: list = []
            walk_conditions(r.when, conds)
            for c in conds:
                name = c["fact"]
                base, _, field = name.partition(".")
                f = cat.get(base)
                if f is None:
                    errors.append(f"{r.id}: 카탈로그에 없는 사실 {name}")
                    continue
                if field and field not in (f.get("fields") or {}):
                    errors.append(f"{r.id}: {base}에 없는 필드 {field}")
                    continue
                allowed = {"yes", "no", "unknown"} if field else values_of(f)
                for op in ("eq", "ne", "in", "not_in"):
                    if op in c and allowed is not None:
                        vals = c[op] if isinstance(c[op], list) else [c[op]]
                        bad = [v for v in vals if norm(v) not in allowed]
                        if bad:
                            errors.append(f"{r.id}: {name} 값이 카탈로그 밖 {bad}")
            if not r.basis:
                errors.append(f"{r.id}: 근거 없음")
            for b in r.basis:
                unit, quote = b.get("unit"), b.get("quote")
                if unit not in units:
                    errors.append(f"{r.id}: 적재되지 않은 근거 {unit!r}")
                elif quote and squeeze(quote) not in squeeze(units[unit]):
                    errors.append(f"{r.id}: 인용문이 원문과 다름 ({unit})")
    return errors


def golden_cases() -> list[tuple[str, dict, tuple]]:
    table = yaml.safe_load((CASES / "decision_table.yaml").read_text(encoding="utf-8"))
    golden = yaml.safe_load((CASES / "golden.yaml").read_text(encoding="utf-8"))
    trs = {t["id"]: t for t in table["test_requirements"]}
    out = []
    for c in golden["cases"]:
        tr = trs[c["tr"]]
        f = copy.deepcopy(table["baselines"][tr["base"]])
        for k, v in tr["changes"].items():
            f[k] = {**f.get(k, {}), **v} if isinstance(v, dict) else v
        e = c["expected"]
        out.append((c["id"], f, (e["outcome"], e["code"] or None, tuple(sorted(e["flags"])))))
    return out


def score(draft: Path, verbose: bool = True) -> dict:
    stages = load_flow(draft)
    rows = []
    for cid, f, exp in golden_cases():
        r = run(stages, f)
        rows.append((cid, exp, r.key(), r))
    ok = sum(e == g for _, e, g, _ in rows)
    outcome_ok = sum(e[0] == g[0] for _, e, g, _ in rows)
    if verbose:
        print(f"{draft}: 완전 일치 {ok}/{len(rows)}, 출력 클래스 일치 {outcome_ok}/{len(rows)}")
        for cid, e, g, r in rows:
            if e != g:
                last = r.trace[-1] if r.trace else {}
                print(f"  ✗ {cid} 기대 {e} / 결과 {g} / {last}")
    return {"exact": ok, "outcome": outcome_ok, "n": len(rows)}


def sample_inputs(n: int, seed: int = 7) -> list[dict]:
    """카탈로그 도메인에서 무작위 사실 조합 + 골든 사실."""
    rng = random.Random(seed)
    cat = catalog()
    inputs = [f for _, f, _ in golden_cases()]
    for _ in range(n):
        f: dict = {}
        for fid, d in cat.items():
            if d["type"] == "bool3":
                f[fid] = rng.choice(["yes", "no", "unknown"])
            elif d["type"] == "enum" and fid != "input_form":
                f[fid] = rng.choice([norm(v) for v in d["values"]])
            elif d["type"] == "object":
                f[fid] = {k: rng.choice(["yes", "no", "unknown"]) for k in d["fields"]}
        allowed = cat["input_form"]["allowed_by_material"].get(f["material"])
        f["input_form"] = rng.choice(allowed) if allowed else None
        f["daily_avg_kg"] = rng.choice([None, 0, 50, 299, 300, 1000])
        f["oil_pct_evidenced"] = rng.choice([None, None, 1, 4.9, 5.0, 20])
        inputs.append(f)
    return inputs


def diff(a: Path, b: Path, n: int = 3000) -> None:
    sa, sb = load_flow(a), load_flow(b)
    groups: dict[tuple, list] = defaultdict(list)
    inputs = sample_inputs(n)
    for f in inputs:
        ra, rb = run(sa, f), run(sb, f)
        if ra.key() != rb.key():
            la = ra.trace[-1].get("rule") if ra.trace else None
            lb = rb.trace[-1].get("rule") if rb.trace else None
            groups[(ra.key(), rb.key(), la, lb)].append(f)
    total = sum(len(v) for v in groups.values())
    print(f"입력 {len(inputs)}개 중 결론이 다른 입력 {total}개, 유형 {len(groups)}개")
    for (ka, kb, la, lb), fs in sorted(groups.items(), key=lambda x: -len(x[1])):
        print(f"- {len(fs)}건 | A {ka} ({la}) | B {kb} ({lb})")
    print("A 결과 분포:", Counter(run(sa, f).outcome for f in inputs).most_common())
    print("B 결과 분포:", Counter(run(sb, f).outcome for f in inputs).most_common())


def main() -> None:
    cmd = sys.argv[1]
    if cmd == "check":
        errs = check(Path(sys.argv[2]))
        print(f"{sys.argv[2]}: 오류 {len(errs)}개")
        for e in errs:
            print("  ✗", e)
        sys.exit(1 if errs else 0)
    if cmd == "score":
        score(Path(sys.argv[2]))
    elif cmd == "diff":
        diff(Path(sys.argv[2]), Path(sys.argv[3]))


if __name__ == "__main__":
    main()
