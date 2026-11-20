"""글자 층 PDF 표 추출(app/reading/pdf_tables.py)과 공용 도우미 테스트."""

from __future__ import annotations

import pytest

from app.reading.common import parse_footnote_line, split_cell_marks
from app.reading.pdf_tables import PdfReadFailed, extract_pdf_tables, has_text_layer
from tests import pdf_fixtures as fx

# ── 공용 도우미 ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "text", "marks"),
    [
        ("ND*", "ND", ["*"]),
        ("ND **", "ND", ["**"]),
        ("0.5 1)", "0.5", ["1"]),
        ("0.51)", "0.51)", []),  # 숫자에 바로 붙은 "1)"은 값의 일부로 둔다
        ("0.12", "0.12", []),
        ("ND※", "ND", ["※"]),
        ("ND (2)", "ND", ["2"]),
        ("  ND * ", "ND", ["*"]),
    ],
)
def test_split_cell_marks(raw, text, marks):
    assert split_cell_marks(raw) == (text, marks)


@pytest.mark.parametrize(
    ("line", "mark", "text"),
    [
        ("* 검출한계 0.01 mg/L", "*", "검출한계 0.01 mg/L"),
        ("(1) 정량한계 0.005", "1", "정량한계 0.005"),
        ("1) 정량한계 0.005", "1", "정량한계 0.005"),
        ("주) 시료는 의뢰인이 채취", "※", "시료는 의뢰인이 채취"),
        ("주2) 비고", "2", "비고"),
        ("※ 참고용", "※", "참고용"),
    ],
)
def test_parse_footnote_line(line, mark, text):
    note = parse_footnote_line(line)
    assert note is not None
    assert (note.mark, note.text) == (mark, text)


@pytest.mark.parametrize("line", ["납(Pb) ES 06402.1 0.12 mg/L 3", "시험성적서", ""])
def test_parse_footnote_line_rejects(line):
    assert parse_footnote_line(line) is None


# ── PDF 표 추출 ────────────────────────────────────────────


def test_simple_table_cells_marks_and_footnote():
    ex = extract_pdf_tables(fx.simple_report_pdf())
    assert ex.source == "pdf_text_layer"
    assert ex.backend == "pdfplumber"
    assert ex.warnings == []
    assert len(ex.pages) == 1
    page = ex.pages[0]
    assert "시험성적서" in page.text
    assert page.width == pytest.approx(595.28, abs=0.1)
    assert page.height == pytest.approx(841.89, abs=0.1)

    assert len(ex.tables) == 1
    t = ex.tables[0]
    assert (t.page, t.table_index, t.n_rows, t.n_cols) == (1, 0, 3, 5)
    assert t.expanded() == [
        ["시험항목", "시험방법", "결과", "단위", "기준"],
        ["납(Pb)", "ES 06402.1", "0.12", "mg/L", "3"],
        ["카드뮴", "ES 06402.1", "ND", "mg/L", "0.3"],
    ]
    nd = t.cell_at(2, 2)
    assert nd is not None and nd.footnote_marks == ["*"]
    assert t.cell_at(1, 2).footnote_marks == []
    assert all(not c.is_header and c.confidence is None for c in t.cells)

    note = t.footnote("*")
    assert note is not None and note.text == "검출한계 0.01 mg/L"
    assert t.continued_from is None

    x0, y0, x1, y1 = t.bbox
    assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
    for c in t.cells:
        cx0, cy0, cx1, cy1 = c.bbox
        assert x0 - 1e-6 <= cx0 < cx1 <= x1 + 1e-6
        assert y0 - 1e-6 <= cy0 < cy1 <= y1 + 1e-6


def test_vertically_merged_cell_is_one_anchor():
    ex = extract_pdf_tables(fx.merged_cell_pdf())
    (t,) = ex.tables
    assert (t.n_rows, t.n_cols) == (5, 6)
    assert len(t.cells) == 5 * 6 - 2  # 병합으로 가려진 두 자리는 칸이 없다
    anchor = t.cell_at(1, 0)
    assert anchor is not None
    assert (anchor.row, anchor.col, anchor.row_span, anchor.col_span) == (1, 0, 3, 1)
    assert anchor.text == "용출시험"
    assert t.cell_at(3, 0) is anchor
    grid = t.expanded()
    assert [grid[r][0] for r in range(5)] == [
        "구분",
        "용출시험",
        "용출시험",
        "용출시험",
        "함량시험",
    ]
    assert grid[2][1:] == ["카드뮴", "ES 06402.1", "ND", "mg/L", "0.3"]
    # 병합 칸 bbox는 세 행을 덮는다
    assert anchor.bbox[3] == pytest.approx(t.cell_at(3, 1).bbox[3], abs=1e-3)


def test_two_page_table_continuation():
    ex = extract_pdf_tables(fx.two_page_table_pdf())
    assert [p.page for p in ex.pages] == [1, 2]
    assert len(ex.tables) == 2
    first, second = ex.tables
    assert (first.page, second.page) == (1, 2)
    assert first.n_rows == 6 and second.n_rows == 4
    assert first.continued_from is None
    assert second.continued_from == first.ref
    assert second.expanded()[0][0] == "항목6"


def test_borderless_table_is_guessed_with_warning():
    ex = extract_pdf_tables(fx.borderless_table_pdf())
    assert len(ex.tables) == 1
    t = ex.tables[0]
    assert (t.n_rows, t.n_cols) == (6, 5)
    assert t.expanded()[0] == ["시험항목", "시험방법", "결과", "단위", "기준"]
    assert t.expanded()[3] == ["항목3", "ES06402", "0.3", "mg/L", "3"]
    assert any("1쪽" in w and "선 없는 표" in w for w in ex.warnings)


def test_plain_text_page_is_not_a_table():
    ex = extract_pdf_tables(fx.plain_text_pdf())
    assert ex.tables == []
    assert ex.warnings == []
    assert "폐수처리 오니" in ex.pages[0].text


def test_has_text_layer():
    assert has_text_layer(fx.simple_report_pdf()) is True
    assert has_text_layer(fx.scanned_like_pdf()) is False


def test_scanned_like_pdf_has_no_tables():
    ex = extract_pdf_tables(fx.scanned_like_pdf())
    assert ex.tables == []
    assert ex.pages[0].text == ""


@pytest.mark.parametrize("data", [b"not a pdf", b"%PDF-1.4\n garbage", b""])
def test_corrupt_bytes_raise(data):
    with pytest.raises(PdfReadFailed):
        extract_pdf_tables(data)
    with pytest.raises(PdfReadFailed):
        has_text_layer(data)
