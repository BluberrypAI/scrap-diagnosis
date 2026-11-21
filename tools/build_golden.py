"""골든 데이터셋 Step 6: 최종 golden.yaml 생성과 동결(freeze).

    uv run python tools/build_golden.py           # golden.yaml + golden.lock 생성
    uv run python tools/build_golden.py --check   # 동결 해시가 맞는지(변경 감지)

situations.yaml(상황) + decision_table.yaml(기대 결과) + input_model.yaml(근거·등급)을 합친다.
external/candidates.yaml에서 support·include로 고른 판례·해석은 케이스의 external에 단다.
동결 뒤 golden.yaml을 바꾸려면 knowledge/cases/CHANGELOG.md에 사유를 적고 다시 생성한다.
판정 규칙을 작성하는 쪽(사람·LLM)에는 이 파일을 보여 주지 않는다(데이터 누수 방지).
"""

from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "knowledge" / "cases"
GOLDEN = CASES / "golden.yaml"
LOCK = CASES / "golden.lock"
EXTERNAL = CASES / "external" / "candidates.yaml"


def load(name: str):
    return yaml.safe_load((CASES / name).read_text(encoding="utf-8"))


def norm(v):
    """YAML 1.1은 yes/no를 불리언으로 읽는다. 사실값(문자열)과 비교하려고 되돌린다."""
    if v is True:
        return "yes"
    if v is False:
        return "no"
    return v


def partition_for(var: dict, value) -> dict | None:
    for p in var.get("partitions", []):
        if "values" in p and norm(value) in [norm(x) for x in p["values"]]:
            return p
    return None


def facts_of(tr: dict, baselines: dict) -> dict:
    facts = copy.deepcopy(baselines[tr["base"]])
    for k, v in tr["changes"].items():
        if k == "can_designation" and isinstance(v, dict):
            facts[k] = {**facts.get(k, {}), **v}
        else:
            facts[k] = v
    return facts


def external_key(c: dict) -> str:
    """외부 레이블 참조 키: "target/사건번호"(사건번호가 없으면 일련번호)."""
    return f"{c['target']}/{c.get('case_no') or c['id']}"


def external_by_tr() -> dict[str, list[str]]:
    """screening에서 support·include로 고른 항목을 TR별로 모은다."""
    out: dict[str, list[str]] = {}
    for c in yaml.safe_load(EXTERNAL.read_text(encoding="utf-8"))["candidates"]:
        s = c.get("screening") or {}
        if s.get("decision") in ("support", "include"):
            for tr in s.get("for", []):
                out.setdefault(tr, []).append(external_key(c))
    return out


def basis_and_grade(tr: dict, facts: dict, model: dict) -> tuple[list[str], str, list[str]]:
    variables = {v["id"]: v for v in model["variables"]}
    outcomes = {o["id"]: o for o in model["outcomes"]}
    groups = model.get("group_rules", {})
    basis: list[str] = list(outcomes[tr["expected"]["outcome"]].get("basis", []))
    grades: list[str] = []
    external: list[str] = []
    keys = set(tr["changes"])
    if tr["kind"] == "baseline":
        keys |= {"material", "packaging_used", "can_contents", "can_metal"}
    for key in sorted(keys):
        var = variables.get(key)
        if var is None:
            continue
        value = facts.get(key)
        p = partition_for(var, value) if not isinstance(value, dict) else None
        if p:
            basis += p.get("basis", [])
            external += p.get("external", [])
            grades.append(p.get("grade", "A"))
        else:
            basis += var.get("basis", [])
            for sub in var.get("sub_conditions", []):
                basis += sub.get("basis", [])
            group = next((g for g in groups.values() if key in g["variables"]), None)
            grades.append((group or var).get("grade", "A"))
    code = tr["expected"]["code"]
    if code and f"RULE-WASTE/별표4/{code}" not in basis:
        basis.append(f"RULE-WASTE/별표4/{code}")
    # 가장 약한 근거가 케이스 등급이 된다: C(우리 해석) > B(판례·공식 해석) > A(조문 문언)
    grade = next((g for g in ("C", "B") if g in grades), "A")
    return list(dict.fromkeys(basis)), grade, external


def build() -> str:
    model = load("input_model.yaml")
    table = load("decision_table.yaml")
    trs = {t["id"]: t for t in table["test_requirements"]}
    support = external_by_tr()
    cases = []
    for s in load("situations.yaml")["cases"]:
        tr = trs[s["tr"]]
        facts = facts_of(tr, table["baselines"])
        basis, grade, external = basis_and_grade(tr, facts, model)
        case = {
            "id": s["id"],
            "tr": s["tr"],
            "kind": tr["kind"],
            "covers": tr["covers"],
            "situation": " ".join(s["situation"].split()),
            "expected": tr["expected"],
            "basis": basis,
            "grade": grade,
            "source": "명세 기반 생성(Annotator A) · 블라인드 검증(Annotator B)",
        }
        external = list(dict.fromkeys(external + support.get(s["tr"], [])))
        if external:
            case["external"] = external
        cases.append(case)
    if len({c["tr"] for c in cases}) != len(trs):
        sys.exit("모든 TR에 상황 서술이 하나씩 있어야 합니다.")
    doc = {"version": 5, "frozen_on": "2026-11-21", "n": len(cases), "cases": cases}
    header = (
        "# 골든 데이터셋 (동결본). 자동 생성: tools/build_golden.py — 직접 고치지 않는다.\n"
        "# 판정 규칙 작성자(사람·LLM)에게 보여 주지 않는다. 변경은 CHANGELOG.md에 사유를 남긴다.\n"
    )
    return header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100)


def main() -> None:
    text = build()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if "--check" in sys.argv:
        locked = LOCK.read_text(encoding="utf-8").split()[0] if LOCK.exists() else ""
        current = GOLDEN.read_text(encoding="utf-8") if GOLDEN.exists() else ""
        if current != text or locked != digest:
            sys.exit(
                "골든셋이 동결본과 다릅니다. 의도한 변경이면 CHANGELOG.md에 적고 다시 생성하세요."
            )
        print(f"골든셋 동결 확인: {digest[:12]}")
        return
    GOLDEN.write_text(text, encoding="utf-8", newline="\n")
    LOCK.write_text(f"{digest}  golden.yaml\n", encoding="utf-8", newline="\n")
    print(f"생성: golden.yaml ({digest[:12]})")


if __name__ == "__main__":
    main()
