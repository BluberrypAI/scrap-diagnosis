"""Azure layout 백엔드 변환 테스트. 실제 서비스는 부르지 않는다(가짜 결과·가짜 클라이언트)."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from app.config import Settings
from app.domain.tables import TableRef
from app.reading.azure_tables import (
    OcrDisabled,
    OcrFailed,
    analyze_layout,
    convert_layout_result,
)


def _poly(x0, y0, x1, y1):
    return [x0, y0, x1, y0, x1, y1, x0, y1]


class _Doc:
    """content 문자열에 단어를 쌓아 span을 계산하는 가짜 결과 작성기."""

    def __init__(self):
        self.content = ""
        self.words: dict[int, list] = {}

    def word(self, page: int, text: str, conf: float = 0.99):
        offset = len(self.content)
        self.content += text + " "
        self.words.setdefault(page, []).append(
            NS(content=text, confidence=conf, span=NS(offset=offset, length=len(text)))
        )
        return NS(offset=offset, length=len(text))

    def cell(self, page, row, col, text, box, *, kind=None, rs=None, cs=None, conf=0.99):
        spans = [self.word(page, t, conf) for t in text.split()]
        return NS(
            kind=kind,
            row_index=row,
            column_index=col,
            row_span=rs,
            column_span=cs,
            content=text,
            bounding_regions=[NS(page_number=page, polygon=_poly(*box))],
            spans=spans,
        )


def _page(number, lines, words, width=8.5, height=11.0, unit="inch"):
    return NS(
        page_number=number,
        width=width,
        height=height,
        unit=unit,
        lines=[NS(content=t, polygon=_poly(*b)) for t, b in lines],
        words=words,
    )


def _simple_result():
    d = _Doc()
    cells = [
        d.cell(1, 0, 0, "시험항목", (1, 2, 3, 2.5), kind="columnHeader"),
        d.cell(1, 0, 1, "결과", (3, 2, 5, 2.5), kind="columnHeader"),
        d.cell(1, 1, 0, "납(Pb)", (1, 2.5, 3, 3)),
        d.cell(1, 1, 1, "ND*", (3, 2.5, 5, 3)),
        d.cell(1, 2, 0, "카드뮴", (1, 3, 3, 3.5)),
        d.cell(1, 2, 1, "0.05", (3, 3, 5, 3.5)),
    ]
    table = NS(
        row_count=3,
        column_count=2,
        cells=cells,
        bounding_regions=[NS(page_number=1, polygon=_poly(1, 2, 5, 3.5))],
    )
    lines = [
        ("시험성적서", (1, 1, 4, 1.3)),
        ("* 검출한계 0.01 mg/L", (1, 3.7, 4, 3.9)),
        ("1) 먼 곳의 주석", (1, 9, 4, 9.2)),  # 15% 밖
    ]
    return NS(model_id="prebuilt-layout", pages=[_page(1, lines, d.words[1])], tables=[table])


def test_simple_table_header_marks_footnote():
    ext = convert_layout_result(_simple_result())
    assert ext.source == "ocr"
    assert ext.backend == "azure-prebuilt-layout"
    assert ext.warnings == []
    assert ext.pages[0].text.startswith("시험성적서\n")
    assert ext.pages[0].width == 8.5
    (t,) = ext.tables
    assert (t.page, t.table_index, t.n_rows, t.n_cols) == (1, 0, 3, 2)
    head = t.cell_at(0, 0)
    assert head.text == "시험항목" and head.is_header
    nd = t.cell_at(1, 1)
    assert nd.text == "ND" and nd.footnote_marks == ["*"] and not nd.is_header
    assert nd.confidence == pytest.approx(0.99)
    assert nd.bbox == pytest.approx((3 / 8.5, 2.5 / 11, 5 / 8.5, 3 / 11))
    assert t.bbox == pytest.approx((1 / 8.5, 2 / 11, 5 / 8.5, 3.5 / 11))
    assert [(f.mark, f.text) for f in t.footnotes] == [("*", "검출한계 0.01 mg/L")]
    assert t.footnote("*").text == "검출한계 0.01 mg/L"


def test_row_merged_cell_and_row_header_not_header():
    d = _Doc()
    cells = [
        d.cell(1, 0, 0, "용출시험", (1, 1, 2, 3), kind="rowHeader", rs=2),
        d.cell(1, 0, 1, "납", (2, 1, 3, 2)),
        d.cell(1, 1, 1, "비소", (2, 2, 3, 3)),
    ]
    table = NS(row_count=2, column_count=2, cells=cells, bounding_regions=[])
    ext = convert_layout_result(NS(pages=[_page(1, [], d.words[1])], tables=[table]))
    (t,) = ext.tables
    merged = t.cell_at(1, 0)
    assert merged.row == 0 and merged.row_span == 2 and merged.text == "용출시험"
    assert not merged.is_header  # rowHeader는 머리글 행이 아니다
    assert t.expanded() == [["용출시험", "납"], ["용출시험", "비소"]]
    assert t.bbox == pytest.approx((1 / 8.5, 1 / 11, 3 / 8.5, 3 / 11))  # 칸 bbox 합


def test_pixel_unit_normalized():
    d = _Doc()
    cells = [d.cell(1, 0, 0, "pH", (100, 200, 500, 300))]
    table = NS(
        row_count=1,
        column_count=1,
        cells=cells,
        bounding_regions=[NS(page_number=1, polygon=_poly(100, 200, 500, 300))],
    )
    page = _page(1, [], d.words[1], width=1000, height=2000, unit="pixel")
    ext = convert_layout_result(NS(pages=[page], tables=[table]))
    assert ext.tables[0].cells[0].bbox == pytest.approx((0.1, 0.1, 0.5, 0.15))
    assert ext.pages[0].width == 1000


def test_table_spanning_two_pages_is_split():
    d = _Doc()
    cells = [
        d.cell(1, 0, 0, "항목", (1, 8, 3, 8.5), kind="columnHeader"),
        d.cell(1, 0, 1, "결과", (3, 8, 5, 8.5), kind="columnHeader"),
        d.cell(1, 1, 0, "납", (1, 8.5, 3, 9)),
        d.cell(1, 1, 1, "ND", (3, 8.5, 5, 9)),
        d.cell(2, 2, 0, "구리", (1, 1, 3, 1.5)),
        d.cell(2, 2, 1, "0.3", (3, 1, 5, 1.5)),
        d.cell(2, 3, 0, "아연", (1, 1.5, 3, 2)),
        d.cell(2, 3, 1, "1.2", (3, 1.5, 5, 2)),
    ]
    # 2쪽에는 위에 다른 표가 없지만, 1쪽에는 이 표 위에 작은 표가 하나 더 있다
    small = NS(
        row_count=1,
        column_count=1,
        cells=[d.cell(1, 0, 0, "시료명", (1, 1, 3, 1.5))],
        bounding_regions=[NS(page_number=1, polygon=_poly(1, 1, 3, 1.5))],
    )
    big = NS(
        row_count=4,
        column_count=2,
        cells=cells,
        bounding_regions=[
            NS(page_number=1, polygon=_poly(1, 8, 5, 9)),
            NS(page_number=2, polygon=_poly(1, 1, 5, 2)),
        ],
    )
    pages = [_page(1, [], d.words[1]), _page(2, [], d.words[2])]
    ext = convert_layout_result(NS(pages=pages, tables=[big, small]))
    assert [(t.page, t.table_index) for t in ext.tables] == [(1, 0), (1, 1), (2, 0)]
    first, second = ext.tables[1], ext.tables[2]
    assert first.n_rows == 2 and first.continued_from is None
    assert second.n_rows == 2 and second.n_cols == 2
    assert second.cell_at(0, 0).text == "구리"  # 행 번호를 쪽마다 0부터
    assert second.continued_from == TableRef(page=1, table_index=1)
    assert any("걸쳐" in w for w in ext.warnings)


def test_low_confidence_warning():
    d = _Doc()
    cells = [d.cell(1, 0, 0, "0.5 mg/L", (1, 1, 2, 2), conf=0.6)]
    table = NS(row_count=1, column_count=1, cells=cells, bounding_regions=[])
    ext = convert_layout_result(NS(pages=[_page(1, [], d.words[1])], tables=[table]))
    assert ext.tables[0].cells[0].confidence == pytest.approx(0.6)
    assert any("신뢰도" in w for w in ext.warnings)


def test_dict_form_camel_case():
    result = {
        "modelId": "prebuilt-layout",
        "pages": [
            {
                "pageNumber": 1,
                "width": 10,
                "height": 10,
                "unit": "inch",
                "lines": [{"content": "※ 비고", "polygon": _poly(1, 3.5, 4, 3.8)}],
                "words": [{"content": "12", "confidence": 0.9, "span": {"offset": 0, "length": 2}}],
            }
        ],
        "tables": [
            {
                "rowCount": 1,
                "columnCount": 1,
                "cells": [
                    {
                        "rowIndex": 0,
                        "columnIndex": 0,
                        "content": "12",
                        "boundingRegions": [{"pageNumber": 1, "polygon": _poly(1, 1, 5, 3)}],
                        "spans": [{"offset": 0, "length": 2}],
                    }
                ],
                "boundingRegions": [{"pageNumber": 1, "polygon": _poly(1, 1, 5, 3)}],
            }
        ],
    }
    ext = convert_layout_result(result)
    t = ext.tables[0]
    assert t.cells[0].text == "12" and t.cells[0].confidence == pytest.approx(0.9)
    assert [(f.mark, f.text) for f in t.footnotes] == [("※", "비고")]


def _settings(**kw):
    base = dict(
        _env_file=None,
        allow_document_ocr=True,
        azure_docintel_endpoint="https://example.invalid/",
        azure_docintel_api_key="fake",
        ocr_timeout_seconds=5,
    )
    base.update(kw)
    return Settings(**base)


class _FakePoller:
    def __init__(self, result, done=True):
        self._result, self._done = result, done
        self.waited = None

    def wait(self, timeout=None):
        self.waited = timeout

    def done(self):
        return self._done

    def result(self, timeout=None):
        return self._result


class _FakeClient:
    def __init__(self, poller=None, error=None):
        self.poller, self.error, self.calls = poller, error, []

    def begin_analyze_document(self, model_id, body, **kw):
        self.calls.append((model_id, body, kw))
        if self.error:
            raise self.error
        return self.poller


def test_ocr_disabled():
    client = _FakeClient(_FakePoller(_simple_result()))
    with pytest.raises(OcrDisabled):
        analyze_layout(
            b"%PDF", "application/pdf", settings=_settings(allow_document_ocr=False), client=client
        )
    with pytest.raises(OcrDisabled):
        analyze_layout(b"%PDF", "application/pdf", settings=_settings(azure_docintel_api_key=None))
    assert client.calls == []


def test_analyze_with_fake_client():
    poller = _FakePoller(_simple_result())
    client = _FakeClient(poller)
    ext = analyze_layout(b"\xff\xd8jpeg", "image/jpeg", settings=_settings(), client=client)
    assert ext.tables[0].cell_at(1, 1).text == "ND"
    ((model_id, body, kw),) = client.calls
    assert model_id == "prebuilt-layout" and body == b"\xff\xd8jpeg"
    assert kw["content_type"] == "application/octet-stream"
    assert poller.waited == 5


def test_analyze_timeout_and_error():
    with pytest.raises(OcrFailed, match="시간 초과"):
        analyze_layout(
            b"x",
            "image/png",
            settings=_settings(),
            client=_FakeClient(_FakePoller(None, done=False)),
        )
    err = RuntimeError("secret-ish detail https://example.invalid/?key=abc")
    with pytest.raises(OcrFailed) as ei:
        analyze_layout(b"x", "application/pdf", settings=_settings(), client=_FakeClient(error=err))
    assert "abc" not in str(ei.value) and "RuntimeError" in str(ei.value)


def test_unsupported_content_type():
    with pytest.raises(ValueError):
        analyze_layout(
            b"x", "text/plain", settings=_settings(), client=_FakeClient(_FakePoller(None))
        )
    with pytest.raises(ValueError):
        analyze_layout(b"x", None, settings=_settings(), client=_FakeClient(_FakePoller(None)))


def test_error_messages_are_plain_korean():
    from types import SimpleNamespace

    class _HttpErr(Exception):
        def __init__(self, status, code):
            super().__init__("https://example.invalid/?key=abc")
            self.status_code = status
            self.error = SimpleNamespace(code=code)

    def msg(err):
        with pytest.raises(OcrFailed) as ei:
            analyze_layout(b"x", "image/png", settings=_settings(), client=_FakeClient(error=err))
        assert "abc" not in str(ei.value)
        return str(ei.value)

    assert "이 파일을 읽지 못했습니다" in msg(_HttpErr(200, "InvalidRequest"))
    assert "키·권한" in msg(_HttpErr(401, "Unauthorized"))
    assert "잠시 뒤" in msg(_HttpErr(429, "TooManyRequests"))
    assert "연결하지 못했습니다" in msg(RuntimeError("boom"))
