"""글자 층이 있는 PDF에서 표를 로컬로 뽑는다(pdfplumber). 결과는 TableExtraction.

설계: docs/design/test-report-table-extraction.md 1절·4절.
- 표 찾기: 먼저 선(line) 기준. 쪽에 선으로 찾은 표가 없으면 글자 정렬(text) 기준으로 찾되,
  2행·2열 이상이고 칸 대부분이 차 있을 때만 표로 보고 warnings에 "선 없는 표 추정"을 남긴다.
- 병합 칸: pdfplumber 표의 칸 경계(x·y)로 격자를 만들고,
  칸 bbox가 덮는 격자 행·열 수를 span으로 둔다.
  병합으로 가려진 자리(pdfplumber가 None으로 주는 칸)는 칸을 만들지 않는다.
- 각주: 표 아래(다음 표 위 또는 쪽 높이 15% 안) 줄 중 parse_footnote_line이 받는 줄.
- 머리글 여부(is_header)·신뢰도(confidence)는 정하지 않는다(열 역할 판정이 정한다).
I/O는 입력 바이트뿐, LLM 없음.
"""

from __future__ import annotations

import io
import re
from bisect import bisect_left
from dataclasses import dataclass

import pdfplumber

from app.domain.tables import BBox, Footnote, PageInfo, TableCell, TableExtraction, TableGrid
from app.reading.common import link_continuations, parse_footnote_line, split_cell_marks

BACKEND = "pdfplumber"
# 격자 경계를 같은 선으로 볼 거리(pt)
_SNAP = 1.5
# 각주를 찾는 범위: 표 아래 쪽 높이의 이 비율까지
_FOOTNOTE_REACH = 0.15
# 글자 정렬로 추정한 표를 받아들일 최소 비율(빈 칸이 아닌 칸)
_TEXT_TABLE_MIN_FILL = 0.6
_TEXT_SETTINGS = {"vertical_strategy": "text", "horizontal_strategy": "text"}
_WS_RE = re.compile(r"\s+")


class PdfReadFailed(ValueError):
    """암호가 걸렸거나 깨진 PDF."""


@dataclass
class _RawCell:
    row: int
    col: int
    row_span: int
    col_span: int
    bbox: tuple[float, float, float, float]  # pt, 왼쪽 위 원점
    text: str


def _open(data: bytes) -> pdfplumber.PDF:
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
        _ = pdf.pages  # 쪽 목록을 읽어야 암호·깨짐이 드러난다
    except Exception as exc:  # pdfminer가 여러 종류의 예외를 낸다
        raise PdfReadFailed(f"PDF를 열 수 없다: {exc.__class__.__name__}") from exc
    return pdf


def has_text_layer(data: bytes, min_chars: int = 20) -> bool:
    """공백이 아닌 글자가 문서 전체에 min_chars개 이상이면 글자 층이 있다고 본다."""
    pdf = _open(data)
    try:
        count = 0
        for page in pdf.pages:
            count += sum(1 for ch in page.chars if not ch.get("text", "").isspace())
            if count >= min_chars:
                return True
        return False
    except Exception as exc:
        raise PdfReadFailed(f"PDF 글자를 읽을 수 없다: {exc.__class__.__name__}") from exc
    finally:
        pdf.close()


def extract_pdf_tables(data: bytes) -> TableExtraction:
    pdf = _open(data)
    pages: list[PageInfo] = []
    tables: list[TableGrid] = []
    warnings: list[str] = []
    try:
        for page_no, page in enumerate(pdf.pages, start=1):
            pages.append(
                PageInfo(
                    page=page_no,
                    text=page.extract_text() or "",
                    width=float(page.width),
                    height=float(page.height),
                )
            )
            tables.extend(_page_tables(page, page_no, warnings))
    except PdfReadFailed:
        raise
    except Exception as exc:
        raise PdfReadFailed(f"PDF를 읽는 중 실패: {exc.__class__.__name__}") from exc
    finally:
        pdf.close()
    return TableExtraction(
        source="pdf_text_layer",
        pages=pages,
        tables=link_continuations(tables),
        backend=BACKEND,
        warnings=warnings,
    )


def _page_tables(page, page_no: int, warnings: list[str]) -> list[TableGrid]:
    found: list[tuple[tuple[float, float, float, float], list[_RawCell]]] = []
    for t in page.find_tables():
        cells = _grid_cells(t)
        if cells:
            found.append((t.bbox, _split_stacked_rows(page, cells)))
    if not found:
        for t in page.find_tables(_TEXT_SETTINGS):
            cells = _drop_empty_lines(_grid_cells(t))
            if _looks_like_table(cells):
                found.append((_union_bbox(cells), cells))
        if found:
            warnings.append(f"{page_no}쪽: 선 없는 표를 글자 정렬로 추정했다({len(found)}개)")
    found.sort(key=lambda x: (x[0][1], x[0][0]))  # 위→아래, 같은 높이면 왼→오른

    w, h = float(page.width), float(page.height)
    grids: list[TableGrid] = []
    for idx, (bbox, cells) in enumerate(found):
        next_top = found[idx + 1][0][1] if idx + 1 < len(found) else h
        out_cells = []
        for c in cells:
            text, marks = split_cell_marks(c.text)
            out_cells.append(
                TableCell(
                    row=c.row,
                    col=c.col,
                    text=text,
                    row_span=c.row_span,
                    col_span=c.col_span,
                    bbox=_norm(c.bbox, w, h),
                    footnote_marks=marks,
                )
            )
        grids.append(
            TableGrid(
                page=page_no,
                table_index=idx,
                n_rows=max(c.row + c.row_span for c in cells),
                n_cols=max(c.col + c.col_span for c in cells),
                cells=out_cells,
                footnotes=_footnotes_below(page, bbox, next_top),
                source="pdf_text_layer",
                bbox=_norm(bbox, w, h),
            )
        )
    return grids


def _snap_edges(values: list[float]) -> list[float]:
    edges: list[float] = []
    for v in sorted(values):
        if not edges or v - edges[-1] > _SNAP:
            edges.append(v)
    return edges


def _edge_index(edges: list[float], v: float) -> int:
    i = bisect_left(edges, v - _SNAP)
    return min(i, len(edges) - 1)


def _clean(text: str | None) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def _grid_cells(table) -> list[_RawCell]:
    """pdfplumber 표 → 격자 좌표의 칸 목록(병합 칸은 anchor 하나)."""
    texts = table.extract()
    boxes: list[tuple[tuple[float, float, float, float], str]] = []
    for r_i, row in enumerate(table.rows):
        for c_i, box in enumerate(row.cells):
            if box is None:  # 병합으로 가려진 자리
                continue
            text = texts[r_i][c_i] if r_i < len(texts) and c_i < len(texts[r_i]) else ""
            boxes.append((tuple(float(v) for v in box), _clean(text)))
    if not boxes:
        return []
    xs = _snap_edges([v for b, _ in boxes for v in (b[0], b[2])])
    ys = _snap_edges([v for b, _ in boxes for v in (b[1], b[3])])
    cells: list[_RawCell] = []
    for (x0, y0, x1, y1), text in boxes:
        c0, c1 = _edge_index(xs, x0), _edge_index(xs, x1)
        r0, r1 = _edge_index(ys, y0), _edge_index(ys, y1)
        if c1 <= c0 or r1 <= r0:  # 폭이나 높이가 없는 칸
            continue
        cells.append(_RawCell(r0, c0, r1 - r0, c1 - c0, (x0, y0, x1, y1), text))
    return _dedupe_overlaps(cells)


_LINE_TOL = 3.0  # 같은 줄로 보는 글자 윗변 차이(pt)


def _cell_lines(page, bbox) -> list[tuple[float, float, str]]:
    """칸 안 글자를 줄로 묶는다. [(윗변, 아랫변, 글자)] 위→아래."""
    x0, y0, x1, y1 = bbox
    x0, y0 = max(x0, 0.0), max(y0, 0.0)
    x1, y1 = min(x1, float(page.width)), min(y1, float(page.height))
    if x1 <= x0 or y1 <= y0:
        return []
    words = page.within_bbox((x0, y0, x1, y1)).extract_words()
    lines: list[list] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(w["top"] - lines[-1][0]) <= _LINE_TOL:
            lines[-1][1] = max(lines[-1][1], w["bottom"])
            lines[-1][2].append(w)
        else:
            lines.append([w["top"], w["bottom"], [w]])
    return [
        (top, bottom, _clean(" ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"]))))
        for top, bottom, ws in lines
    ]


def _split_stacked_rows(page, cells: list[_RawCell]) -> list[_RawCell]:
    """선 없이 한 칸에 여러 항목이 줄로 쌓인 행을 줄마다 나눈다.

    예: 항목 칸 "납(mg/L) / 구리(mg/L) / …"와 결과 칸 "불검출 / 0.021 / …"가
    같은 높이로 줄을 맞춘 경우.
    - 두 칸 이상이 같은 줄 수(2줄 이상)이고 줄 높이가 서로 맞을 때만 나눈다.
    - 줄 수가 다른 칸(예: 두 줄로 쓴 기준)은 줄 높이로 가장 가까운 행에 붙인다.
    - 한 줄짜리 칸(검체명 등)은 나눈 행 전체에 걸친 병합 칸이 된다.
    """
    n_rows = max(c.row + c.row_span for c in cells)
    plan: dict[int, list[float]] = {}  # 원래 행 → 나눈 행의 경계(윗변들)
    lines_of: dict[int, list[tuple[float, float, str]]] = {}
    for r in range(n_rows):
        if any(c.row < r < c.row + c.row_span or (c.row == r and c.row_span > 1) for c in cells):
            continue  # 병합 칸이 걸친 행은 건드리지 않는다
        row_cells = [c for c in cells if c.row == r]
        for c in row_cells:
            lines_of[id(c)] = _cell_lines(page, c.bbox)
        counts = [len(lines_of[id(c)]) for c in row_cells]
        multi = [k for k in counts if k >= 2]
        if not multi:
            continue
        n = max(set(multi), key=lambda k: (multi.count(k), k))
        refs = [c for c in row_cells if len(lines_of[id(c)]) == n]
        if len(refs) < 2:
            continue
        tops = [ln[0] for ln in lines_of[id(refs[0])]]
        if any(
            abs(a[0] - b) > _LINE_TOL
            for c in refs[1:]
            for a, b in zip(lines_of[id(c)], tops, strict=True)
        ):
            continue  # 줄 높이가 맞지 않으면 한 칸의 줄바꿈일 수 있다
        plan[r] = tops
    if not plan:
        return cells

    factor = {r: len(plan.get(r, [None])) for r in range(n_rows)}
    start: dict[int, int] = {}
    acc = 0
    for r in range(n_rows):
        start[r] = acc
        acc += factor[r]
    out: list[_RawCell] = []
    for c in cells:
        new_span = sum(factor[r] for r in range(c.row, c.row + c.row_span))
        tops = plan.get(c.row) if c.row_span == 1 else None
        lines = lines_of.get(id(c), [])
        if tops is None or len(lines) < 2:
            out.append(_RawCell(start[c.row], c.col, new_span, c.col_span, c.bbox, c.text))
            continue
        buckets: list[list[tuple[float, float, str]]] = [[] for _ in tops]
        for ln in lines:
            i = min(range(len(tops)), key=lambda i: abs(ln[0] - tops[i]))
            if ln[0] < tops[i] - _LINE_TOL and i > 0:
                i -= 1
            buckets[i].append(ln)
        x0, y0, x1, y1 = c.bbox
        for i, top in enumerate(tops):
            b_top = y0 if i == 0 else top - _LINE_TOL
            b_bottom = y1 if i == len(tops) - 1 else tops[i + 1] - _LINE_TOL
            text = _clean(" ".join(ln[2] for ln in buckets[i]))
            out.append(
                _RawCell(start[c.row] + i, c.col, 1, c.col_span, (x0, b_top, x1, b_bottom), text)
            )
    return out


def _dedupe_overlaps(cells: list[_RawCell]) -> list[_RawCell]:
    """같은 자리를 두 칸이 덮으면(어긋난 선) 먼저 나온(위·왼쪽) 칸만 남긴다."""
    taken: set[tuple[int, int]] = set()
    out: list[_RawCell] = []
    for c in sorted(cells, key=lambda c: (c.row, c.col)):
        spots = {
            (r, k)
            for r in range(c.row, c.row + c.row_span)
            for k in range(c.col, c.col + c.col_span)
        }
        if spots & taken:
            continue
        taken |= spots
        out.append(c)
    return out


def _drop_empty_lines(cells: list[_RawCell]) -> list[_RawCell]:
    """글자 정렬 표에서 생기는 빈 행·빈 열을 지우고 번호를 다시 매긴다(병합 칸이 없을 때만 씀)."""
    if not cells or any(c.row_span > 1 or c.col_span > 1 for c in cells):
        return cells
    rows = sorted({c.row for c in cells if c.text})
    cols = sorted({c.col for c in cells if c.text})
    r_map = {r: i for i, r in enumerate(rows)}
    c_map = {k: i for i, k in enumerate(cols)}
    return [
        _RawCell(r_map[c.row], c_map[c.col], 1, 1, c.bbox, c.text)
        for c in cells
        if c.row in r_map and c.col in c_map
    ]


def _looks_like_table(cells: list[_RawCell]) -> bool:
    if not cells:
        return False
    n_rows = max(c.row for c in cells) + 1
    n_cols = max(c.col for c in cells) + 1
    if n_rows < 2 or n_cols < 2:
        return False
    filled = sum(1 for c in cells if c.text)
    return filled / (n_rows * n_cols) >= _TEXT_TABLE_MIN_FILL


def _union_bbox(cells: list[_RawCell]) -> tuple[float, float, float, float]:
    return (
        min(c.bbox[0] for c in cells),
        min(c.bbox[1] for c in cells),
        max(c.bbox[2] for c in cells),
        max(c.bbox[3] for c in cells),
    )


def _footnotes_below(page, bbox, next_top: float) -> list[Footnote]:
    h, w = float(page.height), float(page.width)
    top = float(bbox[3])
    bottom = min(next_top, top + h * _FOOTNOTE_REACH, h)
    if bottom - top < 1:
        return []
    region = page.within_bbox((0, top, w, bottom))
    out: list[Footnote] = []
    for line in (region.extract_text() or "").splitlines():
        note = parse_footnote_line(line)
        if note is not None and not any(n.mark == note.mark for n in out):
            out.append(note)
    return out


def _norm(bbox, w: float, h: float) -> BBox:
    x0, y0, x1, y1 = (float(v) for v in bbox)

    def clamp(v: float) -> float:
        return min(1.0, max(0.0, v))

    return (clamp(x0 / w), clamp(y0 / h), clamp(x1 / w), clamp(y1 / h))
