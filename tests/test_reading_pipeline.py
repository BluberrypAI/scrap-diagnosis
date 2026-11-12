"""시험성적서 읽기: 열 역할 → 대응 → 표 검증(T1~T10) → 흐름. 실제 Azure는 부르지 않는다."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.document import (
    DocumentContent,
    ErrorCode,
    ExtractedFactItem,
    ItemStatus,
    WarningCode,
    item_to_value,
)
from app.domain.ranges import NumRange
from app.domain.tables import CellRef, Footnote, PageInfo, TableCell, TableExtraction, TableGrid
from app.reading import azure_tables
from app.reading.columns import ColumnRole, analyze_table, analyze_tables
from app.reading.mapper import map_test_report
from app.reading.pipeline import read_test_report
from app.reading.table_guard import validate_table_item
from app.reading.values import parse_value
from tests.pdf_fixtures import _build, _table, scanned_like_pdf, simple_report_pdf

OFF = Settings(_env_file=None, allow_document_ocr=False)
ON = Settings(
    _env_file=None,
    allow_document_ocr=True,
    azure_docintel_endpoint="https://example.invalid",
    azure_docintel_api_key="test",
)


def grid(
    rows: list[list[str | None]],
    *,
    spans: dict[tuple[int, int], tuple[int, int]] | None = None,
    footnotes: list[Footnote] | None = None,
    marks: dict[tuple[int, int], list[str]] | None = None,
    confidence: dict[tuple[int, int], float] | None = None,
    page: int = 1,
    table_index: int = 0,
) -> TableGrid:
    """None은 병합으로 덮인 자리. spans[(r, c)] = (row_span, col_span)."""
    spans, marks, confidence = spans or {}, marks or {}, confidence or {}
    cells = []
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            if text is None:
                continue
            rs, cs = spans.get((r, c), (1, 1))
            cells.append(
                TableCell(
                    row=r,
                    col=c,
                    text=text,
                    row_span=rs,
                    col_span=cs,
                    footnote_marks=marks.get((r, c), []),
                    confidence=confidence.get((r, c)),
                )
            )
    return TableGrid(
        page=page,
        table_index=table_index,
        n_rows=len(rows),
        n_cols=len(rows[0]),
        cells=cells,
        footnotes=footnotes or [],
        source="pdf_text_layer",
    )


def facts_of(tables: list[TableGrid], keys: list[str], subject: str | None = None):
    layouts = analyze_tables(tables)
    items, warnings = map_test_report(
        [layouts[k] for k in sorted(layouts)], keys, subject_hint=subject
    )
    return {it.key: it for it in items}, warnings, layouts


BASIC = [
    ["시험항목", "시험방법", "결과", "단위", "기준"],
    ["납(Pb)", "ES 06402.1", "0.12", "mg/L", "3"],
    ["카드뮴", "ES 06402.1", "ND", "mg/L", "0.3"],
    ["수소이온농도", "ES 06304.1", "7.2", "-", "-"],
    ["기름성분", "ES 06302.1b", "3.5", "%", "5 이상"],
]


# ---- 값 해석 ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind", "value", "cmp"),
    [
        ("0.12", "number", 0.12, "EQ"),
        ("1,234.5", "number", 1234.5, "EQ"),
        ("<0.01", "number", 0.01, "LT"),
        ("0.01 미만", "number", 0.01, "LT"),
        ("ND", "nd", None, "EQ"),
        ("불검출(<0.005)", "nd", None, "EQ"),
        ("-", "empty", None, "EQ"),
        ("0.1~0.2", "text", None, "EQ"),
        ("약 0.1", "text", None, "EQ"),
    ],
)
def test_parse_value(text, kind, value, cmp):
    p = parse_value(text)
    assert p.kind == kind
    assert p.value == value
    assert p.comparator.value == cmp


def test_parse_value_nd_detection_limit_in_cell():
    assert parse_value("불검출(<0.005)").detection_limit == 0.005


# ---- 열 역할 ----------------------------------------------------------------------------------


def test_column_roles_basic():
    lay = analyze_table(grid(BASIC))
    roles = [c.role for c in lay.columns]
    assert roles == [
        ColumnRole.ITEM,
        ColumnRole.METHOD,
        ColumnRole.RESULT,
        ColumnRole.UNIT,
        ColumnRole.LIMIT,
    ]
    assert lay.header_rows == [0]


def test_method_word_containing_gijun_is_method_not_limit():
    lay = analyze_table(grid([["항목", "시험기준", "결과"], ["납", "ES 06402.1", "0.1"]]))
    assert lay.columns[1].role is ColumnRole.METHOD


def test_data_row_with_judgement_word_is_not_header():
    lay = analyze_table(grid([["항목", "결과", "판정"], ["기름성분", "3.5", "적합"]]))
    assert lay.header_rows == [0]


# ---- 대응 -------------------------------------------------------------------------------------


def test_basic_mapping():
    t = grid(BASIC, footnotes=[Footnote(mark="※", text="ND: 검출한계 0.01 mg/L 미만")])
    facts, _, _ = facts_of([t], ["leach_pb", "leach_cd", "ph", "oil_content_pct", "leach_hg"])
    pb = facts["leach_pb"]
    assert pb.status is ItemStatus.FOUND and pb.value == 0.12
    assert pb.cell_ref == CellRef(page=1, table_index=0, row=1, col=2)
    assert pb.quote == "납(Pb) | ES 06402.1 | 0.12 | mg/L | 3"
    cd = facts["leach_cd"]
    assert cd.status is ItemStatus.FOUND and cd.below_detection_limit and cd.detection_limit == 0.01
    assert facts["ph"].value == 7.2 and facts["ph"].unit_raw is None
    assert facts["oil_content_pct"].value == 3.5
    assert facts["leach_hg"].status is ItemStatus.NOT_FOUND


def test_nd_without_detection_limit_is_ambiguous():
    # 검출한계도 기준 열도 없으면 값을 정하지 않는다
    rows = [r[:4] for r in BASIC]
    facts, _, _ = facts_of([grid(rows)], ["leach_cd"])
    assert facts["leach_cd"].status is ItemStatus.AMBIGUOUS


def test_nd_without_detection_limit_uses_limit_column_in_basic_table():
    facts, _, _ = facts_of([grid(BASIC)], ["leach_cd"])
    cd = facts["leach_cd"]
    assert cd.status is ItemStatus.FOUND and cd.detection_limit == 0.3
    assert cd.detection_limit_basis == "limit_column"


def test_nd_detection_limit_from_marked_footnote_and_column():
    rows = [
        ["시험항목", "결과", "단위", "검출한계"],
        ["납", "ND", "mg/L", "0.02"],
        ["수은", "ND", "mg/L", ""],
    ]
    t = grid(
        rows, marks={(2, 1): ["1"]}, footnotes=[Footnote(mark="1", text="정량한계 0.0005 mg/L")]
    )
    facts, _, layouts = facts_of([t], ["leach_pb", "leach_hg"])
    assert facts["leach_pb"].detection_limit == 0.02
    assert facts["leach_hg"].detection_limit == 0.0005
    for it in facts.values():
        assert validate_table_item(it, layouts) == []


def test_unit_from_result_header():
    t = grid([["시험항목", "결과(mg/L)"], ["비소", "0.05"]])
    facts, _, layouts = facts_of([t], ["leach_as"])
    assert facts["leach_as"].value == 0.05 and facts["leach_as"].unit_raw == "mg/L"
    assert validate_table_item(facts["leach_as"], layouts) == []


def test_unit_conversion_ug_per_l():
    t = grid([["시험항목", "결과", "단위"], ["수은", "2", "μg/L"]])
    facts, _, layouts = facts_of([t], ["leach_hg"])
    assert facts["leach_hg"].value == pytest.approx(0.002)
    assert validate_table_item(facts["leach_hg"], layouts) == []


def test_group_from_merged_column_separates_leach_and_content():
    rows = [
        ["구분", "시험항목", "결과", "단위"],
        ["함량시험", "납", "120", "mg/kg"],
        ["용출시험", "납", "0.4", "mg/L"],
        [None, "구리", "1.1", "mg/L"],
    ]
    t = grid(rows, spans={(2, 0): (2, 1)})
    facts, _, layouts = facts_of([t], ["leach_pb", "leach_cu"])
    assert facts["leach_pb"].value == 0.4
    assert facts["leach_cu"].value == 1.1
    assert all(validate_table_item(it, layouts) == [] for it in facts.values())


def test_section_row_sets_group():
    rows = [
        ["시험항목", "결과", "단위"],
        ["함유량 시험", None, None],
        ["납", "120", "mg/kg"],
        ["용출 시험", None, None],
        ["납", "0.4", "mg/L"],
    ]
    t = grid(rows, spans={(1, 0): (1, 3), (3, 0): (1, 3)})
    facts, _, layouts = facts_of([t], ["leach_pb"])
    assert facts["leach_pb"].value == 0.4
    assert validate_table_item(facts["leach_pb"], layouts) == []


def test_pcb_without_group_is_ambiguous():
    t = grid([["시험항목", "결과", "단위"], ["PCB", "0.002", "mg/L"]])
    facts, _, _ = facts_of([t], ["pcb_mg_l", "pcb_leach_mg_l"])
    assert facts["pcb_mg_l"].status is ItemStatus.AMBIGUOUS
    assert facts["pcb_leach_mg_l"].status is ItemStatus.AMBIGUOUS


def test_metal_with_unknown_group_and_mg_per_kg_is_not_leach():
    t = grid([["시험항목", "결과", "단위"], ["납", "120", "mg/kg"]])
    facts, _, _ = facts_of([t], ["leach_pb"])
    assert facts["leach_pb"].status is ItemStatus.NOT_FOUND


def test_multiple_samples_need_subject():
    rows = [
        ["시험항목", "결과", None, "단위"],
        ["", "시료 A", "시료 B", ""],
        ["납", "0.1", "0.9", "mg/L"],
    ]
    t = grid(rows, spans={(0, 1): (1, 2)})
    facts, warnings, _ = facts_of([t], ["leach_pb"])
    assert facts["leach_pb"].status is ItemStatus.AMBIGUOUS
    assert any(w.code is WarningCode.MULTIPLE_SAMPLES for w in warnings)
    facts, _, layouts = facts_of([t], ["leach_pb"], subject="시료B 폐유 슬러지")
    assert facts["leach_pb"].value == 0.9 and facts["leach_pb"].sample_label == "시료 B"
    assert validate_table_item(facts["leach_pb"], layouts) == []


def test_same_item_different_values_is_ambiguous():
    a = grid([["시험항목", "결과", "단위"], ["납", "0.1", "mg/L"]])
    b = grid([["시험항목", "결과", "단위"], ["납", "0.2", "mg/L"]], page=2)
    facts, _, _ = facts_of([a, b], ["leach_pb"])
    assert facts["leach_pb"].status is ItemStatus.AMBIGUOUS


def test_unknown_header_column_is_not_used():
    t = grid([["시험항목", "측정 1회차"], ["납", "0.1"]])
    facts, _, _ = facts_of([t], ["leach_pb"])
    assert facts["leach_pb"].status is ItemStatus.NOT_FOUND


def test_low_ocr_confidence_is_ambiguous():
    rows = [["시험항목", "결과", "단위"], ["납", "0.01", "mg/L"]]
    facts, warnings, _ = facts_of([grid(rows, confidence={(1, 1): 0.5})], ["leach_pb"])
    assert facts["leach_pb"].status is ItemStatus.AMBIGUOUS
    assert any(w.code is WarningCode.LOW_QUALITY for w in warnings)


# ---- 표 검증: 대응 층이 틀린 값을 냈을 때 ------------------------------------------------------


def _found(**kw) -> ExtractedFactItem:
    base = dict(
        key="leach_pb",
        status=ItemStatus.FOUND,
        page=1,
        quote="납",
        unit_raw="mg/L",
        unit_ref=CellRef(page=1, table_index=0, row=1, col=3),
    )
    base.update(kw)
    return ExtractedFactItem(**base)


def test_guard_rejects_limit_column_value():
    layouts = analyze_tables([grid(BASIC)])
    bad = _found(value=3.0, value_raw="3", cell_ref=CellRef(page=1, table_index=0, row=1, col=4))
    reasons = validate_table_item(bad, layouts)
    assert any(r.startswith("T3") for r in reasons)


def test_guard_rejects_invented_number_and_wrong_row():
    layouts = analyze_tables([grid(BASIC)])
    invented = _found(
        value=0.13, value_raw="0.13", cell_ref=CellRef(page=1, table_index=0, row=1, col=2)
    )
    assert any(r.startswith("T2") for r in validate_table_item(invented, layouts))
    wrong_row = _found(
        value=7.2,
        value_raw="7.2",
        cell_ref=CellRef(page=1, table_index=0, row=3, col=2),
        unit_ref=None,
        unit_raw=None,
    )
    assert any(r.startswith("T4") for r in validate_table_item(wrong_row, layouts))


def test_guard_rejects_bad_coordinates_and_bad_conversion():
    layouts = analyze_tables([grid(BASIC)])
    missing = _found(
        value=0.12, value_raw="0.12", cell_ref=CellRef(page=9, table_index=0, row=1, col=2)
    )
    assert validate_table_item(missing, layouts) == ["T1: 가리키는 표가 없음"]
    scaled = _found(
        value=120.0, value_raw="0.12", cell_ref=CellRef(page=1, table_index=0, row=1, col=2)
    )
    assert any(r.startswith("T7") for r in validate_table_item(scaled, layouts))


def test_guard_rejects_detection_limit_not_in_source():
    t = grid(BASIC, footnotes=[Footnote(mark="※", text="검출한계 0.01 mg/L")])
    layouts = analyze_tables([t])
    from app.domain.tables import FootnoteRef

    bad = _found(
        key="leach_cd",
        value=None,
        value_raw="ND",
        below_detection_limit=True,
        detection_limit=0.5,
        cell_ref=CellRef(page=1, table_index=0, row=2, col=2),
        unit_ref=CellRef(page=1, table_index=0, row=2, col=3),
        detection_limit_ref=FootnoteRef(page=1, table_index=0, footnote_mark="※"),
    )
    assert any(r.startswith("T8") for r in validate_table_item(bad, layouts))


# ---- 계약 확장 --------------------------------------------------------------------------------


def test_contract_accepts_tables_and_cell_refs():
    content = DocumentContent(tables=[grid(BASIC)])
    assert content.tables[0].n_cols == 5
    it = _found(value=0.12, value_raw="0.12", cell_ref=CellRef(page=1, table_index=0, row=1, col=2))
    again = ExtractedFactItem.model_validate(it.model_dump())
    assert again.cell_ref == it.cell_ref


# ---- 흐름(PDF·Azure 경로) ---------------------------------------------------------------------


def test_pipeline_local_pdf():
    rep = read_test_report(
        simple_report_pdf(), "report.pdf", settings=OFF, requested_keys=["leach_pb", "leach_cd"]
    )
    facts = {f.key: f for f in rep.result.facts}
    assert facts["leach_pb"].status is ItemStatus.FOUND and facts["leach_pb"].value == 0.12
    assert facts["leach_cd"].below_detection_limit and facts["leach_cd"].detection_limit == 0.01
    assert rep.rejected == {}
    assert rep.route[0].startswith("pdfplumber")


def test_pipeline_pdf_with_merged_group_column():
    rows = [
        ["구분", "시험항목", "시험방법", "결과", "단위", "기준"],
        ["용출시험", "납", "ES 06402.1", "0.4", "mg/L", "3"],
        ["", "6가크롬", "ES 06407.1", "ND(<0.01)", "mg/L", "1.5"],
        ["함량시험", "납", "ES 06900.1", "120", "mg/kg", "-"],
    ]
    pdf = _build([_table(rows, [("SPAN", (0, 1), (0, 2))])])
    rep = read_test_report(pdf, "r.pdf", settings=OFF, requested_keys=["leach_pb", "leach_cr6"])
    facts = {f.key: f for f in rep.result.facts}
    assert facts["leach_pb"].value == 0.4
    assert facts["leach_cr6"].below_detection_limit and facts["leach_cr6"].detection_limit == 0.01


def test_pipeline_scanned_pdf_without_ocr():
    rep = read_test_report(scanned_like_pdf(), "scan.pdf", settings=OFF)
    assert rep.result.errors[0].code is ErrorCode.EMPTY_CONTENT
    assert all(f.status is ItemStatus.NOT_FOUND for f in rep.result.facts)


def test_pipeline_scanned_pdf_goes_to_azure(monkeypatch):
    fake = TableExtraction(
        source="ocr",
        pages=[PageInfo(page=1, text="시험성적서")],
        tables=[grid([["시험항목", "결과", "단위"], ["카드뮴", "0.05", "mg/L"]])],
        backend="azure-prebuilt-layout",
    )
    calls = []

    def fake_analyze(data, ct, *, settings, client=None):
        calls.append(ct)
        return fake

    monkeypatch.setattr(azure_tables, "analyze_layout", fake_analyze)
    rep = read_test_report(scanned_like_pdf(), "scan.pdf", settings=ON, requested_keys=["leach_cd"])
    assert calls == ["application/pdf"]
    assert rep.result.facts[0].value == 0.05


def test_pipeline_image_requires_ocr():
    rep = read_test_report(b"\x89PNG....", "photo.png", settings=OFF)
    assert rep.result.errors[0].code is ErrorCode.EMPTY_CONTENT


def test_pipeline_unsupported_format():
    rep = read_test_report(b"hello", "a.docx", settings=OFF)
    assert rep.result.errors[0].code is ErrorCode.UNSUPPORTED_FORMAT


def test_pipeline_stacked_rows_in_one_cell():
    """선 없이 한 칸에 여러 줄로 쌓인 항목을 줄마다 나눠 읽는다. 기준 열은 결과로 읽지 않는다."""
    from tests.pdf_fixtures import stacked_rows_pdf

    rep = read_test_report(stacked_rows_pdf(), "r.pdf", settings=OFF)
    lay = next(iter(rep.layouts.values()))
    roles = [c.role for c in lay.columns]
    assert roles == [ColumnRole.SAMPLE, ColumnRole.ITEM, ColumnRole.LIMIT, ColumnRole.RESULT]
    grid = lay.table.expanded()
    assert ["S-1", "구리(mg/L)", "3.0 이상", "0.021"] in grid
    assert any(r[1] == "pH" and "폐알칼리" in r[2] and r[3] == "8.05" for r in grid)
    facts = {f.key: f for f in rep.result.facts}
    assert facts["leach_cu"].status is ItemStatus.FOUND and facts["leach_cu"].value == 0.021
    assert facts["leach_cu"].sample_label == "S-1"
    assert facts["sludge_water_pct"].value == 74.4
    assert facts["oil_content_pct"].value == 0.1 and facts["ph"].value == 8.05
    # 검출한계 없는 불검출은 0이 아니라 같은 행 기준값 미만
    assert facts["leach_pb"].below_detection_limit and facts["leach_pb"].detection_limit == 3.0
    assert rep.rejected == {}


def test_nd_without_detection_limit_uses_same_row_limit():
    """검출한계가 없는 불검출은 같은 행 기준값을 상한으로 쓴다(값을 0으로 짓지 않는다)."""
    from tests.pdf_fixtures import stacked_rows_pdf

    rep = read_test_report(stacked_rows_pdf(), "r.pdf", settings=OFF)
    pb = next(f for f in rep.result.facts if f.key == "leach_pb")
    assert pb.status is ItemStatus.FOUND and pb.value is None
    assert pb.below_detection_limit and pb.detection_limit == 3.0
    assert pb.detection_limit_basis == "limit_column"
    assert pb.detection_limit_ref is not None and pb.detection_limit_ref.col == 2
    assert "기준 3.0 미만" in pb.note
    assert item_to_value(pb) == NumRange(hi=3.0, hi_inc=False)
    assert rep.rejected == {}


@pytest.mark.parametrize(
    "limit, expect",
    [("3.0 이상", 3.0), ("3", 3.0), ("2.0 이하", None), ("-", None), ("0.1~0.3", None)],
)
def test_limit_bound_only_for_upper_limits(limit, expect):
    t = grid([["항목", "기준", "결과"], ["납(mg/L)", limit, "불검출"]])
    lay = analyze_table(t)
    items, _ = map_test_report([lay], ["leach_pb"], subject_hint=None)
    it = items[0]
    if expect is None:
        assert it.status is ItemStatus.AMBIGUOUS
    else:
        assert it.detection_limit == expect and it.detection_limit_basis == "limit_column"


def test_guard_rejects_limit_basis_pointing_at_other_column():
    t = grid([["항목", "기준", "결과", "비고"], ["납(mg/L)", "3.0 이상", "불검출", "3.0"]])
    lay = analyze_table(t)
    items, _ = map_test_report([lay], ["leach_pb"], subject_hint=None)
    it = items[0].model_copy(
        update={"detection_limit_ref": CellRef(page=1, table_index=0, row=1, col=3)}
    )
    reasons = validate_table_item(it, {(1, 0): lay})
    assert any("기준 열이 아님" in r for r in reasons)
    plain = items[0].model_copy(update={"detection_limit_basis": None})
    assert any("검출한계 열이 아님" in r for r in validate_table_item(plain, {(1, 0): lay}))


def _sample_table(index: int, item: str, value: str) -> TableGrid:
    return grid(
        [["시험항목", "단위", "시험결과", "비고"], [item, "mg/L", value, "-"]], table_index=index
    )


def test_per_sample_tables_with_unreadable_item_are_ambiguous():
    """시료별 표 중 한 표의 항목만 읽혔으면(나머지는 글자가 깨짐) 값을 정하지 않는다."""
    tables = [
        _sample_table(0, "밥", "3.297"),  # OCR이 '납'을 잘못 읽음
        _sample_table(1, "남", "7.287"),
        _sample_table(2, "납", "22.288"),
    ]
    facts, warnings, _ = facts_of(tables, ["leach_pb"])
    assert facts["leach_pb"].status is ItemStatus.AMBIGUOUS
    assert "시료별 표" in facts["leach_pb"].note
    assert any(w.code is WarningCode.MULTIPLE_SAMPLES for w in warnings)


def test_same_shape_tables_with_different_known_items_are_fine():
    tables = [_sample_table(0, "납", "0.12"), _sample_table(1, "구리", "1.5")]
    facts, _, _ = facts_of(tables, ["leach_pb", "leach_cu"])
    assert facts["leach_pb"].value == 0.12 and facts["leach_cu"].value == 1.5


def test_repeated_header_rows_in_one_table_are_ambiguous():
    """시료별 표를 표 인식이 한 표로 합친 경우: 머리글이 표 중간에 반복된다."""
    t = grid(
        [
            ["시험항목", "단위", "시험결과", "비고"],
            ["밥", "mg/L", "3.297", "-"],
            ["2) HMC-7", "", "", ""],
            ["시험항목", "단위", "시험결과", "비고"],
            ["납", "mg/L", "22.288", "-"],
        ]
    )
    facts, _, _ = facts_of([t], ["leach_pb"])
    assert facts["leach_pb"].status is ItemStatus.AMBIGUOUS


def test_unread_item_keeps_place_raw_name_and_unit():
    """단위 표기가 달라 정하지 못한 항목도 원문 위치·항목 이름·단위 표기를 남긴다(검수 화면용)."""
    rows = [
        ["시험항목", "결과", "기준"],
        ["납(mg/L)", "불검출", "3.0 이상"],
        ["카드뮴(ppt)", "불검출", "0.3 이상"],
        ["TCE(mg/L)", "불검출", "0.3 이상"],
    ]
    rep = read_test_report(_build([_table(rows)]), "r.pdf", "application/pdf", settings=Settings())
    by = {it.key: it for it in rep.result.facts}
    cd = by["leach_cd"]
    assert cd.status is ItemStatus.AMBIGUOUS
    assert (cd.page, cd.item_raw, cd.unit_raw, cd.value_raw) == (
        1,
        "카드뮴(ppt)",
        "ppt",
        "불검출",
    )
    assert cd.cell_ref is not None and cd.cell_ref.row == 2
    assert by["leach_tce"].item_raw == "TCE(mg/L)"


def test_mg_per_ml_is_converted_with_note():
    """mg/mL은 ×1000으로 mg/L에 환산하고, 환산했다고 메모에 남긴다."""
    rows = [
        ["시험항목", "결과", "기준"],
        ["구리(mg/mL)", "0.002", "3.0 이상"],
        ["카드뮴(mg/mL)", "불검출", "0.3 이상"],
    ]
    rep = read_test_report(_build([_table(rows)]), "r.pdf", "application/pdf", settings=Settings())
    by = {it.key: it for it in rep.result.facts}
    cu, cd = by["leach_cu"], by["leach_cd"]
    assert cu.status is ItemStatus.FOUND and cu.value == pytest.approx(2.0)
    assert "단위 환산: mg/mL → mg/L (×1000)" in (cu.note or "")
    # 불검출 + 같은 줄 기준값도 같은 단위로 본다(0.3 mg/mL = 300 mg/L)
    assert cd.status is ItemStatus.FOUND and cd.detection_limit == pytest.approx(300)
    assert "단위 환산" in (cd.note or "")


@pytest.mark.parametrize(
    ("text", "target", "factor"),
    [
        ("카드뮴(mg/mL)", "mg/L", 1000),
        ("㎎/mL", "mg/L", 1000),
        ("ug/mL", "mg/L", 1),
        ("ng/mL", "mg/L", 0.001),
        ("ng/L", "mg/L", 0.000001),
        ("mg/dL", "mg/L", 10),
        ("g/kg", "%", 0.1),
        ("mg/g", "%", 0.1),
        ("μg/g", "%", 0.0001),
        ("g/100g", "%", 1),
    ],
)
def test_same_dimension_units_convert(text, target, factor):
    from app.reading.units import convert, find_unit

    assert convert(1, find_unit(text), target) == pytest.approx(factor)


@pytest.mark.parametrize(("text", "target"), [("mg/m3", "mg/L"), ("mg/L", "%"), ("%", "mg/L")])
def test_units_needing_density_or_unknown_are_not_converted(text, target):
    from app.reading.units import convert, find_unit

    assert convert(1, find_unit(text), target) is None
