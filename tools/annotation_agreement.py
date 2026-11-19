"""골든 데이터셋 Step 5: 블라인드 재라벨링과 평가자 간 일치도.

    uv run python tools/annotation_agreement.py blind   # annotation/blind.yaml 생성(기대 결과 숨김)
    uv run python tools/annotation_agreement.py score   # annotator_b.yaml과 기대 결과 비교

score는 출력 클래스 기준 Cohen's κ, (클래스·코드·플래그) 완전 일치율을 내고,
불일치 건을 annotation/disagreements.yaml로 쓴다. 불일치는 사람이 판정 조정(adjudication)한다.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "knowledge" / "cases"
ANN = CASES / "annotation"


def load(p: Path):
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def dump(p: Path, header: str, data) -> None:
    p.write_text(
        header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
        newline="\n",
    )


def expected_by_case() -> dict[str, dict]:
    trs = {t["id"]: t for t in load(CASES / "decision_table.yaml")["test_requirements"]}
    out = {}
    for c in load(CASES / "situations.yaml")["cases"]:
        out[c["id"]] = {**trs[c["tr"]]["expected"], "tr": c["tr"], "situation": c["situation"]}
    return out


def blind() -> None:
    cases = load(CASES / "situations.yaml")["cases"]
    data = {"cases": [{"id": c["id"], "situation": c["situation"]} for c in cases]}
    dump(ANN / "blind.yaml", "# Annotator B 입력: 상황 서술만 담는다(기대 결과·TR 없음).\n", data)
    print(f"blind.yaml: {len(cases)}건")


def cohen_kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def norm(x: dict) -> tuple:
    return (x.get("outcome"), x.get("code") or None, tuple(sorted(x.get("flags") or [])))


def score() -> None:
    exp = expected_by_case()
    labels = {x["id"]: x for x in load(ANN / "annotator_b.yaml")["labels"]}
    missing = sorted(set(exp) - set(labels))
    if missing:
        sys.exit(f"annotator_b에 없는 케이스: {missing}")
    ids = sorted(exp)
    a = [exp[i]["outcome"] for i in ids]
    b = [labels[i]["outcome"] for i in ids]
    kappa = cohen_kappa(a, b)
    exact = sum(norm(exp[i]) == norm(labels[i]) for i in ids)
    outcome_agree = sum(x == y for x, y in zip(a, b, strict=True))
    dis = []
    for i in ids:
        if norm(exp[i]) != norm(labels[i]):
            e, l_ = exp[i], labels[i]
            dis.append(
                {
                    "id": i,
                    "tr": e["tr"],
                    "situation": e["situation"],
                    "expected": {"outcome": e["outcome"], "code": e["code"], "flags": e["flags"]},
                    "annotator_b": {
                        "outcome": l_["outcome"],
                        "code": l_.get("code"),
                        "flags": l_.get("flags") or [],
                        "rationale": l_.get("rationale"),
                    },
                    "adjudication": None,
                }
            )
    report = {
        "n": len(ids),
        "outcome_agreement": round(outcome_agree / len(ids), 4),
        "cohen_kappa_outcome": round(kappa, 4),
        "exact_agreement": round(exact / len(ids), 4),
        "disagreements": len(dis),
    }
    dump(
        ANN / "disagreements.yaml",
        "# 자동 생성: tools/annotation_agreement.py score\n"
        "# adjudication에 판정 조정 결과를 적는다:\n"
        "#   expected | annotator_b | rewrite(서술 고침) | spec(명세 고침)\n",
        {"report": report, "items": dis},
    )
    print(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))


if __name__ == "__main__":
    {"blind": blind, "score": score}[sys.argv[1]]()
