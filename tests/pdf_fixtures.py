"""표 추출 테스트용 PDF를 메모리에서 만든다(reportlab). 한글은 CID 글꼴 HYSMyeongJo-Medium."""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT = "HYSMyeongJo-Medium"
pdfmetrics.registerFont(UnicodeCIDFont(FONT))

_TEXT = ParagraphStyle("ko", fontName=FONT, fontSize=10, leading=14)
_GRID = [
    ("FONTNAME", (0, 0), (-1, -1), FONT),
    ("FONTSIZE", (0, 0), (-1, -1), 10),
    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
]

HEADER = ["시험항목", "시험방법", "결과", "단위", "기준"]


def _build(story: list) -> bytes:
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4).build(story)
    return buf.getvalue()


def _table(rows: list[list[str]], extra_style: list | None = None) -> Table:
    t = Table(rows, repeatRows=0)
    t.setStyle(TableStyle(_GRID + (extra_style or [])))
    return t


def simple_report_pdf() -> bytes:
    """머리글 + 2행, 표 아래 각주 한 줄."""
    rows = [
        HEADER,
        ["납(Pb)", "ES 06402.1", "0.12", "mg/L", "3"],
        ["카드뮴", "ES 06402.1", "ND*", "mg/L", "0.3"],
    ]
    return _build(
        [
            Paragraph("시험성적서", _TEXT),
            Spacer(1, 12),
            _table(rows),
            Spacer(1, 6),
            Paragraph("* 검출한계 0.01 mg/L", _TEXT),
        ]
    )


def merged_cell_pdf() -> bytes:
    """구분 열의 "용출시험" 칸이 세 행에 걸친다."""
    rows = [
        ["구분", *HEADER],
        ["용출시험", "납(Pb)", "ES 06402.1", "0.12", "mg/L", "3"],
        ["", "카드뮴", "ES 06402.1", "ND", "mg/L", "0.3"],
        ["", "구리", "ES 06402.1", "1.5", "mg/L", "3"],
        ["함량시험", "수분", "ES 06301.1", "85", "%", "-"],
    ]
    return _build([_table(rows, [("SPAN", (0, 1), (0, 3))])])


def two_page_table_pdf() -> bytes:
    """표가 두 쪽에 걸치고 둘째 쪽에는 머리글이 반복되지 않는다."""
    first = [HEADER] + [[f"항목{i}", "ES 06402.1", f"0.{i}", "mg/L", "3"] for i in range(1, 6)]
    second = [[f"항목{i}", "ES 06402.1", f"0.{i}", "mg/L", "3"] for i in range(6, 10)]
    return _build([_table(first), PageBreak(), _table(second)])


def scanned_like_pdf() -> bytes:
    """글자 층이 없는 쪽(사각형만 그림)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.rect(72, 400, 300, 200, stroke=1, fill=0)
    c.showPage()
    c.save()
    return buf.getvalue()


def borderless_table_pdf() -> bytes:
    """선 없는 표(글자 정렬만으로 열이 보임)."""
    rows = [HEADER] + [[f"항목{i}", "ES06402", f"0.{i}", "mg/L", "3"] for i in range(1, 6)]
    t = Table(rows)
    t.setStyle(
        TableStyle([("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 10)])
    )
    return _build([t])


def plain_text_pdf() -> bytes:
    """표 없이 문단만 있는 쪽."""
    lines = [
        "시험성적서",
        "의뢰인이 제출한 시료에 대하여 아래와 같이 시험하였음을 증명합니다.",
        "시료명: 폐수처리 오니",
        "접수일: 2026년 11월 1일",
    ]
    return _build([Paragraph(s, _TEXT) for s in lines])


def stacked_rows_pdf() -> bytes:
    """한 칸에 항목이 여러 줄로 쌓이고 행 사이 선이 없는 성적서(실제 공공기관 성적서 모양).

    검체 하나에 항목 여러 개를 한 칸에 줄바꿈으로 적고, 기준 칸 하나는 두 줄(pH)이다.
    단위는 항목 이름 안에 있다("납(mg/L)"). 기준 열이 결과 열보다 왼쪽이다.
    """
    rows = [
        ["검체명", "항목명", "기준", "결과"],
        ["S-1", "납(mg/L)\n구리(mg/L)\n수분(%)", "3.0 이상\n3.0 이상\n-", "불검출\n0.021\n74.4"],
        ["S-2", "기름성분(%)\npH", "5% 이상\n폐산 : 2.0 이하,\n폐알칼리 : 12.5 이상", "0.1\n8.05"],
    ]
    t = Table(rows, repeatRows=0)
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
                ("INNERGRID", (0, 0), (-1, 0), 0.5, colors.black),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.black),
                ("LINEAFTER", (0, 0), (-2, -1), 0.5, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return _build([t])
