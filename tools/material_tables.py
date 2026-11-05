"""소재별 판정표 생성기.

소재마다 엔진이 묻는 질문의 모든 답 조합을 엔진에 넣어 보고 "답 → 지정 여부 → 분류번호 → 재활용" 표를 만든다.
판정은 엔진(공통 규칙)이 하고, 이 도구는 펼쳐서 보여 주기만 한다.

쓰임
  - 법률 검토: 규칙 전체 대신 소재별 표 한 장씩 확인한다(docs/material-tables/<소재>.md).
  - 회귀 테스트: tests/data/material_tables.json(기대값)과 다르면 tests/test_material_tables.py가 실패한다.
    규칙·카탈로그를 의도적으로 바꿨으면 이 도구를 --update로 다시 돌려 기대값을 갱신하고, 바뀐 칸을 검토한다.

전제(표마다 머리에 적음)
  - 폐기물로 내보내고(material_fate=released), 관문 질문 '해당 없음', 배출시설 있는 사업장(사업장폐기물)이다.
  - 숫자 질문은 그 질문이 가르는 기준값마다 '바로 아래 / 바로 위'를 넣는다(기준값과 같을 때의 이상·초과 구분은
    경계값 테스트가 따로 본다).
  - '모름'은 펼치지 않는다(모름의 처리는 공통 규칙 테스트가 따로 본다).
  - 공통 오염 확인(잔류물·기름·PCB·유해화학물질)은 '모두 아니오' + 한 번에 하나만 '예'로 펼친다.
  - 해석 자료(질의회신)만 근거인 결론은 엔진 기본값대로 '기관 확인'으로 멈춘 것으로 적는다.

실행
  python tools/material_tables.py            표 파일 생성 + 요약 출력
  python tools/material_tables.py --update   기대값(tests/data/material_tables.json)도 갱신
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wastecalc.engine import evaluate, value_text, parse_answer  # noqa: E402
from wastecalc.kb import load_kb  # noqa: E402

BASE = {"material_fate": "released", "circular_resource_recognized": False, "law_exclusion": "none",
        "emission_facility": True}
STOP_FACTS = {"code", "general_group", "no_specific_code_applies"}
# 소재와 무관한 공통 오염 확인. 소재 표에서는 '모두 아니오'를 기본으로 두고 한 번에 하나만 '예'로 바꿔 본다
# (두 개 이상 겹치는 경우는 소재와 무관한 공통 규칙의 문제라 공통 테스트에서 본다).
COMMON = {"designated_residue": False, "oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": False}
MAX_LEAVES = 1500
MAX_DEPTH = 30
EXPECTED = ROOT / "tests" / "data" / "material_tables.json"
OUT_DIR = ROOT / "docs" / "material-tables"


def _num_values(r: dict, fact: str) -> list[float]:
    card = next((c for c in r.get("resolution") or [] if c["fact"] == fact), None)
    ths = sorted({float(t["value"]) for t in (card or {}).get("thresholds", [])})
    if not ths:
        return [0.0]
    vals: set[float] = set()
    for t in ths:
        d = max(abs(t) * 0.02, 0.001)
        vals.update({round(max(0.0, t - d), 6), round(t + d, 6)})
    return sorted(vals)


def _branch_values(kb, r: dict, nq: dict) -> list:
    f = kb.facts[nq["fact"]]
    if f["type"] == "bool":
        return [False, True]
    if f["type"] == "enum":
        return list(nq.get("allowed_values") or f["values"])
    return _num_values(r, nq["fact"])


def _designated_groups(kb, d3: dict) -> list[str]:
    m = kb.s4_map["designated"]
    groups = []
    for b in d3.get("basis", []):
        keys = [k for k in m if b["rule_id"].startswith(k)]
        if keys:
            groups.append("/".join(m[max(keys, key=len)]))
    return sorted(set(groups))


def _row(kb, path: dict, r: dict) -> dict:
    dec = {d["stage"]: d for d in r["decided"]}
    nq = r.get("next_question") or {}
    flags = []
    if "S4" in dec:
        result = dec["S4"]["conclusion"]
    elif nq.get("fact") in STOP_FACTS:
        n = len(nq.get("allowed_values") or {})
        result = f"번호 선택 필요({n}개)"
        flags.append("CODE_CHOICE")
    elif r["status"] == "NEED_EXPERT":
        result = f"기관 확인({r.get('reason') or ''})"
        flags.append("STOP")
    elif r["status"] == "NEED_TEST":
        result = f"시험 필요({r.get('reason') or nq.get('fact') or ''})"
        flags.append("STOP")
    else:
        result = f"{r['status']}({r.get('reason') or nq.get('fact') or ''})"
        flags.append("STOP")
    s3 = dec.get("S3")
    groups = _designated_groups(kb, s3) if s3 and s3["conclusion"] == "DESIGNATED" else []
    if len(groups) > 1:
        flags.append("MULTI_REASON")  # 지정 사유가 여러 개 — 번호가 한쪽으로 좁혀졌는지 검토
    s5 = dec.get("S5")
    return {
        "answers": {k: v for k, v in path.items()},
        "designated": None if not s3 else s3["conclusion"],
        "designated_by": [b["rule_id"] for b in s3["basis"]] if s3 and s3["conclusion"] == "DESIGNATED" else [],
        "result": result,
        "recycling": None if not s5 else s5["conclusion"],
        "status": r["status"],
        "flags": flags,
    }


def material_table(kb, mid: str) -> dict:
    rows, stack, truncated = [], [{}], False
    while stack:
        path = stack.pop()
        r = evaluate({**BASE, "material": mid, **path}, strict=False, kb=kb)
        nq = r.get("next_question")
        decided = {d["stage"] for d in r["decided"]}
        if not nq or "S4" in decided or nq["fact"] in STOP_FACTS or len(path) >= MAX_DEPTH:
            rows.append(_row(kb, path, r))
            continue
        values = _branch_values(kb, r, nq)
        if nq["fact"] in COMMON and any(path.get(f, COMMON[f]) != COMMON[f] for f in COMMON):
            values = [COMMON[nq["fact"]]]  # 이미 다른 오염 항목 하나를 '예'로 바꾼 경로
        for v in reversed(values):
            stack.append({**path, nq["fact"]: v})
        if len(rows) + len(stack) > MAX_LEAVES:
            truncated = True
            break
    return {"material": mid, "rows": rows, "truncated": truncated}


def all_tables(kb) -> dict:
    return {mid: material_table(kb, mid) for mid, m in kb.materials["materials"].items() if not m.get("unlisted")}


# ---------------------------------------------------------------- 출력

def _ans_text(kb, f, v) -> str:
    try:
        return f"{kb.facts[f].get('label', f)}={value_text(kb, f, parse_answer(kb, f, v))}"
    except Exception:  # noqa: BLE001
        return f"{f}={v}"


def _md(kb, t: dict) -> str:
    m = kb.materials["materials"][t["material"]]
    names = {c["id"]: c["name"] for c in kb.annex4["codes"]}
    L = [f"# {m['label']} (`{t['material']}`)", "",
         "전제: 폐기물로 내보냄 · 관문 질문 해당 없음 · 배출시설 있는 사업장 · 오염 확인은 한 번에 하나만 '예'. 숫자는 기준값 바로 아래/위. 규칙·카탈로그 모두 검토 전(UNVERIFIED).",
         "", f"카탈로그 번호 후보: {json.dumps(m.get('codes') or {}, ensure_ascii=False)}", ""]
    if t["truncated"]:
        L += ["> 경우의 수가 많아 일부만 펼쳤습니다.", ""]
    L += ["| # | 답 | 지정 여부 | 결과 | 재활용 | 표시 | 검토 |", "|---|---|---|---|---|---|---|"]
    for i, row in enumerate(t["rows"], 1):
        ans = " · ".join(_ans_text(kb, f, v) for f, v in row["answers"].items()) or "(추가 질문 없음)"
        res = row["result"]
        if res in names:
            res = f"{res} {names[res][:30]}"
        des = {"DESIGNATED": "지정", "NOT_DESIGNATED": "지정 아님", None: "-"}.get(row["designated"], row["designated"])
        L.append(f"| {i} | {ans} | {des} | {res} | {row['recycling'] or '-'} | {' '.join(row['flags'])} | ☐ |")
    return "\n".join(L) + "\n"


def summarize(kb, tables: dict) -> tuple[str, dict]:
    stats = {"materials": len(tables), "rows": 0, "code_choice": [], "multi_reason": [], "stop": 0, "truncated": []}
    for mid, t in tables.items():
        stats["rows"] += len(t["rows"])
        if t["truncated"]:
            stats["truncated"].append(mid)
        for row in t["rows"]:
            if "CODE_CHOICE" in row["flags"]:
                stats["code_choice"].append(mid)
            if "MULTI_REASON" in row["flags"]:
                stats["multi_reason"].append(mid)
            if "STOP" in row["flags"]:
                stats["stop"] += 1
    stats["code_choice"] = sorted(set(stats["code_choice"]))
    stats["multi_reason"] = sorted(set(stats["multi_reason"]))
    L = ["# 소재별 판정표 — 목록", "",
         "`tools/material_tables.py`가 엔진으로 만든 표입니다. 표마다 끝의 '검토' 칸에 확인 표시를 합니다.", "",
         f"- 소재 {stats['materials']}종, 행 {stats['rows']}개, 멈춤(시험·기관 확인 등) {stats['stop']}행",
         f"- 번호를 목록에서 골라야 하는 소재: {', '.join(stats['code_choice']) or '없음'}",
         f"- 지정 사유가 여러 개인 행이 있는 소재(번호가 한쪽으로 좁혀졌는지 검토): {', '.join(stats['multi_reason']) or '없음'}",
         f"- 일부만 펼친 소재: {', '.join(stats['truncated']) or '없음'}", "",
         "| 묶음 | 소재 | 행 | 번호 선택 | 사유 여럿 |", "|---|---|---|---|---|"]
    groups = kb.materials.get("groups", {})
    for mid, t in tables.items():
        m = kb.materials["materials"][mid]
        L.append(f"| {groups.get(m['group'], {}).get('label', m['group'])} | [{m['label']}]({mid}.md) | {len(t['rows'])} | "
                 f"{'예' if mid in stats['code_choice'] else ''} | {'예' if mid in stats['multi_reason'] else ''} |")
    return "\n".join(L) + "\n", stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="기대값 파일도 갱신")
    args = ap.parse_args()
    kb = load_kb()
    kb = kb.at(kb.as_of)
    tables = all_tables(kb)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for mid, t in tables.items():
        (OUT_DIR / f"{mid}.md").write_text(_md(kb, t), encoding="utf-8")
    index, stats = summarize(kb, tables)
    (OUT_DIR / "README.md").write_text(index, encoding="utf-8")
    if args.update:
        EXPECTED.parent.mkdir(parents=True, exist_ok=True)
        EXPECTED.write_text(json.dumps({"as_of": kb.as_of, "tables": tables}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items()}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
