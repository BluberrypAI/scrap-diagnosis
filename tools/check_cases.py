"""골든 데이터셋 검사: knowledge/cases/*.yaml이 적재한 조문과 맞는지 확인한다.

    uv run python tools/check_cases.py

- 근거(basis) 참조 무결성: "문서키/단위ID"가 knowledge/law/articles에 실제로 있는지
- 입력 모델: 파티션 값이 도메인 안에 있는지, 효과(effect)가 출력 클래스나 continue인지
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LAW = ROOT / "knowledge" / "law" / "articles"
CASES = ROOT / "knowledge" / "cases"


def load_units() -> set[str]:
    units = set()
    for f in LAW.glob("*.json"):
        doc = json.loads(f.read_text(encoding="utf-8"))
        units |= {f"{doc['key']}/{u['id']}" for u in doc["units"]}
    return units


def walk_basis(node, path: str = ""):
    """중첩 구조에서 basis 목록을 모두 찾는다."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "basis" and isinstance(v, list):
                for b in v:
                    yield path, b
            else:
                yield from walk_basis(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            label = v.get("id", i) if isinstance(v, dict) else i
            yield from walk_basis(v, f"{path}[{label}]")


def check_basis(doc, units: set[str], errors: list[str], name: str) -> int:
    n = 0
    for where, ref in walk_basis(doc):
        n += 1
        if ref not in units:
            errors.append(f"{name}: {where}: 적재되지 않은 근거 {ref!r}")
    return n


def sv(v) -> str:
    """YAML 1.1은 yes/no를 불리언으로 읽는다. 문자열 사실값과 같은 표기로 맞춘다."""
    if v is True:
        return "yes"
    if v is False:
        return "no"
    return str(v)


def flat_domain(domain) -> set[str] | None:
    if isinstance(domain, list):
        return {sv(v) for v in domain}
    if isinstance(domain, dict) and "type" not in domain:
        vals = set()
        for key, vs in domain.items():
            vals |= {sv(v) for v in vs} | {f"{key}:{sv(v)}" for v in vs}
        return vals
    return None  # 수치형


def check_input_model(model: dict, errors: list[str]) -> None:
    outcomes = {o["id"] for o in model["outcomes"]}
    precedences = [o["precedence"] for o in model["outcomes"]]
    if len(set(precedences)) != len(precedences):
        errors.append("input_model: 출력 클래스 precedence가 겹침")
    ids = [v["id"] for v in model["variables"]]
    if len(set(ids)) != len(ids):
        errors.append("input_model: 변수 id가 겹침")
    for v in model["variables"]:
        domain = flat_domain(v.get("domain"))
        for p in v.get("partitions", []):
            if domain is not None and "values" in p:
                bad = [x for x in p["values"] if sv(x) not in domain]
                if bad:
                    errors.append(f"input_model: {v['id']} 파티션 값이 도메인 밖 {bad}")
            effect = str(p.get("effect", ""))
            head = effect.split()[0] if effect else ""
            if head.isupper() and head not in outcomes:
                errors.append(f"input_model: {v['id']} 알 수 없는 출력 클래스 {head}")
        if (
            domain is not None
            and v.get("partitions")
            and all("values" in p for p in v["partitions"])
        ):
            covered = {sv(x) for p in v["partitions"] for x in p["values"]}
            plain = {d for d in domain if ":" not in d}
            if isinstance(v.get("domain"), list) and plain - covered:
                errors.append(
                    f"input_model: {v['id']} 파티션이 덮지 않는 값 {sorted(plain - covered)}"
                )
    for name, rule in model.get("group_rules", {}).items():
        for var in rule["variables"]:
            if var not in ids:
                errors.append(f"input_model: group_rules.{name}에 없는 변수 {var}")


def check_table_facts(model: dict, table: dict, errors: list[str]) -> int:
    """결정 테이블의 사실값이 입력 모델 도메인 안에 있는지(오타·표기 불일치 방지)."""
    variables = {v["id"]: v for v in model["variables"]}
    sub = {s["id"] for v in model["variables"] for s in v.get("sub_conditions", [])}
    n = 0
    rows = [("baseline:" + k, b) for k, b in table["baselines"].items()]
    rows += [(t["id"], t["changes"]) for t in table["test_requirements"]]
    for where, facts in rows:
        for key, value in facts.items():
            n += 1
            var = variables.get(key)
            if var is None:
                errors.append(f"decision_table: {where}: 입력 모델에 없는 변수 {key}")
                continue
            if isinstance(value, dict):
                bad = [k for k in value if k not in sub]
                if bad:
                    errors.append(f"decision_table: {where}: {key}의 알 수 없는 하위 조건 {bad}")
                continue
            domain = flat_domain(var.get("domain"))
            if value is None or domain is None:
                continue
            if sv(value) not in domain:
                errors.append(f"decision_table: {where}: {key}={value!r}가 도메인 밖")
    return n


def main() -> None:
    units = load_units()
    errors: list[str] = []
    model = yaml.safe_load((CASES / "input_model.yaml").read_text(encoding="utf-8"))
    n = check_basis(model, units, errors, "input_model")
    check_input_model(model, errors)
    print(
        f"input_model: 변수 {len(model['variables'])}개, 출력 클래스 {len(model['outcomes'])}개, "
        f"근거 참조 {n}개 (적재 단위 {len(units)}개)"
    )
    table = yaml.safe_load((CASES / "decision_table.yaml").read_text(encoding="utf-8"))
    nf = check_table_facts(model, table, errors)
    print(f"decision_table: TR {len(table['test_requirements'])}개, 사실값 {nf}개")
    golden_path = CASES / "golden.yaml"
    if golden_path.exists():
        golden = yaml.safe_load(golden_path.read_text(encoding="utf-8"))
        ng = check_basis(golden, units, errors, "golden")
        print(f"golden: 케이스 {golden['n']}개, 근거 참조 {ng}개")
    if errors:
        print("\n".join(f"  ✗ {e}" for e in errors))
        sys.exit(1)
    print("  ✓ 통과")


if __name__ == "__main__":
    main()
