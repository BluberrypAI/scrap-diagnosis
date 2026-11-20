"""표 인식 백엔드가 함께 쓰는 도우미: 각주 표시 분리, 각주 줄 해석, 쪽 넘김 표 잇기."""

from __future__ import annotations

import re

from app.reading.tables import Footnote, TableGrid, TableRef

# 칸 글자 끝에 붙은 각주 표시: "ND*", "ND **", "0.5 1)", "ND1)", "ND※"
# ("0.5(1)"은 값일 수 있어 떼지 않음)
_CELL_MARK_RE = re.compile(r"\s*(\*{1,3}|※|\(\d{1,2}\)|\d{1,2}\))\s*$")
# 표 아래 각주 줄: "* 검출한계 0.01 mg/L", "1) …", "(1) …", "※ …", "주) …", "주1) …"
_FOOTNOTE_LINE_RE = re.compile(
    r"^\s*(\*{1,3}|※|\(\d{1,2}\)|\d{1,2}\)|주\s*\d{0,2}\s*\))\s*(.+?)\s*$"
)


def normalize_mark(mark: str) -> str:
    """각주 표시를 비교용으로 맞춘다. "(1)"·"1)"·"주1)" → "1", "주)" → "※"."""
    m = mark.strip()
    digits = re.sub(r"\D", "", m)
    if digits:
        return digits
    if m.startswith("주"):
        return "※"
    return m


def split_cell_marks(text: str) -> tuple[str, list[str]]:
    """칸 글자에서 끝에 붙은 각주 표시를 떼어 낸다.

    번호 표시("1)", "(1)")는 숫자 값의 일부일 수 있어("0.51)", "0.5(1)") 앞에 공백이 있거나
    바로 앞 글자가 숫자·소수점이 아닐 때("ND1)")만 표시로 본다. 표시만 있는 칸("*")은 그대로 둔다.
    """
    marks: list[str] = []
    body = text.strip()
    while True:
        m = _CELL_MARK_RE.search(body)
        if not m:
            break
        raw = m.group(1)
        before = body[: m.start()]
        if not before.strip():
            break  # 표시만 남는 경우는 떼지 않는다
        if raw[0].isdigit() or raw.startswith("("):
            spaced = m.group(0).startswith((" ", "\t"))
            prev = before[-1]
            if not spaced and (prev.isdigit() or prev == "."):
                break
        marks.insert(0, normalize_mark(raw))
        body = before.rstrip()
    return body, marks


def parse_footnote_line(line: str) -> Footnote | None:
    m = _FOOTNOTE_LINE_RE.match(line)
    if not m:
        return None
    return Footnote(mark=normalize_mark(m.group(1)), text=m.group(2))


def link_continuations(tables: list[TableGrid]) -> list[TableGrid]:
    """쪽 넘김으로 이어진 표에 continued_from을 채운다.

    조건: 바로 앞 쪽의 마지막 표와 열 수가 같고, 이 표가 그 쪽의 첫 표이며,
    첫 행에 머리글 표시가 없다. 열 위치(bbox x)를 알면 첫·끝 x가 쪽 너비의 3% 안에서
    맞아야 한다. 추정이므로 검증기가 경고를 붙인다.
    """
    by_page: dict[int, list[TableGrid]] = {}
    for t in tables:
        by_page.setdefault(t.page, []).append(t)
    out: list[TableGrid] = []
    for t in tables:
        prev_page = by_page.get(t.page - 1)
        first_here = min(by_page[t.page], key=lambda x: x.table_index) is t
        if t.continued_from is None and prev_page and first_here:
            prev = max(prev_page, key=lambda x: x.table_index)
            header_first_row = any(c.is_header for c in t.cells if c.row == 0)
            if prev.n_cols == t.n_cols and not header_first_row and _x_aligned(prev, t):
                t = t.model_copy(
                    update={
                        "continued_from": TableRef(page=prev.page, table_index=prev.table_index)
                    }
                )
        out.append(t)
    return out


def _x_aligned(a: TableGrid, b: TableGrid, tol: float = 0.03) -> bool:
    if a.bbox is None or b.bbox is None:
        return True
    return abs(a.bbox[0] - b.bbox[0]) <= tol and abs(a.bbox[2] - b.bbox[2]) <= tol
