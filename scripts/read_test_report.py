"""시험성적서 파일 하나를 읽어 표·열 역할·사실·검증 결과를 보여 준다(비교 시험용).

    uv run python scripts/read_test_report.py 성적서.pdf
    uv run python scripts/read_test_report.py 성적서.pdf --backend local      # pdfplumber만
    # Azure(ALLOW_DOCUMENT_OCR 필요, 과금)
    uv run python scripts/read_test_report.py 사진.jpg --backend azure
    uv run python scripts/read_test_report.py 성적서.pdf --subject "시료 B" --json out.json

Azure 경로는 원본을 Azure Document Intelligence로 보낸다.
실제 고객 서류는 쓰지 말고 가린 샘플만 쓴다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.reading.pipeline import read_test_report  # noqa: E402


def _print_table(lay) -> None:
    t = lay.table
    roles = " | ".join(
        f"{c.role.value}{'' if c.by_rule else '?'}{f'[{c.sample_label}]' if c.sample_label else ''}"
        for c in lay.columns
    )
    cont = f" (앞 표 {t.continued_from.page}쪽에서 이어짐)" if t.continued_from else ""
    print(f"\n## {t.page}쪽 표 {t.table_index} — {t.n_rows}행 x {t.n_cols}열, {t.source}{cont}")
    print(f"열 역할: {roles}")
    for r, row in enumerate(t.expanded()):
        tag = "H" if r in lay.header_rows else " "
        print(f" {tag}{r:>2} | " + " | ".join(x or "·" for x in row))
    for fn in t.footnotes:
        print(f"    각주 [{fn.mark}] {fn.text}")
    for note in lay.notes:
        print(f"    메모: {note}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--backend", choices=["auto", "local", "azure"], default="auto")
    ap.add_argument("--subject", help="이 건의 시료 이름(시료가 여럿인 성적서)")
    ap.add_argument("--json", type=Path, help="결과(계약 형식)를 JSON으로 저장")
    args = ap.parse_args()

    data = args.file.read_bytes()
    rep = read_test_report(
        data,
        args.file.name,
        settings=get_settings(),
        backend=args.backend,
        subject_hint=args.subject,
        document_id=args.file.name,
    )
    print("# 경로")
    for step in rep.route:
        print(f"- {step}")
    if rep.extraction is not None:
        for w in rep.extraction.warnings:
            print(f"- 백엔드 메모: {w}")
        for key in sorted(rep.layouts):
            _print_table(rep.layouts[key])

    print("\n# 사실")
    for f in rep.result.facts:
        if f.status.value == "FOUND":
            if f.below_detection_limit:
                val = (
                    f"불검출(기준 {f.detection_limit:g} 미만으로 봄)"
                    if f.detection_limit_basis == "limit_column"
                    else f"불검출(검출한계 {f.detection_limit:g})"
                )
            else:
                cmp = "" if f.comparator.value == "EQ" else f"{f.comparator.value} "
                val = f"{cmp}{f.value:g}"
            ref = f.cell_ref
            where = f"{ref.page}쪽 표{ref.table_index} ({ref.row},{ref.col})" if ref else ""
            print(f"- {f.key}: {val}  [{where}] {f.quote}")
        elif f.status.value != "NOT_FOUND":
            print(f"- {f.key}: {f.status.value} — {f.note or ''}")
    for w in rep.result.warnings:
        print(f"! {w.code.value}: {w.message} {w.key or ''}")
    for e in rep.result.errors:
        print(f"!! {e.code.value}: {e.message}")
    for key, reasons in rep.rejected.items():
        print(f"x 검증 탈락 {key}: {'; '.join(reasons)}")

    if args.json:
        args.json.write_text(
            json.dumps(rep.result.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n저장: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
