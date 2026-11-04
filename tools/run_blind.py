"""블라인드 시험: 실행 전에 가정을 고정한 파일(testdata/blind/batchN.yaml)로 계산기를 돌려 기관 답과 비교한다.

규칙: 결과를 본 뒤 그 회차 파일의 가정은 바꾸지 않는다. 실행 시 파일의 SHA-256을 결과에 남긴다.
틀린 결과가 나와도 그 회차에서는 규칙을 고치지 않고 기록만 한다.
실행: python tools/run_blind.py testdata/blind/batch1.yaml
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wastecalc import evaluate, load_kb  # noqa: E402

KB = load_kb()


def judge(expected: dict, facts: dict) -> list[tuple[str, str, str, str]]:
    r = evaluate(facts, strict=False, kb=KB)
    got = {d["stage"]: d for d in r["decided"]}
    ref = None
    if r.get("reason") == "INTERPRETATION_NEEDED":
        ref = {d["stage"]: d for d in evaluate(facts, strict=False, kb=KB, allow_interpretive=True)["decided"]}
    rows = []
    for stage, want in expected.items():
        want_c = want["conclusion"] if isinstance(want, dict) else want
        d = got.get(stage)
        if d is None:
            if ref and stage in ref:
                same = ref[stage]["conclusion"] == want_c
                rows.append((stage, str(want), f"문의 안내 (참고 결론 {ref[stage]['conclusion']})",
                             "CONSULT(참고 일치)" if same else "CONSULT(참고 불일치)"))
            else:
                nq = (r.get("next_question") or {}).get("fact")
                rows.append((stage, str(want), f"{r['status']} at {r.get('stage')}" + (f", 다음 질문 {nq}" if nq else ""),
                             "STOPPED"))
            continue
        verdict = "CORRECT" if d["conclusion"] == want_c else "WRONG"
        detail = d["conclusion"]
        if verdict == "CORRECT" and isinstance(want, dict) and want.get("allowed_types"):
            mine = {a["r_code"] for a in d.get("allowed_types", [])}
            missing = set(want["allowed_types"]) - mine
            if missing:
                verdict, detail = "WRONG", f"기관 R코드 {sorted(missing)}가 계산기 목록에 없음"
            else:
                detail = f"{detail} (기관 R코드 {len(want['allowed_types'])}개 모두 포함)"
        rows.append((stage, str(want_c), detail, verdict))
    return rows


def main(path: str) -> None:
    p = Path(path)
    raw = p.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    doc = yaml.safe_load(raw.decode("utf-8"))
    common = doc.get("common", {})
    out = [f"# 블라인드 시험 결과 — {p.name}", "",
           f"가정 파일 SHA-256 `{sha}` (실행 시점). 기준일 {KB.as_of}, 규칙 DB `{KB.version}`, strict 해제.", "",
           "| 사례 | 상황 | 입력 | 단계 | 기관 답 | 계산기 | 판정 |", "|---|---|---|---|---|---|---|"]
    tally: dict[str, int] = {}
    for c in doc["cases"]:
        runs = [("기본: " + c["assumed"], {**common, **c["facts"]})]
        if c.get("variant"):
            runs.append(("변형: " + c.get("variant_note", json.dumps(c["variant"], ensure_ascii=False)),
                         {**common, **c["facts"], **c["variant"]}))
        for label, facts in runs:
            for stage, want, got, verdict in judge(c["expected"], facts):
                key = verdict + ("(변형)" if label.startswith("변형") else "")
                tally[key] = tally.get(key, 0) + 1
                out.append(f"| {c['id']} | {c['title']} | {label} | {stage} | {want} | {got} | **{verdict}** |")
    out += ["", "합계: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items()))]
    dest = p.with_name(p.stem + "_result.md")
    dest.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1])
