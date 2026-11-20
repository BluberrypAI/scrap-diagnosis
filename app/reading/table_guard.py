"""표 검증(T1~T10). 대응 층(규칙이든 LLM이든)이 낸 FOUND 항목을 표 구조로 다시 확인한다.

설계 docs/design/test-report-table-extraction.md 6절.
대응 층의 판단을 믿지 않고 표에서 다시 계산한다.
실패 사유가 하나라도 있으면 그 항목은 FOUND로 받지 않는다.
"""

from __future__ import annotations

import re

from app.reading.columns import ColumnRole, TableLayout
from app.reading.contract import Comparator, ExtractedFactItem, ItemStatus
from app.reading.mapper import LOW_CONFIDENCE
from app.reading.rows import candidate_items, is_section_row, row_info, section_groups
from app.reading.tables import CellRef, FootnoteRef, TableGrid
from app.reading.test_items import BY_KEY
from app.reading.units import convert
from app.reading.values import numbers_in, parse_value, to_float

_REL_TOL = 1e-6
_ND_WORDS = ("nd", "n.d", "불검출", "검출안됨", "검출되지않음", "미검출")


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= _REL_TOL * max(1.0, abs(a), abs(b))


def _compact(text: str) -> str:
    return re.sub(r"[\s,]+", "", text or "").lower()


def _number_in(raw: str, text: str) -> bool:
    """raw의 숫자가 text의 숫자 중 하나와 같은가(쉼표·1.50/1.5 표기 차이 허용)."""
    nums = numbers_in(raw)
    if len(nums) != 1:
        return False
    v = to_float(nums[0])
    return any(_same(v, to_float(n)) for n in numbers_in(text))


def validate_table_item(
    item: ExtractedFactItem,
    layouts: dict[tuple[int, int], TableLayout],
    *,
    unit_of: dict[str, str | None] | None = None,
) -> list[str]:
    """실패 사유 목록(비면 통과). FOUND가 아니거나 cell_ref가 없으면 검사하지 않는다(기존 §5 몫)."""
    if item.status is not ItemStatus.FOUND or item.cell_ref is None:
        return []
    reasons: list[str] = []
    ref = item.cell_ref
    test_item = BY_KEY.get(item.key)
    if test_item is None:
        return [f"T4: 항목명 사전에 없는 키 {item.key}"]
    target_unit = (unit_of or {}).get(item.key, test_item.unit)

    # T1 칸이 있다
    layout = layouts.get((ref.page, ref.table_index))
    if layout is None:
        return ["T1: 가리키는 표가 없음"]
    t: TableGrid = layout.table
    if not (0 <= ref.row < t.n_rows and 0 <= ref.col < t.n_cols):
        return ["T1: 표 밖 좌표"]
    cell = t.cell_at(ref.row, ref.col)
    if cell is None:
        return ["T1: 빈 자리"]
    if ref.row < layout.first_data_row or is_section_row(t, ref.row):
        return ["T3: 머리글·구분 행의 칸"]

    # T2 값이 그 칸에 있다
    parsed = parse_value(cell.text)
    if item.below_detection_limit:
        if parsed.kind != "nd" and not any(w in _compact(cell.text) for w in _ND_WORDS):
            reasons.append("T2: 칸에 불검출 표기가 없음")
    else:
        if not item.value_raw or not _number_in(item.value_raw, cell.text):
            reasons.append("T2: value_raw가 칸 글자에 없음")
        elif parsed.kind == "number" and parsed.comparator is not item.comparator:
            reasons.append("T2: 부등호가 칸 글자와 다름")

    # T3 결과 열 / T10 규칙으로 정한 열
    col = layout.column(ref.col)
    if col.role is not ColumnRole.RESULT:
        reasons.append(f"T3: 결과 열이 아님({col.role.value} '{col.header}')")
    elif not col.by_rule:
        reasons.append("T10: 열 역할을 규칙으로 정하지 못한 열")

    # OCR 신뢰도
    if cell.confidence is not None and cell.confidence < LOW_CONFIDENCE:
        reasons.append(f"OCR: 칸 신뢰도 낮음({cell.confidence:.2f})")

    # T4 항목 / T5 묶음
    sections = section_groups(layout)
    info = row_info(layout, ref.row, sections)
    if test_item not in info.items:
        reasons.append(f"T4: 같은 행의 항목 '{info.item_text}'이 {item.key}와 맞지 않음")
    else:
        cands, notes = candidate_items(info, item.unit_raw)
        if test_item not in cands:
            reasons.append(f"T5: 묶음(용출·함량)이 맞지 않음(행 묶음 {info.group})")
        elif len(cands) > 1 or notes:
            reasons.append("T5: 용출·함량을 가르지 못함")

    # T6 시료가 여럿이면 열이 정해져 있다
    results = [c for c in layout.cols_with(ColumnRole.RESULT) if c.by_rule]
    if len(results) > 1 and item.sample_label != col.sample_label:
        reasons.append("T6: 시료별 결과 열인데 sample_label이 그 열과 다름")

    # T7 단위가 근거 칸에 있고, 환산을 다시 계산하면 같다
    if target_unit is None:
        if item.unit_raw:
            reasons.append("T7: 단위가 없는 항목에 단위가 있음")
    elif not item.unit_raw:
        reasons.append("T7: 단위가 없음")
    else:
        uref = item.unit_ref or ref
        ucell = _ref_text(layouts, uref)
        if ucell is None or _compact(item.unit_raw) not in _compact(ucell):
            reasons.append("T7: unit_raw가 근거 칸에 없음")
    if (
        not item.below_detection_limit
        and item.value_raw
        and not any(r.startswith("T2") for r in reasons)
    ):
        conv = convert(to_float(numbers_in(item.value_raw)[0]), item.unit_raw, target_unit)
        if (
            conv is None
            or not isinstance(item.value, int | float)
            or not _same(conv, float(item.value))
        ):
            reasons.append("T7: 환산값이 다시 계산한 값과 다름")

    # T8 검출한계 근거
    if item.below_detection_limit:
        reasons += _check_detection_limit(item, layout, ref)

    # T9 같은 키가 다른 값으로 또 있다
    reasons += _check_duplicates(item, layouts, target_unit)
    return reasons


def _ref_text(layouts: dict[tuple[int, int], TableLayout], ref: CellRef) -> str | None:
    lay = layouts.get((ref.page, ref.table_index))
    if lay is None:
        return None
    c = lay.table.cell_at(ref.row, ref.col)
    return c.text if c else None


def _check_detection_limit(item: ExtractedFactItem, layout: TableLayout, ref: CellRef) -> list[str]:
    t = layout.table
    dref = item.detection_limit_ref
    if dref is None or item.detection_limit is None:
        return ["T8: 검출한계 근거가 없음"]
    if item.detection_limit_basis == "limit_column" and not isinstance(dref, CellRef):
        return ["T8: 기준값 상한은 같은 행 기준 칸이어야 함"]
    if isinstance(dref, FootnoteRef):
        if (dref.page, dref.table_index) != (t.page, t.table_index):
            return ["T8: 다른 표의 각주"]
        fn = t.footnote(dref.footnote_mark)
        if fn is None:
            return ["T8: 각주가 없음"]
        cell = t.cell_at(ref.row, ref.col)
        marks = cell.footnote_marks if cell else []
        if dref.footnote_mark not in marks and dref.footnote_mark != "※":
            return ["T8: 값 칸에 그 각주 표시가 없음"]
        text = fn.text
    else:
        same_cell = (dref.page, dref.table_index, dref.row, dref.col) == (
            ref.page,
            ref.table_index,
            ref.row,
            ref.col,
        )
        if not same_cell:
            if (dref.page, dref.table_index, dref.row) != (ref.page, ref.table_index, ref.row):
                return ["T8: 검출한계 칸이 같은 행이 아님"]
            role = layout.column(dref.col).role
            if item.detection_limit_basis == "limit_column":
                if role is not ColumnRole.LIMIT:
                    return ["T8: 기준값을 상한으로 썼다면서 기준 열이 아님"]
            elif role is not ColumnRole.DETECTION_LIMIT:
                return ["T8: 검출한계 열이 아님"]
        c = t.cell_at(dref.row, dref.col)
        text = c.text if c else ""
    # 검출한계 값은 단위 환산 전후 어느 쪽이든 근거 글자의 숫자와 맞아야 한다
    nums = [to_float(n) for n in numbers_in(text)]
    if not nums:
        return ["T8: 근거에 숫자가 없음"]
    ok = any(_same(item.detection_limit, n) for n in nums) or any(
        (conv := convert(n, item.unit_raw, BY_KEY[item.key].unit)) is not None
        and _same(item.detection_limit, conv)
        for n in nums
    )
    return [] if ok else ["T8: 검출한계 값이 근거와 다름"]


def _check_duplicates(
    item: ExtractedFactItem,
    layouts: dict[tuple[int, int], TableLayout],
    target_unit: str | None,
) -> list[str]:
    test_item = BY_KEY[item.key]
    mine = item.cell_ref
    seen: set[tuple] = set()
    for (page, ti), lay in layouts.items():
        results = [c for c in lay.cols_with(ColumnRole.RESULT) if c.by_rule]
        if item.sample_label:
            results = [c for c in results if c.sample_label == item.sample_label] or results
        if len(results) != 1:
            continue
        col = results[0]
        sections = section_groups(lay)
        for r in range(lay.first_data_row, lay.table.n_rows):
            if is_section_row(lay.table, r):
                continue
            if mine and (page, ti, r, col.col) == (mine.page, mine.table_index, mine.row, mine.col):
                continue
            info = row_info(lay, r, sections)
            if test_item not in info.items:
                continue
            cell = lay.table.cell_at(r, col.col)
            p = parse_value(cell.text if cell else "")
            unit = info.unit_raw or col.unit or p.unit
            cands, _ = candidate_items(info, unit)
            if test_item not in cands:
                continue
            if p.kind == "nd":
                sig: tuple = ("ND",)
            elif p.kind == "number":
                conv = convert(p.value or 0.0, unit, target_unit)
                sig = ("VAL", round(conv, 9) if conv is not None else p.raw, p.comparator)
            else:
                sig = ("TEXT", p.raw)
            seen.add(sig)
    if item.below_detection_limit:
        mine_sig: tuple = ("ND",)
    else:
        v = float(item.value) if isinstance(item.value, int | float) else 0.0
        mine_sig = ("VAL", round(v, 9), item.comparator)
    others = seen - {mine_sig}
    return [f"T9: 같은 항목이 다른 값으로 또 있음({len(others)}곳)"] if others else []


__all__ = ["validate_table_item", "Comparator"]
