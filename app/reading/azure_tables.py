"""Azure AI Document Intelligence(prebuilt-layout) 표 인식 백엔드.

PDF(스캔 포함)나 사진을 보내 받은 layout 결과를 `TableExtraction`으로 바꾼다.
설계: docs/design/test-report-table-extraction.md 4절(출력 형식), 9절(데이터 정책).

- `analyze_layout`: 설정 `allow_document_ocr`가 켜져 있고 endpoint·key가 있을 때만 서비스를 부른다.
  원본을 그대로 Azure로 보내므로(9절) 기본은 꺼짐이다.
- `convert_layout_result`: 서비스 결과(SDK `AnalyzeResult`, REST JSON dict, 같은 모양의 가짜 객체)를
  바꾸는 순수 함수. I/O 없음.

정한 것(설계 문서에 없던 세부):
- 머리글(is_header)은 `columnHeader`·`stubHead`만 참으로 본다. `rowHeader`는 표 왼쪽 항목명 열이라
  머리글 행이 아니다. 참으로 두면 쪽 넘김 판단(첫 행 머리글 여부)이 틀어진다.
- 여러 쪽에 걸친 표 하나는 칸의 bounding region 쪽으로 나눠 쪽마다 TableGrid 하나로 만든다.
  행 번호는 쪽마다 0부터 다시 매기고, 뒤 조각의 continued_from에 앞 조각 좌표를 넣는다
  (Azure가 이미 한 표로 묶었으므로 link_continuations의 추정보다 확실하다).
- PageInfo.width·height는 서비스 단위(PDF는 inch, 사진은 pixel) 값 그대로 둔다.
  bbox만 비율로 바꾼다.
"""

from __future__ import annotations

import bisect
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.reading.common import link_continuations, parse_footnote_line, split_cell_marks
from app.reading.tables import (
    BBox,
    Footnote,
    PageInfo,
    TableCell,
    TableExtraction,
    TableGrid,
    TableRef,
)

SUPPORTED_CONTENT_TYPES = frozenset(
    {"application/pdf", "image/jpeg", "image/png", "image/tiff", "image/bmp", "image/heif"}
)
HEADER_KINDS = frozenset({"columnHeader", "stubHead"})
LOW_CONFIDENCE = 0.8
FOOTNOTE_WINDOW = 0.15  # 표 아래 각주를 찾는 범위(쪽 높이에 대한 비율)
_SELECTION_MARKS = (":selected:", ":unselected:")


class OcrDisabled(RuntimeError):
    """문서 인식이 꺼져 있다(allow_document_ocr=false 또는 endpoint·key 없음)."""


class OcrFailed(RuntimeError):
    """서비스 오류·시간 초과. 메시지에 비밀값을 넣지 않는다."""


# ---------------------------------------------------------------- 서비스 호출


def analyze_layout(
    data: bytes, content_type: str | None, *, settings: Settings, client: Any = None
) -> TableExtraction:
    """원본 바이트를 Azure layout 모델로 읽어 표를 돌려준다.

    client를 주입하면 그것을 쓴다(테스트). 없으면 설정으로 DocumentIntelligenceClient를 만든다.
    """
    if not settings.ocr_enabled:
        raise OcrDisabled("문서 인식(OCR)이 꺼져 있다: ALLOW_DOCUMENT_OCR와 endpoint·key를 확인")
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype not in SUPPORTED_CONTENT_TYPES:
        raise ValueError(f"문서 인식이 지원하지 않는 형식: {content_type!r}")
    if not data:
        raise ValueError("빈 파일")

    if client is None:
        client = _make_client(settings)
    model_id = settings.azure_docintel_model
    timeout = settings.ocr_timeout_seconds
    try:
        # SDK 1.0.x: body에 bytes를 주면 그대로 전송한다. 형식은 서비스가 내용으로 판별하므로
        # octet-stream으로 보낸다(SDK 예제와 같음).
        poller = client.begin_analyze_document(
            model_id,
            body=data,
            content_type="application/octet-stream",
            polling_interval=1,  # 기본값이면 응답의 Retry-After를 따라 수십 초씩 기다린다
        )
        poller.wait(timeout)
        if not poller.done():
            raise OcrFailed(f"문서 인식 시간 초과({timeout:g}초)")
        result = poller.result()
    except OcrFailed:
        raise
    except Exception as e:  # SDK·전송 예외를 감싼다. 원문 메시지에는 URL 등이 섞일 수 있어 요약만
        raise OcrFailed(_describe_error(e)) from e
    if result is None:
        raise OcrFailed("문서 인식 결과가 비어 있다")
    return convert_layout_result(result, model_id=model_id)


def _make_client(settings: Settings) -> Any:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    return DocumentIntelligenceClient(
        settings.azure_docintel_endpoint,  # type: ignore[arg-type]  # ocr_enabled가 보장
        AzureKeyCredential(settings.azure_docintel_api_key),  # type: ignore[arg-type]
    )


_BAD_FILE_CODES = {
    "InvalidRequest",
    "InvalidContent",
    "InvalidContentDimensions",
    "InvalidArgument",
}


def _describe_error(e: Exception) -> str:
    """사용자에게 보일 쉬운 문장 + 괄호 안 기술 요약(예외 이름·상태·코드. URL·키는 넣지 않는다)."""
    detail = [type(e).__name__]
    status = getattr(e, "status_code", None)
    if status is not None:
        detail.append(f"status={status}")
    code = getattr(getattr(e, "error", None), "code", None)
    if isinstance(code, str):
        detail.append(f"code={code}")
    if status in (401, 403):
        head = "문서 인식 설정(키·권한)에 문제가 있습니다. 관리자에게 알려 주세요."
    elif status == 429:
        head = "문서 인식 요청이 많습니다. 잠시 뒤 다시 올려 주세요."
    elif code in _BAD_FILE_CODES or status in (400, 415):
        head = (
            "문서 인식이 이 파일을 읽지 못했습니다. 파일이 손상됐거나 너무 작거나 흐릴 수 있어요. "
            "다른 파일로 올리거나 값을 직접 입력해 주세요."
        )
    elif status is None:
        head = "문서 인식 서비스에 연결하지 못했습니다. 잠시 뒤 다시 올려 주세요."
    else:
        head = "문서 인식에 실패했습니다. 잠시 뒤 다시 올리거나 값을 직접 입력해 주세요."
    return f"{head} ({' '.join(detail)})"


# ---------------------------------------------------------------- 결과 변환


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """SDK 모델(Mapping, 키는 camelCase)·dict·SimpleNamespace에서 같은 필드를 읽는다."""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        camel = _camel(name)
        if camel in obj:
            value = obj[camel]
        elif name in obj:
            value = obj[name]
        else:
            return default
    else:
        value = getattr(obj, name, default)
    return default if value is None else value


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(p.title() for p in rest)


@dataclass
class _Page:
    number: int
    width: float | None
    height: float | None
    lines: list[tuple[str, BBox | None]]


@dataclass
class _Part:
    """표 하나(쪽 하나 분량). table_index는 쪽 안 순서를 정한 뒤 채운다."""

    page: int
    cells: list[TableCell]
    n_rows: int
    n_cols: int
    bbox: BBox | None
    parent: int
    seq: int  # 같은 원래 표 안의 조각 순서
    table_index: int = 0
    footnotes: list[Footnote] = field(default_factory=list)


def convert_layout_result(result: Any, *, model_id: str | None = None) -> TableExtraction:
    """layout 결과를 TableExtraction으로 바꾼다(순수 함수)."""
    model = _get(result, "model_id") or model_id or "prebuilt-layout"
    warnings: list[str] = []

    pages: dict[int, _Page] = {}
    word_index: list[tuple[int, int, float | None]] = []  # (offset, length, confidence)
    for i, p in enumerate(_get(result, "pages", [])):
        number = int(_get(p, "page_number", i + 1))
        width, height = _num(_get(p, "width")), _num(_get(p, "height"))
        lines = [
            (_clean(_get(ln, "content", "")), _bbox(_get(ln, "polygon"), width, height))
            for ln in _get(p, "lines", [])
        ]
        pages[number] = _Page(number, width, height, lines)
        for w in _get(p, "words", []):
            span = _get(w, "span")
            if span is None:
                continue
            conf = _get(w, "confidence")
            word_index.append(
                (int(_get(span, "offset", 0)), int(_get(span, "length", 0)), _num(conf))
            )
    word_index.sort(key=lambda t: t[0])
    word_offsets = [t[0] for t in word_index]

    parts: list[_Part] = []
    for t_i, table in enumerate(_get(result, "tables", [])):
        parts.extend(_split_table(t_i, table, pages, word_index, word_offsets, warnings))

    # 쪽 안 순서: 표 위쪽 y 순
    by_page: dict[int, list[_Part]] = {}
    for part in parts:
        by_page.setdefault(part.page, []).append(part)
    for page_parts in by_page.values():
        page_parts.sort(key=lambda x: (x.bbox[1] if x.bbox else 2.0, x.parent, x.seq))
        for idx, part in enumerate(page_parts):
            part.table_index = idx
        for idx, part in enumerate(page_parts):
            nxt = page_parts[idx + 1] if idx + 1 < len(page_parts) else None
            part.footnotes = _footnotes_below(part, nxt, pages.get(part.page))

    ordered = sorted(parts, key=lambda x: (x.page, x.table_index))
    first_of: dict[tuple[int, int], _Part] = {(x.parent, x.seq): x for x in parts}
    grids: list[TableGrid] = []
    for part in ordered:
        prev = first_of.get((part.parent, part.seq - 1))
        grids.append(
            TableGrid(
                page=part.page,
                table_index=part.table_index,
                n_rows=part.n_rows,
                n_cols=part.n_cols,
                cells=part.cells,
                footnotes=part.footnotes,
                continued_from=(
                    TableRef(page=prev.page, table_index=prev.table_index) if prev else None
                ),
                source="ocr",
                bbox=part.bbox,
            )
        )
    grids = link_continuations(grids)

    low = [c.confidence for g in grids for c in g.cells if c.confidence is not None]
    low = [c for c in low if c < LOW_CONFIDENCE]
    if low:
        warnings.append(
            f"OCR 신뢰도가 {LOW_CONFIDENCE}보다 낮은 칸 {len(low)}개(최저 {min(low):.2f})"
        )

    page_infos = [
        PageInfo(
            page=p.number,
            text="\n".join(text for text, _ in p.lines),
            width=p.width,
            height=p.height,
        )
        for p in sorted(pages.values(), key=lambda x: x.number)
    ]
    return TableExtraction(
        source="ocr",
        pages=page_infos,
        tables=grids,
        backend=f"azure-{model}",
        warnings=warnings,
    )


def _split_table(
    t_i: int,
    table: Any,
    pages: dict[int, _Page],
    word_index: list[tuple[int, int, float | None]],
    word_offsets: list[int],
    warnings: list[str],
) -> list[_Part]:
    regions = _get(table, "bounding_regions", [])
    default_page = int(_get(regions[0], "page_number", 1)) if regions else 1
    n_cols_declared = int(_get(table, "column_count", 0))
    n_rows_declared = int(_get(table, "row_count", 0))

    # 칸을 쪽별로 모은다
    raw_by_page: dict[int, list[tuple[Any, BBox | None]]] = {}
    for cell in _get(table, "cells", []):
        cell_regions = _get(cell, "bounding_regions", [])
        page_no = int(_get(cell_regions[0], "page_number", default_page)) if cell_regions else None
        page_no = page_no or default_page
        pg = pages.get(page_no)
        bbox = None
        if cell_regions and pg is not None:
            bbox = _bbox(_get(cell_regions[0], "polygon"), pg.width, pg.height)
        raw_by_page.setdefault(page_no, []).append((cell, bbox))
    if not raw_by_page:
        return []

    multi = len(raw_by_page) > 1
    if multi:
        warnings.append(
            f"표 {t_i + 1}이 {len(raw_by_page)}쪽에 걸쳐 있어 쪽마다 나누고 "
            "이어짐(continued_from)을 표시함"
        )

    parts: list[_Part] = []
    for seq, page_no in enumerate(sorted(raw_by_page)):
        raw = raw_by_page[page_no]
        offset = min(int(_get(c, "row_index", 0)) for c, _ in raw) if multi else 0
        cells: list[TableCell] = []
        taken: set[tuple[int, int]] = set()
        for cell, bbox in sorted(
            raw, key=lambda x: (int(_get(x[0], "row_index", 0)), int(_get(x[0], "column_index", 0)))
        ):
            row = int(_get(cell, "row_index", 0)) - offset
            col = int(_get(cell, "column_index", 0))
            rs = max(1, int(_get(cell, "row_span", 1)))
            cs = max(1, int(_get(cell, "column_span", 1)))
            area = {(r, k) for r in range(row, row + rs) for k in range(col, col + cs)}
            if area & taken:
                warnings.append(f"{page_no}쪽 표 {t_i + 1}의 칸 ({row},{col})이 다른 칸과 겹쳐 뺌")
                continue
            taken |= area
            text, marks = split_cell_marks(_clean(_get(cell, "content", "")))
            cells.append(
                TableCell(
                    row=row,
                    col=col,
                    text=text,
                    row_span=rs,
                    col_span=cs,
                    is_header=_get(cell, "kind") in HEADER_KINDS,
                    bbox=bbox,
                    confidence=_cell_confidence(_get(cell, "spans", []), word_index, word_offsets),
                    footnote_marks=marks,
                )
            )
        if not cells:
            continue
        n_rows = max(c.row + c.row_span for c in cells)
        if not multi:
            n_rows = max(n_rows, n_rows_declared)
        n_cols = max(max(c.col + c.col_span for c in cells), n_cols_declared)
        parts.append(
            _Part(
                page=page_no,
                cells=cells,
                n_rows=n_rows,
                n_cols=n_cols,
                bbox=_table_bbox(regions, page_no, pages.get(page_no), cells),
                parent=t_i,
                seq=seq,
            )
        )
    for i, part in enumerate(parts):  # 비어서 빠진 조각이 있으면 순서를 다시 매긴다
        part.seq = i
    return parts


def _table_bbox(regions: list[Any], page_no: int, pg: _Page | None, cells: list[TableCell]):
    if pg is not None:
        for r in regions:
            if int(_get(r, "page_number", 0)) == page_no:
                b = _bbox(_get(r, "polygon"), pg.width, pg.height)
                if b is not None:
                    return b
    boxes = [c.bbox for c in cells if c.bbox is not None]
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _cell_confidence(
    spans: list[Any],
    word_index: list[tuple[int, int, float | None]],
    word_offsets: list[int],
) -> float | None:
    values: list[float] = []
    for s in spans:
        start = int(_get(s, "offset", 0))
        end = start + int(_get(s, "length", 0))
        i = bisect.bisect_left(word_offsets, start)
        while i < len(word_index) and word_index[i][0] < end:
            off, length, conf = word_index[i]
            if off + length <= end and conf is not None:
                values.append(conf)
            i += 1
    if not values:
        return None
    return min(1.0, max(0.0, sum(values) / len(values)))


def _footnotes_below(part: _Part, nxt: _Part | None, pg: _Page | None) -> list[Footnote]:
    """표 아래(쪽 높이 15% 안, 다음 표 위)에 있는 각주 줄."""
    if pg is None or part.bbox is None:
        return []
    bottom = part.bbox[3]
    limit = bottom + FOOTNOTE_WINDOW
    if nxt is not None and nxt.bbox is not None:
        limit = min(limit, nxt.bbox[1])
    found: list[tuple[float, Footnote]] = []
    for text, bbox in pg.lines:
        if bbox is None:
            continue
        top = bbox[1]
        if bottom - 0.005 <= top <= limit:
            fn = parse_footnote_line(text)
            if fn is not None:
                found.append((top, fn))
    found.sort(key=lambda x: x[0])
    return [fn for _, fn in found]


def _bbox(polygon: Any, width: float | None, height: float | None) -> BBox | None:
    if not polygon or not width or not height:
        return None
    pts = [float(v) for v in polygon]
    if len(pts) < 4:
        return None
    xs, ys = pts[0::2], pts[1::2]

    def clamp(v: float) -> float:
        return min(1.0, max(0.0, v))

    return (
        clamp(min(xs) / width),
        clamp(min(ys) / height),
        clamp(max(xs) / width),
        clamp(max(ys) / height),
    )


def _clean(text: str) -> str:
    for m in _SELECTION_MARKS:
        text = text.replace(m, " ")
    return " ".join(text.split())


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
