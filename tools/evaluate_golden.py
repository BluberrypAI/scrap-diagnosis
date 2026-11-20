"""골든 데이터셋 품질 평가: 커버리지와 뮤테이션 테스팅.

    uv run python tools/evaluate_golden.py   # 리포트 출력 + knowledge/cases/evaluation.yaml

1. 커버리지: input_model의 파티션·경계값, 게이트 G1~G8, 출력 클래스를 골든 케이스가 덮는 비율
2. 뮤테이션 테스팅: 명세 오라클(tools/cases_spec.py)을 AST 단위로 하나씩 변형(mutant)하고,
   골든셋 76건 중 하나라도 결과가 달라지면 그 변형을 '잡았다(killed)'고 본다.
   mutation score = killed / 전체. 살아남은 변형(survivor)이 골든셋의 빈틈 후보다.
   변형 연산자: ROR(비교 연산자 교체), CRP(수치 상수 ±1), BRD(분기 조건을 True/False로),
   SER(모듈 상수 집합·튜플의 원소 하나 제거), BOR(and/or 교체)
"""

from __future__ import annotations

import ast
import copy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "knowledge" / "cases"
SPEC = Path(__file__).resolve().parent / "cases_spec.py"


def norm(v):
    return "yes" if v is True else "no" if v is False else v


def load(name):
    return yaml.safe_load((CASES / name).read_text(encoding="utf-8"))


def golden_facts() -> list[tuple[str, dict, dict]]:
    table = load("decision_table.yaml")
    trs = {t["id"]: t for t in table["test_requirements"]}
    out = []
    for c in load("golden.yaml")["cases"]:
        tr = trs[c["tr"]]
        facts = copy.deepcopy(table["baselines"][tr["base"]])
        for k, v in tr["changes"].items():
            facts[k] = {**facts.get(k, {}), **v} if isinstance(v, dict) else v
        out.append((c["id"], facts, c["expected"]))
    return out


def key(r: dict) -> tuple:
    return (r["outcome"], r.get("code") or None, tuple(sorted(r.get("flags") or [])))


# ---- 커버리지 ------------------------------------------------------------------------------


def coverage(cases, model, table) -> dict:
    trs = {t["id"]: t for t in table["test_requirements"]}
    golden = load("golden.yaml")["cases"]
    gates = {trs[c["tr"]]["gate"] for c in golden}
    outcomes = {c["expected"]["outcome"] for c in golden}
    parts_total, parts_hit, missing = 0, 0, []
    for var in model["variables"]:
        for p in var.get("partitions", []):
            if "values" not in p:
                continue
            parts_total += 1
            vals = {norm(x) for x in p["values"]}
            hit = False
            for _, f, _ in cases:
                v = f.get(var["id"])
                if var["id"] == "input_form" and v is not None:
                    hit |= v in vals or f"{f.get('material')}:{v}" in vals
                else:
                    hit |= v in vals
            parts_hit += hit
            if not hit:
                missing.append(f"{var['id']}={sorted(vals)}")
    # 값 단위(도메인 원소) 커버리지: 동등 분할상 대표값 하나면 충분하지만 참고로 잰다
    values_total, values_hit, values_missing = 0, 0, []
    for var in model["variables"]:
        dom = var.get("domain")
        if not isinstance(dom, list):
            continue
        for d in dom:
            values_total += 1
            if any(f.get(var["id"]) == norm(d) for _, f, _ in cases):
                values_hit += 1
            else:
                values_missing.append(f"{var['id']}={norm(d)}")
    bounds = {"daily_avg_kg": [299, 300], "oil_pct_evidenced": [4.9, 5.0]}
    b_total = sum(len(v) for v in bounds.values())
    b_hit = sum(any(f.get(k) == x for _, f, _ in cases) for k, xs in bounds.items() for x in xs)
    all_outcomes = [o["id"] for o in model["outcomes"]]
    return {
        "partition": {"covered": parts_hit, "total": parts_total, "missing": missing},
        "domain_value": {"covered": values_hit, "total": values_total, "missing": values_missing},
        "boundary": {"covered": b_hit, "total": b_total},
        "gate": {
            "covered": len(gates),
            "total": 8,
            "missing": sorted({f"G{i}" for i in range(1, 9)} - gates),
        },
        "outcome": {
            "covered": len(outcomes),
            "total": len(all_outcomes),
            "missing": [o for o in all_outcomes if o not in outcomes],
        },
    }


# ---- 뮤테이션 -------------------------------------------------------------------------------

ROR = {
    ast.GtE: [ast.Gt, ast.LtE],
    ast.Gt: [ast.GtE],
    ast.LtE: [ast.Lt],
    ast.Lt: [ast.LtE],
    ast.Eq: [ast.NotEq],
    ast.NotEq: [ast.Eq],
    ast.In: [ast.NotIn],
    ast.NotIn: [ast.In],
}


def mutation_points(tree: ast.Module) -> list[tuple[str, int, int, str]]:
    """(종류, 노드 순번, 변형 번호, 설명) 목록."""
    points = []
    for i, node in enumerate(ast.walk(tree)):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Compare):
            for j, op in enumerate(node.ops):
                for k, alt in enumerate(ROR.get(type(op), [])):
                    points.append(
                        ("ROR", i, j * 10 + k, f"L{line} {type(op).__name__}→{alt.__name__}")
                    )
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int | float)
            and not isinstance(node.value, bool)
        ):
            for k, d in enumerate((-1, 1)):
                points.append(("CRP", i, k, f"L{line} {node.value}→{node.value + d}"))
        elif isinstance(node, ast.If):
            for k, v in enumerate((True, False)):
                points.append(("BRD", i, k, f"L{line} if-조건→{v}"))
        elif isinstance(node, ast.BoolOp):
            points.append(("BOR", i, 0, f"L{line} {type(node.op).__name__} 교체"))
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Set | ast.Tuple):
            name = stmt.targets[0].id
            for k, elt in enumerate(stmt.value.elts):
                points.append(("SER", id(stmt), k, f"{name}에서 {ast.literal_eval(elt)!r} 제거"))
    return points


def apply_mutation(tree: ast.Module, point) -> ast.Module:
    kind, idx, var, _ = point
    t = copy.deepcopy(tree)
    if kind == "SER":
        stmts = [s for s in tree.body if id(s) == idx]
        pos = tree.body.index(stmts[0])
        del t.body[pos].value.elts[var]
        return t
    node = list(ast.walk(t))[idx]
    if kind == "ROR":
        j, k = divmod(var, 10)
        node.ops[j] = ROR[type(node.ops[j])][k]()
    elif kind == "CRP":
        node.value = node.value + (-1 if var == 0 else 1)
    elif kind == "BRD":
        node.test = ast.Constant(value=(var == 0))
    elif kind == "BOR":
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    return t


def run(tree: ast.Module, cases) -> list[str]:
    ns: dict = {"__name__": "mutant"}
    try:
        exec(compile(ast.fix_missing_locations(tree), "mutant", "exec"), ns)
    except Exception as e:  # 컴파일 단계에서 깨진 변형도 '잡힘'으로 본다
        return [f"compile:{type(e).__name__}"]
    failed = []
    for cid, facts, exp in cases:
        try:
            got = ns["evaluate"](copy.deepcopy(facts))
        except Exception:
            failed.append(cid)
            continue
        if key(got) != key(exp):
            failed.append(cid)
    return failed


def mutation(cases) -> dict:
    src = SPEC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    base_fail = run(tree, cases)
    if base_fail:
        sys.exit(f"원본 명세 오라클이 골든셋과 다름: {base_fail}")
    points = mutation_points(tree)
    killed, survivors = 0, []
    by_kind: dict[str, list[int]] = {}
    for p in points:
        failed = run(apply_mutation(tree, p), cases)
        ok = bool(failed)
        killed += ok
        by_kind.setdefault(p[0], [0, 0])
        by_kind[p[0]][0] += ok
        by_kind[p[0]][1] += 1
        if not ok:
            survivors.append(f"{p[0]} {p[3]}")
    return {
        "mutants": len(points),
        "killed": killed,
        "score": round(killed / len(points), 4),
        "by_operator": {k: {"killed": v[0], "total": v[1]} for k, v in sorted(by_kind.items())},
        "survivors": survivors,
    }


def main() -> None:
    cases = golden_facts()
    model = load("input_model.yaml")
    table = load("decision_table.yaml")
    report = {
        "golden_cases": len(cases),
        "coverage": coverage(cases, model, table),
        "mutation": mutation(cases),
    }
    text = yaml.safe_dump(report, allow_unicode=True, sort_keys=False, width=100)
    (CASES / "evaluation.yaml").write_text(
        "# 자동 생성: tools/evaluate_golden.py — 골든셋 품질 평가(커버리지·뮤테이션)\n" + text,
        encoding="utf-8",
        newline="\n",
    )
    print(text)


if __name__ == "__main__":
    main()
