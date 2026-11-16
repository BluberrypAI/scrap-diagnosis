"""칸 단위 표(TableGrid). 서류 읽기의 표 인식 층이 내는 형식.

설계: docs/design/test-report-table-extraction.md 4절.
- 좌표는 (page, table_index, row, col). page는 1부터, table_index·row·col은 0부터.
- 병합 칸은 왼쪽 위 칸(anchor) 하나에 글자를 두고 row_span·col_span으로 범위를 적는다.
  펼친 격자는 expanded()가 만든다(병합 범위의 모든 칸이 같은 글자).
- bbox는 쪽 크기에 대한 비율 [x0, y0, x1, y1](0~1, 왼쪽 위가 원점).
  백엔드마다 단위가 달라 비율로 통일한다.
I/O·LLM 없음.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

TableSource = Literal["pdf_text_layer", "ocr"]
BBox = tuple[float, float, float, float]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TableRef(_Strict):
    page: int = Field(ge=1)
    table_index: int = Field(ge=0)


class CellRef(_Strict):
    """값을 읽은 칸. 병합 칸 안의 어느 좌표를 가리켜도 같은 칸으로 본다."""

    page: int = Field(ge=1)
    table_index: int = Field(ge=0)
    row: int = Field(ge=0)
    col: int = Field(ge=0)


class FootnoteRef(_Strict):
    """값(예: 검출한계)을 읽은 표 각주."""

    page: int = Field(ge=1)
    table_index: int = Field(ge=0)
    footnote_mark: str


class TableCell(_Strict):
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    text: str
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)
    is_header: bool = False  # 백엔드가 아는 경우만(Azure columnHeader). 모르면 False
    bbox: BBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)  # OCR일 때 글자 인식 신뢰도
    footnote_marks: list[str] = []  # 칸 글자에 붙은 각주 표시(*, 1) 등)


class Footnote(_Strict):
    mark: str  # "*", "**", "1", "※" 등. 표시 없이 표 아래에 붙은 주석은 "※"
    text: str


class TableGrid(_Strict):
    page: int = Field(ge=1)
    table_index: int = Field(ge=0)  # 같은 쪽 안에서의 순서
    n_rows: int = Field(ge=1)
    n_cols: int = Field(ge=1)
    cells: list[TableCell]
    footnotes: list[Footnote] = []
    continued_from: TableRef | None = None  # 앞 쪽 표가 이어진 것이면 그 표
    source: TableSource
    bbox: BBox | None = None  # 표 전체 영역

    @model_validator(mode="after")
    def _cells_fit(self) -> Self:
        seen: dict[tuple[int, int], int] = {}
        for i, c in enumerate(self.cells):
            if c.row + c.row_span > self.n_rows or c.col + c.col_span > self.n_cols:
                raise ValueError(f"칸 ({c.row},{c.col})이 표 크기를 넘는다")
            for r in range(c.row, c.row + c.row_span):
                for k in range(c.col, c.col + c.col_span):
                    if (r, k) in seen:
                        raise ValueError(f"칸 ({r},{k})을 두 칸이 함께 차지한다")
                    seen[(r, k)] = i
        return self

    @property
    def ref(self) -> TableRef:
        return TableRef(page=self.page, table_index=self.table_index)

    def cell_at(self, row: int, col: int) -> TableCell | None:
        """(row, col)을 덮는 칸(병합 칸이면 anchor). 비어 있는 자리면 None."""
        for c in self.cells:
            if c.row <= row < c.row + c.row_span and c.col <= col < c.col + c.col_span:
                return c
        return None

    def expanded(self) -> list[list[str]]:
        """펼친 격자. 병합 범위의 모든 자리에 anchor 글자, 빈 자리는 ""."""
        grid = [["" for _ in range(self.n_cols)] for _ in range(self.n_rows)]
        for c in self.cells:
            for r in range(c.row, c.row + c.row_span):
                for k in range(c.col, c.col + c.col_span):
                    grid[r][k] = c.text
        return grid

    def footnote(self, mark: str) -> Footnote | None:
        return next((f for f in self.footnotes if f.mark == mark), None)


class PageInfo(_Strict):
    page: int = Field(ge=1)
    text: str  # 표 밖 글자를 포함한 쪽 전체 글자
    width: float | None = None
    height: float | None = None


class TableExtraction(_Strict):
    """표 인식 층의 출력 한 묶음(문서 하나)."""

    source: TableSource
    pages: list[PageInfo]
    tables: list[TableGrid]
    backend: str  # "pdfplumber", "azure-prebuilt-layout" 등
    warnings: list[str] = []  # 백엔드가 남기는 사람이 읽을 메모(경고 코드는 검증기가 정한다)
