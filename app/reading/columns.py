"""열 역할 판정(규칙). 설계 docs/design/test-report-table-extraction.md 5절.

머리글 사전으로 열마다 역할을 정한다. 사전으로 정하지 못한 열은 UNKNOWN(by_rule=False)이고,
그 열의 값은 결과로 쓰지 않는다(T10). LLM 보조 판정은 아직 붙이지 않았다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.tables import TableGrid, TableRef
from app.reading.units import find_unit


class ColumnRole(StrEnum):
    ITEM = "ITEM"
    GROUP = "GROUP"
    METHOD = "METHOD"
    RESULT = "RESULT"
    UNIT = "UNIT"
    LIMIT = "LIMIT"
    DETECTION_LIMIT = "DETECTION_LIMIT"
    JUDGEMENT = "JUDGEMENT"
    NUMBER = "NUMBER"  # 순번
    SAMPLE = "SAMPLE"  # 시료(검체) 이름·번호 열. 값은 행마다의 시료 구분
    UNKNOWN = "UNKNOWN"


# 순서가 중요하다: "시험기준"은 방법이고 기준이 아니다, "검출한계"는 기준이 아니다.
_ROLE_WORDS: tuple[tuple[ColumnRole, tuple[str, ...]], ...] = (
    (
        ColumnRole.METHOD,
        ("시험방법", "분석방법", "측정방법", "시험기준", "공정시험", "시험법", "방법"),
    ),
    (ColumnRole.DETECTION_LIMIT, ("검출한계", "정량한계", "mdl", "loq", "lod")),
    (ColumnRole.LIMIT, ("기준", "허용", "법적", "규제", "지정폐기물", "한도")),
    (ColumnRole.JUDGEMENT, ("판정", "적합", "적부", "비고")),
    (ColumnRole.UNIT, ("단위",)),
    (
        ColumnRole.RESULT,
        ("결과", "측정값", "분석값", "시험값", "측정치", "분석치", "결과치", "result"),
    ),
    (ColumnRole.ITEM, ("항목", "성분", "물질", "item")),
    (ColumnRole.GROUP, ("구분", "분류")),
    (ColumnRole.NUMBER, ("순번", "번호", "no.", "no")),
)
_SAMPLE_WORDS = ("시료", "sample", "검체")
# 머리글 전체가 이 말이면 결과 열이 아니라 시료 이름 열("검체명 | 항목명 | 기준 | 결과")
_SAMPLE_ID_HEADERS = {
    "검체명",
    "시료명",
    "검체번호",
    "시료번호",
    "시료구분",
    "검체구분",
    "samplename",
    "sampleid",
    "sampleno.",
}


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def role_of_header(text: str) -> ColumnRole | None:
    c = _compact(text)
    if not c:
        return None
    if c in _SAMPLE_ID_HEADERS:
        return ColumnRole.SAMPLE
    for role, words in _ROLE_WORDS:
        if role is ColumnRole.NUMBER:
            if c in words:
                return role
            continue
        if any(w in c for w in words):
            return role
    return None


def _is_sample_header(text: str) -> bool:
    c = _compact(text)
    return any(w in c for w in _SAMPLE_WORDS)


@dataclass
class ColumnInfo:
    col: int
    role: ColumnRole
    header: str
    by_rule: bool
    unit: str | None = None  # 머리글에 붙은 단위("결과(mg/L)")
    sample_label: str | None = None  # 시료별 결과 열


@dataclass
class TableLayout:
    table: TableGrid
    header_rows: list[int]
    columns: list[ColumnInfo]
    inherited_from: TableRef | None = None  # 머리글을 앞 표에서 물려받음
    notes: list[str] = field(default_factory=list)

    @property
    def first_data_row(self) -> int:
        return max(self.header_rows) + 1 if self.header_rows else 0

    def column(self, col: int) -> ColumnInfo:
        return self.columns[col]

    def cols_with(self, role: ColumnRole) -> list[ColumnInfo]:
        return [c for c in self.columns if c.role is role]


_VALUE_LIKE = re.compile(
    r"^\s*([<>≤≥]\s*)?\d[\d,]*(\.\d+)?\s*(mg/l|mg/kg|%|ppm|μg/l|ug/l)?\s*$|^\s*(nd|n\.d\.?|불검출)\b",
    re.IGNORECASE,
)


def looks_like_value(text: str) -> bool:
    return bool(_VALUE_LIKE.search(text or ""))


def _header_rows(table: TableGrid) -> list[int]:
    """위에서부터 연속된 머리글 행(최대 3행). 값처럼 보이는 칸이 있는 행은 머리글이 아니다."""
    grid = table.expanded()
    rows: list[int] = []
    for r in range(min(3, table.n_rows)):
        cells = [c for c in table.cells if c.row == r]
        marked = any(c.is_header for c in cells)
        texts = grid[r]
        if any(looks_like_value(t) for t in texts) and not marked:
            break
        hits = sum(1 for t in texts if role_of_header(t) is not None)
        samples = sum(1 for t in texts if _is_sample_header(t))
        if marked or hits >= 2 or (rows and samples >= 1):
            rows.append(r)
        else:
            break
    return rows


def analyze_table(table: TableGrid, prev: TableLayout | None = None) -> TableLayout:
    """열 역할을 정한다. 머리글이 없고 앞 표가 이어진 것이면 앞 표의 열 역할을 물려받는다."""
    header_rows = _header_rows(table)
    if not header_rows:
        if (
            prev is not None
            and table.continued_from is not None
            and table.continued_from == prev.table.ref
            and prev.table.n_cols == table.n_cols
        ):
            return TableLayout(
                table=table,
                header_rows=[],
                columns=[ColumnInfo(**vars(c)) for c in prev.columns],
                inherited_from=prev.table.ref,
                notes=["앞 쪽 표의 머리글을 물려받음(추정)"],
            )
        cols = [
            ColumnInfo(col=k, role=ColumnRole.UNKNOWN, header="", by_rule=False)
            for k in range(table.n_cols)
        ]
        return TableLayout(
            table=table, header_rows=[], columns=cols, notes=["머리글 행을 찾지 못함"]
        )

    grid = table.expanded()
    columns: list[ColumnInfo] = []
    for k in range(table.n_cols):
        texts: list[str] = []
        for r in header_rows:
            t = grid[r][k].strip()
            if t and t not in texts:
                texts.append(t)
        header = " / ".join(texts)
        # 아래 행(더 구체적인 머리글)부터 역할을 찾는다: "결과 / 시료A"면 시료별 결과 열
        role = None
        for t in reversed(texts):
            role = role_of_header(t)
            if role is not None:
                break
        sample = next((t for t in reversed(texts) if _is_sample_header(t)), None)
        if role is None and sample is not None:
            role = ColumnRole.RESULT
        if role is ColumnRole.RESULT and sample is None and len(texts) >= 2:
            # 위는 "결과", 아래는 시료 이름(사전에 없는 말)인 경우
            if role_of_header(texts[-1]) is None:
                sample = texts[-1]
        unit = next((u for t in texts if (u := find_unit(t))), None)
        columns.append(
            ColumnInfo(
                col=k,
                role=role or ColumnRole.UNKNOWN,
                header=header,
                by_rule=role is not None,
                unit=unit,
                sample_label=sample if role is ColumnRole.RESULT else None,
            )
        )
    # 결과 열이 하나뿐이면 시료 이름이 없어도 된다. 여럿인데 이름이 없으면 열 번호로 구분한다.
    results = [c for c in columns if c.role is ColumnRole.RESULT]
    if len(results) > 1:
        for i, c in enumerate(results, 1):
            if not c.sample_label:
                c.sample_label = f"결과열{i}"
    return TableLayout(table=table, header_rows=header_rows, columns=columns)


def analyze_tables(tables: list[TableGrid]) -> dict[tuple[int, int], TableLayout]:
    """문서의 모든 표. 쪽·순서대로 처리해 이어진 표가 앞 표를 물려받게 한다."""
    out: dict[tuple[int, int], TableLayout] = {}
    for t in sorted(tables, key=lambda x: (x.page, x.table_index)):
        prev = None
        if t.continued_from is not None:
            prev = out.get((t.continued_from.page, t.continued_from.table_index))
        out[(t.page, t.table_index)] = analyze_table(t, prev)
    return out
