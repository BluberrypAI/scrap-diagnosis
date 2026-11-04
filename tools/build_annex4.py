"""시행규칙 별표 4(폐기물의 종류별 세부분류)를 번호 표로 옮긴다. 결과: rules/annex4_codes.yaml

PDF 텍스트에서 번호와 명칭을 읽고, 여러 줄에 걸친 명칭은 이어 붙인다.
인용문(번호+명칭)은 tests/test_annex4.py가 원문과 다시 대조한다.
실행: python tools/build_annex4.py
"""
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "sources" / "raw" / "170401309.pdf"
OUT = ROOT / "rules" / "annex4_codes.yaml"

SECTIONS = {"1.": "DESIGNATED", "2.": "GENERAL", "3.": "HOUSEHOLD"}
LINE = re.compile(r"^\s*(\d{2}(?:-\d{2}){0,2})\s+(\S.*)$")


def pdf_text() -> str:
    import fitz  # pymupdf

    return "\n".join(p.get_text() for p in fitz.open(PDF))


def main() -> None:
    text = pdf_text()
    section = None
    entries: list[dict] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or "법제처" in line or "국가법령정보센터" in line:
            continue
        s = line.strip()
        if s[:2] in SECTIONS and ("세부분류" in s):
            section = SECTIONS[s[:2]]
            continue
        if section is None:
            continue
        m = LINE.match(line)
        if m:
            entries.append({"id": m.group(1), "name": m.group(2).strip(), "section": section})
        elif entries:
            entries[-1]["name"] += " " + s  # 앞 명칭의 다음 줄
    for e in entries:
        e["name"] = re.sub(r"\s+", " ", e["name"]).strip()
        # 줄바꿈으로 갈라진 한글 단어를 붙인다: "포 함한다" 같은 경우는 원문 대조 테스트가 공백 무시로 검사
        e["level"] = {2: "division", 5: "group", 8: "code"}[len(e["id"])]

    codes = [e for e in entries if e["level"] == "code"]
    groups = [e for e in entries if e["level"] != "code"]
    out = {
        "source": "RULE-A4",
        "note": "시행규칙 별표 4 <개정 2025. 12. 30.> 에서 자동 추출. 직접 고치지 말고 생성기를 다시 실행.",
        "groups": [{k: e[k] for k in ("id", "name", "section", "level")} for e in groups],
        "codes": [{k: e[k] for k in ("id", "name", "section")} for e in codes],
    }
    OUT.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    by = {}
    for c in codes:
        by[c["section"]] = by.get(c["section"], 0) + 1
    print(f"codes={len(codes)} unique={len({c['id'] for c in codes})} groups={len(groups)} by_section={by}")


if __name__ == "__main__":
    main()
