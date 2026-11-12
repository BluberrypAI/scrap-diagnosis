"""표의 데이터 행 해석: 항목, 묶음(용출·함량), 단위, 결과 칸. 대응 층과 표 검증이 함께 쓴다."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.tables import CellRef, TableGrid
from app.reading.columns import ColumnInfo, ColumnRole, TableLayout
from app.reading.test_items import Group, TestItem, group_hint, match_items
from app.reading.units import find_unit, unit_rule
from app.reading.values import normalize_unit_cell

# 역할이 이런 열의 글자는 묶음 단서로 보지 않는다(값·기준 칸의 "용출" 같은 말은 무시)
_NON_GROUP_ROLES = {
    ColumnRole.RESULT,
    ColumnRole.LIMIT,
    ColumnRole.DETECTION_LIMIT,
    ColumnRole.JUDGEMENT,
}


@dataclass
class RowInfo:
    row: int
    item_text: str
    items: list[TestItem]
    group: Group | None
    unit_raw: str | None
    unit_ref: CellRef | None
    method: str | None


def section_groups(layout: TableLayout) -> dict[int, Group | None]:
    """행마다 위쪽 '구분 행'(한 칸이 표 전체 너비를 덮는 행)이 정한 묶음."""
    t = layout.table
    out: dict[int, Group | None] = {}
    current: Group | None = None
    for r in range(layout.first_data_row, t.n_rows):
        full = [c for c in t.cells if c.row == r and c.col_span == t.n_cols]
        if full:
            current = group_hint(full[0].text)
        out[r] = current
    return out


def is_section_row(table: TableGrid, row: int) -> bool:
    return any(c.row == row and c.col_span == table.n_cols for c in table.cells)


def item_column(layout: TableLayout) -> int | None:
    items = layout.cols_with(ColumnRole.ITEM)
    if items:
        return items[0].col
    # 항목 열 머리글이 없으면 결과 열보다 왼쪽에서 사전 항목이 가장 많이 맞는 열
    t = layout.table
    grid = t.expanded()
    results = [c.col for c in layout.cols_with(ColumnRole.RESULT)]
    limit = min(results) if results else t.n_cols
    best, best_hits = None, 0
    for k in range(limit):
        if layout.columns[k].role not in (ColumnRole.UNKNOWN, ColumnRole.GROUP):
            continue
        hits = sum(1 for r in range(layout.first_data_row, t.n_rows) if match_items(grid[r][k]))
        if hits > best_hits:
            best, best_hits = k, hits
    return best


def row_info(layout: TableLayout, row: int, sections: dict[int, Group | None]) -> RowInfo:
    t = layout.table
    grid = t.expanded()
    icol = item_column(layout)
    item_text = grid[row][icol] if icol is not None else ""
    items = match_items(item_text)

    # 묶음: 항목 글자 → 같은 행의 다른 칸(결과·기준 열 제외) → 위쪽 구분 행
    group = group_hint(item_text)
    if group is None:
        for col in layout.columns:
            if col.col == icol or col.role in _NON_GROUP_ROLES:
                continue
            g = group_hint(grid[row][col.col])
            if g is not None:
                group = g
                break
    if group is None:
        group = sections.get(row)

    unit_raw, unit_ref = None, None
    ucols = layout.cols_with(ColumnRole.UNIT)
    if ucols:
        unit_raw = normalize_unit_cell(grid[row][ucols[0].col])
        if unit_raw is not None:
            unit_ref = CellRef(page=t.page, table_index=t.table_index, row=row, col=ucols[0].col)
    if unit_raw is None and icol is not None and (u := find_unit(item_text)):
        unit_raw = u  # 항목 이름에 붙은 단위: "납(mg/L)", "수분(%)"
        unit_ref = CellRef(page=t.page, table_index=t.table_index, row=row, col=icol)

    mcols = layout.cols_with(ColumnRole.METHOD)
    method = grid[row][mcols[0].col].strip() or None if mcols else None
    return RowInfo(
        row=row,
        item_text=item_text,
        items=items,
        group=group,
        unit_raw=unit_raw,
        unit_ref=unit_ref,
        method=method,
    )


def header_unit_ref(layout: TableLayout, col: ColumnInfo) -> CellRef | None:
    """머리글에 단위가 있는 열이면 그 머리글 칸."""
    if not col.unit:
        return None
    t = layout.table
    for r in layout.header_rows:
        cell = t.cell_at(r, col.col)
        if cell is not None and col.unit in cell.text:
            return CellRef(page=t.page, table_index=t.table_index, row=cell.row, col=cell.col)
    return None


def candidate_items(info: RowInfo, unit_raw: str | None) -> tuple[list[TestItem], list[str]]:
    """행의 항목 후보를 묶음·단위로 거른다. (남은 후보, 메모)

    - 묶음을 알면 그 묶음의 항목만(pH처럼 묶음이 없는 항목은 그대로)
    - 묶음을 모르면 단위로 보조: 용출 항목은 mg/L로 환산되는 단위일 때만 남긴다.
      단위도 모르면 용출 항목은 정하지 않는다(후보로 남기되 메모)
    """
    notes: list[str] = []
    out: list[TestItem] = []
    for it in info.items:
        if it.group is None or info.group == it.group:
            out.append(it)
            continue
        if info.group is not None:
            continue  # 묶음이 다름
        if it.unit is None:
            out.append(it)
            continue
        if unit_raw is None:
            notes.append(f"{it.label}: 용출·함량 구분과 단위를 모두 확인하지 못함")
            out.append(it)
            continue
        if unit_rule(unit_raw, it.unit) is not None and not _ambiguous_unit(unit_raw):
            out.append(it)
    return out, notes


def _ambiguous_unit(unit_raw: str) -> bool:
    # ppm·ppb는 용출액인지 고상인지 단위만으로 알 수 없다
    return re.sub(r"\s+", "", unit_raw).lower() in {"ppm", "ppb"}
