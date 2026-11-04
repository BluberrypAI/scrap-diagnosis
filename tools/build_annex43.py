"""시행규칙 별표 4의3(폐기물의 종류별 재활용 가능 유형)을 표로 옮긴다. 결과: rules/annex43.yaml

이 PDF는 텍스트 층이 겹쳐 있어 일반 추출로는 글자가 섞인다. 그래서 표의 괘선 좌표로 칸을 나눈다.
- 표 전체 폭의 가로선 = 행 경계, '재활용 유형' 열부터 시작하는 가로선 = 한 번호 안의 칸 경계
- 열: 분류번호 | 폐기물의 종류 | 재활용 유형 | 사전 분석·확인 필요 여부
실행: python tools/build_annex43.py
"""
import re
from pathlib import Path

import fitz
import yaml

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "sources" / "raw" / "170401353.pdf"
OUT = ROOT / "rules" / "annex43.yaml"
ID = re.compile(r"^\d{2}(?:-\d{2}){0,2}$")
RCODE = re.compile(r"R-\d+(?:-\d+)?")


def lines(page):
    hs, vs = [], []
    for dr in page.get_drawings():
        for it in dr["items"]:
            if it[0] == "l":
                p, q = it[1], it[2]
                if abs(p.y - q.y) < 0.5:
                    hs.append((p.y, min(p.x, q.x), max(p.x, q.x)))
                elif abs(p.x - q.x) < 0.5:
                    vs.append((p.x, min(p.y, q.y), max(p.y, q.y)))
            elif it[0] == "re":
                r = it[1]
                if r.height < 1.5:
                    hs.append((r.y0, r.x0, r.x1))
                elif r.width < 1.5:
                    vs.append((r.x0, r.y0, r.y1))
    return hs, vs


def cluster(values, tol=5.0):
    groups = []
    for v in values:
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return groups


def spans(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                t = s["text"].strip()
                if t:
                    x0, y0, x1, y1 = s["bbox"]
                    out.append(((x0 + x1) / 2, (y0 + y1) / 2, x0, t))
    return out


def text_in(sp, x0, x1, y0, y1):
    sel = sorted([s for s in sp if x0 <= s[0] < x1 and y0 <= s[1] < y1], key=lambda s: (round(s[1]), s[2]))
    return " ".join(s[3] for s in sel).strip()


def main():
    doc = fitz.open(PDF)
    rows = []
    for pno, page in enumerate(doc):
        hs, vs = lines(page)
        xs = cluster(sorted({round(v[0], 1) for v in vs}))
        if len(xs) < 5:
            continue  # 표가 없는 쪽(비고 등)
        # 같은 쪽의 두 표는 괘선이 몇 pt씩 어긋난다 → 근접한 x를 하나의 열 경계로 묶는다
        c0, c1, c2, c3, c4 = xs[0][0], xs[1][0], xs[2][0], xs[3][0], xs[-1][-1]
        full = sorted({round(h[0], 1) for h in hs if h[1] <= xs[0][-1] + 2 and h[2] >= xs[-1][0] - 2})
        sub = sorted({round(h[0], 1) for h in hs if xs[2][0] - 2 <= h[1] <= xs[2][-1] + 2 and h[2] >= xs[-1][0] - 2})
        sp = spans(page)
        for y0, y1 in zip(full, full[1:]):
            code = text_in(sp, c0, c1, y0, y1).replace(" ", "")
            name = text_in(sp, c1, c2, y0, y1)
            if code.startswith("분류번호"):
                continue
            cuts = [y0] + [s for s in sub if y0 < s < y1] + [y1]
            cells = []
            for a, b in zip(cuts, cuts[1:]):
                rtext = text_in(sp, c2, c3, a, b)
                pre = text_in(sp, c3, c4, a, b).replace(" ", "")
                if rtext or pre:
                    cells.append({"r_text": rtext, "r_codes": RCODE.findall(rtext.replace(" ", "")),
                                  "prohibited": "재활용금지" in rtext.replace(" ", ""),
                                  "pre_analysis": pre or None})
            rows.append({"page": pno + 1, "code": code, "name": name, "cells": cells})

    # 쪽을 넘어간 행(분류번호 칸이 빈 행)은 앞 번호에 붙인다
    merged = []
    for r in rows:
        if not r["code"] and merged:
            merged[-1]["cells"] += r["cells"]
            merged[-1]["name"] = (merged[-1]["name"] + " " + r["name"]).strip()
            merged[-1]["continued_on_page"] = r["page"]
        elif r["code"]:
            merged.append(r)
    # 사전 분석 칸이 세로로 병합됐거나 쪽을 넘어간 경우: 라벨 없는 칸은 위 칸에 합친다
    for r in merged:
        if len(r["code"]) != 8:
            # 그룹 행(02-01 등)은 명칭이 칸을 가로질러 병합돼 있다 → 재활용 유형 칸으로 읽지 않는다
            spill = " ".join(c["r_text"] + " " + (c["pre_analysis"] or "") for c in r["cells"]).strip()
            r["name"] = (r["name"] + " " + spill).strip()
            r["cells"] = []
            continue
        out_cells = []
        for cell in r["cells"]:
            if out_cells and cell["pre_analysis"] is None and not cell["prohibited"]:
                prev = out_cells[-1]
                prev["r_text"] = (prev["r_text"] + ", " + cell["r_text"]).strip(", ")
                prev["r_codes"] += cell["r_codes"]
            else:
                out_cells.append(cell)
        r["cells"] = out_cells
    bad = [r["code"] for r in merged if not ID.match(r["code"])]
    out = {"source": "RULE-A43",
           "note": "시행규칙 별표 4의3 <개정 2025. 12. 30.> 괘선 좌표로 자동 추출. 직접 고치지 말고 생성기를 다시 실행.",
           "rows": merged}
    OUT.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    six = [r for r in merged if len(r["code"]) == 8]
    print(f"rows={len(merged)} six_digit={len(six)} bad_ids={bad[:10]} "
          f"empty={[r['code'] for r in merged if not r['cells']][:20]}")


if __name__ == "__main__":
    main()
