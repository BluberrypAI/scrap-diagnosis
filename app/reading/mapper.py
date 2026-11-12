"""대응 층(규칙): 표 → 시험성적서 사실 항목. LLM 없이 열 역할과 항목명 사전으로 값을 칸에 대응한다.

설계 docs/design/test-report-table-extraction.md 6절.
이 결과도 표 검증(table_guard)을 다시 통과해야 한다.
나중에 LLM 대응 층을 붙이면 같은 출력 형식(ExtractedFactItem + cell_ref)을 낸다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.document import (
    Comparator,
    ExtractedFactItem,
    ExtractionWarning,
    ItemStatus,
    WarningCode,
)
from app.domain.tables import CellRef, FootnoteRef, TableGrid
from app.reading.columns import ColumnInfo, ColumnRole, TableLayout, role_of_header
from app.reading.rows import (
    RowInfo,
    candidate_items,
    header_unit_ref,
    is_section_row,
    item_column,
    row_info,
    section_groups,
)
from app.reading.test_items import BY_KEY, TestItem, match_items
from app.reading.units import UnitRule, convert, find_unit, unit_rule
from app.reading.values import numbers_in, parse_value, to_float

LOW_CONFIDENCE = 0.8  # OCR 칸 신뢰도가 이보다 낮으면 값을 정하지 않는다
_DL_WORDS = ("검출한계", "정량한계", "검출하한", "mdl", "loq", "lod")


@dataclass
class _Candidate:
    item: ExtractedFactItem
    signature: tuple
    warnings: list[ExtractionWarning] = field(default_factory=list)


def _quote(table: TableGrid, row: int) -> str:
    grid = table.expanded()
    parts: list[str] = []
    for t in grid[row]:
        t = t.strip()
        if t and (not parts or parts[-1] != t):
            parts.append(t)
    return " | ".join(parts)


def _pick_result_column(
    results: list[ColumnInfo], subject_hint: str | None
) -> tuple[ColumnInfo | None, bool]:
    """(고른 열, 시료가 여럿이라 못 골랐는지)."""
    if len(results) == 1:
        return results[0], False
    if not results:
        return None, False
    if subject_hint:
        h = re.sub(r"\s+", "", subject_hint).lower()
        hits = [
            c
            for c in results
            if c.sample_label and ((s := re.sub(r"\s+", "", c.sample_label).lower()) in h or h in s)
        ]
        if len(hits) == 1:
            return hits[0], False
    return None, True


def _detection_limit(
    layout: TableLayout, row: int, value_col: int, nd_dl: float | None, nd_dl_raw: str | None
) -> tuple[float | None, str | None, CellRef | FootnoteRef | None, str | None]:
    """불검출의 검출한계: (값, 표기, 근거, 단위 표기). 못 찾으면 값 None."""
    t = layout.table
    ref_value_cell = CellRef(page=t.page, table_index=t.table_index, row=row, col=value_col)
    if nd_dl is not None:
        return nd_dl, nd_dl_raw, ref_value_cell, None
    grid = t.expanded()
    for col in layout.cols_with(ColumnRole.DETECTION_LIMIT):
        nums = numbers_in(grid[row][col.col])
        if len(nums) == 1:
            ref = CellRef(page=t.page, table_index=t.table_index, row=row, col=col.col)
            return to_float(nums[0]), nums[0], ref, find_unit(grid[row][col.col]) or col.unit
    cell = t.cell_at(row, value_col)
    marks = cell.footnote_marks if cell else []
    footnotes = [t.footnote(m) for m in marks] + [t.footnote("※")]
    for fn in footnotes:
        if fn is None:
            continue
        low = fn.text.lower()
        if not any(w in low for w in _DL_WORDS):
            continue
        nums = numbers_in(fn.text)
        if len(nums) == 1:
            ref = FootnoteRef(page=t.page, table_index=t.table_index, footnote_mark=fn.mark)
            return to_float(nums[0]), nums[0], ref, find_unit(fn.text)
    return None, None, None, None


_LOWER_BOUND_WORDS = ("이하", "미만", "≤", "<", "＜", "≦")


def _limit_bound(layout: TableLayout, row: int) -> tuple[float, str, CellRef, str | None] | None:
    """같은 행 기준 칸의 숫자(불검출의 상한으로 쓸 값). (값, 표기, 근거 칸, 단위 표기)

    기준 칸에 숫자가 하나뿐이고 '이 값 이상이면 해당'인 기준("3.0 이상", "3", "5% 초과")일 때만.
    "2.0 이하"처럼 낮을수록 해당하는 기준이나 숫자가 여럿인 칸(pH)은 쓰지 않는다.
    """
    t = layout.table
    grid = t.expanded()
    for col in layout.cols_with(ColumnRole.LIMIT):
        text = grid[row][col.col]
        nums = numbers_in(text)
        if len(nums) != 1 or any(w in text for w in _LOWER_BOUND_WORDS):
            continue
        value = to_float(nums[0])
        if value <= 0:
            continue
        ref = CellRef(page=t.page, table_index=t.table_index, row=row, col=col.col)
        return value, nums[0], ref, find_unit(text) or col.unit
    return None


def _row_sample(layout: TableLayout, info: RowInfo) -> str | None:
    """시료 이름 열(검체명)의 그 행 글자. 병합 칸이면 위 칸의 이름."""
    cols = layout.cols_with(ColumnRole.SAMPLE)
    if not cols:
        return None
    return layout.table.expanded()[info.row][cols[0].col].strip() or None


_PAREN = re.compile(r"\(([^)]*)\)")


def _unsure_place(layout: TableLayout, info: RowInfo, col: ColumnInfo | None) -> dict:
    """값을 정하지 못한 행의 위치·원문(쪽, 행 글자, 항목 이름, 괄호 속 단위 표기, 결과 칸 글자)."""
    t = layout.table
    place: dict = {
        "page": t.page,
        "quote": _quote(t, info.row),
        "item_raw": (info.item_text or "").strip() or None,
    }
    m = _PAREN.search(info.item_text or "")
    if info.unit_raw:
        place["unit_raw"] = info.unit_raw
    elif m and m.group(1).strip():
        place["unit_raw"] = m.group(1).strip()
    if col is not None:
        cell = t.cell_at(info.row, col.col)
        if cell is not None and cell.text.strip():
            place["value_raw"] = cell.text.strip()
        place["cell_ref"] = CellRef(
            page=t.page, table_index=t.table_index, row=info.row, col=col.col
        )
    return place


def _item_for_row(
    layout: TableLayout,
    info: RowInfo,
    test_item: TestItem,
    col: ColumnInfo,
    multiple_results: bool,
) -> _Candidate:
    t = layout.table
    key = test_item.key
    cell = t.cell_at(info.row, col.col)
    text = cell.text if cell else ""
    parsed = parse_value(text)
    ref = CellRef(page=t.page, table_index=t.table_index, row=info.row, col=col.col)
    base = dict(
        key=key,
        page=t.page,
        quote=_quote(t, info.row),
        item_raw=(info.item_text or "").strip() or None,
        method=info.method,
        sample_label=(col.sample_label if multiple_results else None) or _row_sample(layout, info),
        cell_ref=ref,
    )
    warnings: list[ExtractionWarning] = []

    def ambiguous(note: str, raw: str | None = None, unit: str | None = None) -> _Candidate:
        return _Candidate(
            ExtractedFactItem(
                status=ItemStatus.AMBIGUOUS, value_raw=raw, unit_raw=unit, note=note, **base
            ),
            ("AMBIGUOUS", note),
            warnings,
        )

    if layout.inherited_from is not None:
        warnings.append(
            ExtractionWarning(
                code=WarningCode.TABLE_CONTINUATION_GUESSED,
                message="앞 쪽 표가 이어진 것으로 보고 머리글을 물려받았습니다.",
                key=key,
                page=t.page,
            )
        )
    if cell is not None and cell.confidence is not None and cell.confidence < LOW_CONFIDENCE:
        warnings.append(
            ExtractionWarning(
                code=WarningCode.LOW_QUALITY,
                message=f"글자 인식 신뢰도가 낮습니다({cell.confidence:.2f}).",
                key=key,
                page=t.page,
            )
        )
        return ambiguous("글자 인식 신뢰도가 낮아 값을 정하지 않음", parsed.raw)

    # 단위: 단위 열 → 결과 열 머리글 → 값 칸 안
    unit_raw, unit_ref = info.unit_raw, info.unit_ref
    if unit_raw is None and col.unit:
        unit_raw, unit_ref = col.unit, header_unit_ref(layout, col)
    if unit_raw is None and parsed.unit:
        unit_raw, unit_ref = parsed.unit, ref
    if test_item.unit is None:
        unit_raw, unit_ref = None, None  # pH

    if parsed.kind in ("empty", "text"):
        return ambiguous(f"결과 칸을 값으로 읽을 수 없음: {parsed.raw!r}", parsed.raw or None)

    # 불검출 + 검출한계 없음 + 같은 줄 기준값(단위 없는 숫자) = "이 줄 기준보다 낮다".
    # 기준 칸은 법 기준을 적는 칸이라 원문 단위 표기(오타 포함)와 상관없이 기준 단위로 본다.
    # 검출한계 숫자가 적힌 불검출("<0.01 mg/mL")은 단위가 값을 바꾸므로 아래에서 환산한다.
    if parsed.kind == "nd" and test_item.unit is not None and parsed.detection_limit is None:
        stated = _detection_limit(layout, info.row, col.col, None, None)
        bound = _limit_bound(layout, info.row) if stated[0] is None else None
        if bound is not None and bound[3] is None:
            dl, dl_raw, dl_ref, _ = bound
            same = (
                unit_raw is not None
                and (unit_rule(unit_raw, test_item.unit) or UnitRule(0)).factor == 1
            )
            note = f"불검출. 검출한계가 없어 같은 행 기준 {dl_raw} 미만으로 봄"
            if unit_raw and not same:
                note += f" · 원문 단위 '{unit_raw}'와 상관없이 기준 단위({test_item.unit})로 봄"
            item = ExtractedFactItem(
                status=ItemStatus.FOUND,
                value_raw=parsed.raw,
                unit_raw=unit_raw,
                below_detection_limit=True,
                detection_limit=dl,
                unit_ref=unit_ref,
                detection_limit_ref=dl_ref,
                detection_limit_basis="limit_column",
                note=note,
                **base,
            )
            return _Candidate(item, ("ND", dl), warnings)

    rule = unit_rule(unit_raw, test_item.unit)
    if rule is None:
        warnings.append(
            ExtractionWarning(
                code=WarningCode.UNIT_CONVERSION_FAILED,
                message=f"단위를 환산할 수 없습니다: {unit_raw or '단위 없음'} → {test_item.unit}",
                key=key,
                page=t.page,
            )
        )
        return ambiguous("단위를 확인하지 못함", parsed.number_raw or parsed.raw, unit_raw)
    if rule.assumed:
        warnings.append(
            ExtractionWarning(
                code=WarningCode.UNIT_ASSUMED,
                message=f"{unit_raw}를 {test_item.unit}로 가정해 환산했습니다.",
                key=key,
                page=t.page,
            )
        )

    # 배율이 1이 아닌 환산은 메모에 남긴다(검수 화면이 "환산했어요"로 알린다)
    conv_note = (
        f"단위 환산: {unit_raw} → {test_item.unit} (×{rule.factor:g})"
        if unit_raw and rule.factor != 1 and not rule.assumed
        else None
    )

    if parsed.kind == "nd":
        dl, dl_raw, dl_ref, dl_unit = _detection_limit(
            layout, info.row, col.col, parsed.detection_limit, parsed.detection_limit_raw
        )
        basis = "stated"
        if dl is None:
            bound = _limit_bound(layout, info.row)
            if bound is None:
                return ambiguous(
                    "불검출이지만 검출한계도 같은 행 기준값도 찾지 못함", parsed.raw, unit_raw
                )
            dl, dl_raw, dl_ref, dl_unit = bound
            basis = "limit_column"
        dl_conv = convert(dl, dl_unit or unit_raw, test_item.unit)
        if dl_conv is None:
            return ambiguous("검출한계의 단위를 환산할 수 없음", parsed.raw, unit_raw)
        if basis == "stated":
            dl_note = f"검출한계 표기 {dl_raw}"
        else:
            dl_note = f"불검출. 검출한계가 없어 같은 행 기준 {dl_raw} 미만으로 봄"

        item = ExtractedFactItem(
            status=ItemStatus.FOUND,
            value_raw=parsed.raw,
            unit_raw=unit_raw,
            below_detection_limit=True,
            detection_limit=dl_conv,
            unit_ref=unit_ref,
            detection_limit_ref=dl_ref,
            detection_limit_basis=basis,
            note=f"{dl_note} · {conv_note}" if conv_note else dl_note,
            **base,
        )
        return _Candidate(item, ("ND", dl_conv), warnings)

    assert parsed.value is not None and parsed.number_raw is not None
    value = parsed.value * rule.factor
    item = ExtractedFactItem(
        status=ItemStatus.FOUND,
        value=value,
        comparator=parsed.comparator,
        value_raw=parsed.number_raw,
        unit_raw=unit_raw,
        unit_ref=unit_ref,
        note=conv_note,
        **base,
    )
    return _Candidate(item, ("VAL", value, parsed.comparator), warnings)


def _signature(layout: TableLayout) -> tuple[str, ...]:
    return tuple(c.role.value for c in layout.columns)


def _per_sample_tables(layouts: list[TableLayout]) -> dict[int, list[TableLayout]]:
    """열 구성이 같은 결과 표가 둘 이상이면 시료마다 따로 그린 표로 본다.

    예: "1) 시료A" 아래 표, "2) 시료B" 아래 표.

    쪽 넘김으로 이어진 표는 한 표이므로 뺀다. 돌려주는 값: id(표) → 같은 무리의 다른 표들.
    """
    groups: dict[tuple[str, ...], list[TableLayout]] = {}
    for lay in layouts:
        if lay.inherited_from is not None or lay.table.continued_from is not None:
            continue
        if not any(c.role is ColumnRole.RESULT and c.by_rule for c in lay.columns):
            continue
        groups.setdefault(_signature(lay), []).append(lay)
    out: dict[int, list[TableLayout]] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        for lay in members:
            out[id(lay)] = [m for m in members if m is not lay]
    return out


def _risky_in_sample_tables(
    layout: TableLayout, key: str, per_sample: dict[int, list[TableLayout]]
) -> bool:
    """시료별 표 가운데 하나에서 찾은 항목인데, 다른 표에도 같은 항목이 있거나 읽지 못한 항목 행이
    있으면(글자가 깨져 같은 항목인지 알 수 없음) 어느 시료 값인지 정할 수 없다."""
    others = per_sample.get(id(layout))
    if not others:
        return False
    for other in others:
        icol = item_column(other)
        if icol is None:
            return True
        grid = other.table.expanded()
        for r in range(other.first_data_row, other.table.n_rows):
            text = grid[r][icol].strip()
            if not text or is_section_row(other.table, r):
                continue
            keys = {it.key for it in match_items(text)}
            if key in keys or not keys:
                return True
    return False


def _repeated_header_rows(layout: TableLayout) -> list[int]:
    """데이터 행 가운데 머리글이 다시 나온 행("시험항목 | 단위 | 시험결과"). 시료마다 표를 그렸는데
    표 인식이 한 표로 합친 경우에 생긴다."""
    t = layout.table
    grid = t.expanded()
    out = []
    for r in range(layout.first_data_row, t.n_rows):
        roles = {role_of_header(x) for x in grid[r]} - {None}
        if len(roles) >= 2 and ColumnRole.RESULT in roles:
            out.append(r)
    return out


def _risky_in_blocks(layout: TableLayout, row: int, key: str) -> bool:
    """머리글이 반복되는 표(시료 묶음이 여럿)에서 이 행이 어느 시료 값인지 정할 수 없는가.

    다른 묶음에 같은 항목이 있거나 읽지 못한 항목 행이 있으면 정할 수 없다.
    """
    repeats = _repeated_header_rows(layout)
    if not repeats:
        return False
    t = layout.table
    bounds = [layout.first_data_row, *repeats, t.n_rows]
    blocks = [range(a, b) for a, b in zip(bounds, bounds[1:], strict=False)]
    icol = item_column(layout)
    if icol is None:
        return True
    grid = t.expanded()
    for block in blocks:
        if row in block:
            continue
        for r in block:
            if r in repeats or is_section_row(t, r):
                continue
            text = grid[r][icol].strip()
            if not text:
                continue
            keys = {it.key for it in match_items(text)}
            if key in keys or not keys:
                return True
    return False


def map_test_report(
    layouts: list[TableLayout],
    requested_keys: list[str],
    *,
    subject_hint: str | None = None,
) -> tuple[list[ExtractedFactItem], list[ExtractionWarning]]:
    """요청한 키마다 정확히 하나의 항목을 돌려준다(계약 §3)."""
    found: dict[str, list[_Candidate]] = {k: [] for k in requested_keys}
    warnings: list[ExtractionWarning] = []
    multi_sample_keys: set[str] = set()
    unsure: dict[str, str] = {}
    # 정하지 못한 항목이 원문 어디에 있었는지(검수 화면이 원문 순서 자리에 "읽지 못함"으로 보인다)
    unsure_at: dict[str, dict] = {}
    per_sample = _per_sample_tables(layouts)
    blocked: set[str] = set()

    for layout in layouts:
        t = layout.table
        results = [c for c in layout.cols_with(ColumnRole.RESULT) if c.by_rule]
        if not results:
            continue
        col, multi = _pick_result_column(results, subject_hint)
        sections = section_groups(layout)
        for r in range(layout.first_data_row, t.n_rows):
            if is_section_row(t, r):
                continue
            info = row_info(layout, r, sections)
            if not info.items:
                continue
            unit_hint = info.unit_raw or (col.unit if col else None)
            if unit_hint is None and col is not None:
                cell = t.cell_at(r, col.col)
                unit_hint = find_unit(cell.text) if cell else None
            items, notes = candidate_items(info, unit_hint)
            items = [it for it in items if it.key in found]
            if not items:
                continue
            if len(items) > 1 or notes:
                for it in items:
                    unsure[it.key] = (
                        notes[0]
                        if notes
                        else (f"'{info.item_text}' 행이 용출·함량 중 어느 쪽인지 정하지 못함")
                    )
                    unsure_at.setdefault(it.key, _unsure_place(layout, info, col))
                continue
            test_item = items[0]
            if col is None:
                multi_sample_keys.add(test_item.key)
                continue
            if _risky_in_sample_tables(layout, test_item.key, per_sample) or _risky_in_blocks(
                layout, r, test_item.key
            ):
                blocked.add(test_item.key)  # 다른 표에서 찾은 같은 항목 값도 쓰지 않는다
                continue
            found[test_item.key].append(
                _item_for_row(layout, info, test_item, col, multiple_results=len(results) > 1)
            )

    out: list[ExtractedFactItem] = []
    for key in requested_keys:
        cands = found[key]
        if key in blocked or (key in multi_sample_keys and not cands):
            out.append(
                ExtractedFactItem(
                    key=key,
                    status=ItemStatus.AMBIGUOUS,
                    note=(
                        "시료별 표가 여럿이라 어느 시료 값인지 정하지 못함"
                        if key in blocked
                        else "시료가 여럿이라 어느 열인지 정하지 못함"
                    ),
                )
            )
            warnings.append(
                ExtractionWarning(
                    code=WarningCode.MULTIPLE_SAMPLES,
                    message="한 서류에 시료가 여럿이라 이 건의 시료를 골라야 합니다.",
                    key=key,
                )
            )
            continue
        if not cands:
            if key in unsure:
                out.append(
                    ExtractedFactItem(
                        key=key,
                        status=ItemStatus.AMBIGUOUS,
                        note=unsure[key],
                        **unsure_at.get(key, {}),
                    )
                )
            else:
                out.append(ExtractedFactItem(key=key, status=ItemStatus.NOT_FOUND))
            continue
        sigs = {c.signature for c in cands}
        if len(sigs) > 1:
            notes = "; ".join(f"{c.item.page}쪽 '{c.item.quote}'" for c in cands)
            out.append(
                ExtractedFactItem(
                    key=key,
                    status=ItemStatus.AMBIGUOUS,
                    note=f"같은 항목이 서로 다른 값으로 여러 번 나옴: {notes}"[:500],
                )
            )
            continue
        first = cands[0]
        out.append(first.item)
        warnings.extend(first.warnings)
    return out, warnings


__all__ = ["map_test_report", "BY_KEY", "Comparator", "LOW_CONFIDENCE"]
