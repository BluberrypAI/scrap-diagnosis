"""시험성적서 읽기 흐름: 표 인식(로컬 또는 Azure) → 열 역할 → 대응 → 표 검증 → 계약 결과.

설계 docs/design/test-report-table-extraction.md 3절. 업로드 API는 app/api/document_reading.py로
이 흐름을 부른다. scripts/read_test_report.py로 파일 하나를 읽어 볼 수도 있다.

경로
- PDF에 글자 층이 있으면 pdfplumber(로컬).
  결과 표를 하나도 못 찾으면 OCR이 켜져 있을 때 Azure로 다시
- 글자 층이 없는 PDF, 이미지: OCR이 켜져 있으면 Azure, 아니면 EMPTY_CONTENT 오류
- backend="local" / "azure"로 강제할 수 있다(비교 시험용)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Literal

from app.config import Settings
from app.domain.document import (
    DocType,
    DocumentExtractionResult,
    ErrorCode,
    ExtractedFactItem,
    ExtractionError,
    ExtractionWarning,
    ItemStatus,
    WarningCode,
)
from app.domain.tables import TableExtraction
from app.reading.columns import ColumnRole, TableLayout, analyze_tables
from app.reading.mapper import map_test_report
from app.reading.table_guard import validate_table_item
from app.reading.test_items import TEST_ITEMS

Backend = Literal["auto", "local", "azure"]
TEST_REPORT_KEYS = [t.key for t in TEST_ITEMS]
IMAGE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".heic": "image/heif",
    ".heif": "image/heif",
}


@dataclass
class ReadReport:
    result: DocumentExtractionResult
    extraction: TableExtraction | None
    layouts: dict[tuple[int, int], TableLayout] = field(default_factory=dict)
    rejected: dict[str, list[str]] = field(default_factory=dict)  # 키 → 표 검증 실패 사유
    route: list[str] = field(default_factory=list)  # 거친 경로(사람이 읽는 기록)


def _content_type(filename: str, content_type: str | None) -> str | None:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct:
        return ct
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    return IMAGE_TYPES.get(suffix)


def _result_tables(extraction: TableExtraction) -> int:
    return sum(
        1
        for lay in analyze_tables(extraction.tables).values()
        if any(c.role is ColumnRole.RESULT and c.by_rule for c in lay.columns)
    )


def extract_tables(
    data: bytes,
    filename: str,
    content_type: str | None,
    *,
    settings: Settings,
    backend: Backend = "auto",
    azure_client=None,
) -> tuple[TableExtraction | None, list[str], ExtractionError | None]:
    from app.reading import azure_tables, pdf_tables

    route: list[str] = []
    ct = _content_type(filename, content_type)
    is_pdf = ct == "application/pdf"

    def azure() -> tuple[TableExtraction | None, ExtractionError | None]:
        if not settings.ocr_enabled:
            route.append("Azure OCR 꺼짐(ALLOW_DOCUMENT_OCR)")
            return None, ExtractionError(
                code=ErrorCode.EMPTY_CONTENT,
                message="글자 층이 없거나 표를 찾지 못했고, 문서 인식(OCR)이 꺼져 있습니다.",
            )
        try:
            ext = azure_tables.analyze_layout(data, ct, settings=settings, client=azure_client)
        except azure_tables.OcrDisabled:
            route.append("Azure OCR 꺼짐")
            return None, ExtractionError(
                code=ErrorCode.EMPTY_CONTENT, message="문서 인식이 꺼져 있습니다."
            )
        except (azure_tables.OcrFailed, ValueError) as exc:
            route.append(f"Azure 실패: {exc}")
            return None, ExtractionError(code=ErrorCode.READER_FAILED, message=str(exc))
        route.append(f"Azure {ext.backend}: 표 {len(ext.tables)}개")
        return ext, None

    if not is_pdf and ct not in IMAGE_TYPES.values():
        return (
            None,
            route,
            ExtractionError(
                code=ErrorCode.UNSUPPORTED_FORMAT, message=f"지원하지 않는 형식: {filename} ({ct})"
            ),
        )
    if backend == "azure" or not is_pdf:
        ext, err = azure()
        return ext, route, err

    try:
        text_layer = pdf_tables.has_text_layer(data)
    except pdf_tables.PdfReadFailed as exc:
        return None, route, ExtractionError(code=ErrorCode.DOCUMENT_UNREADABLE, message=str(exc))
    if not text_layer:
        route.append("PDF 글자 층 없음(스캔본)")
        if backend == "local":
            return (
                None,
                route,
                ExtractionError(
                    code=ErrorCode.EMPTY_CONTENT, message="글자 층이 없는 PDF입니다(OCR 필요)."
                ),
            )
        ext, err = azure()
        return ext, route, err

    try:
        local = pdf_tables.extract_pdf_tables(data)
    except pdf_tables.PdfReadFailed as exc:
        return None, route, ExtractionError(code=ErrorCode.DOCUMENT_UNREADABLE, message=str(exc))
    n = _result_tables(local)
    route.append(f"pdfplumber: 표 {len(local.tables)}개, 결과 열이 있는 표 {n}개")
    if n > 0 or backend == "local":
        return local, route, None
    ext, err = azure()
    if ext is None:
        route.append("Azure를 쓸 수 없어 로컬 결과를 그대로 씀")
        return local, route, None
    return ext, route, err


def read_test_report(
    data: bytes,
    filename: str,
    content_type: str | None = None,
    *,
    settings: Settings,
    document_id: str = "doc",
    requested_keys: list[str] | None = None,
    subject_hint: str | None = None,
    backend: Backend = "auto",
    azure_client=None,
) -> ReadReport:
    keys = requested_keys or TEST_REPORT_KEYS
    extraction, route, err = extract_tables(
        data, filename, content_type, settings=settings, backend=backend, azure_client=azure_client
    )
    if extraction is None:
        result = DocumentExtractionResult(
            document_id=document_id,
            detected_doc_type=DocType.OTHER,
            doc_type_confidence=0.0,
            facts=[ExtractedFactItem(key=k, status=ItemStatus.NOT_FOUND) for k in keys],
            errors=[err] if err else [],
        )
        return ReadReport(result=result, extraction=None, route=route)

    layouts = analyze_tables(extraction.tables)
    warnings: list[ExtractionWarning] = []
    if not extraction.tables:
        warnings.append(
            ExtractionWarning(code=WarningCode.TABLE_NOT_DETECTED, message="표를 찾지 못했습니다.")
        )
    for lay in layouts.values():
        if any(c.role is ColumnRole.UNKNOWN for c in lay.columns) and lay.cols_with(
            ColumnRole.RESULT
        ):
            warnings.append(
                ExtractionWarning(
                    code=WarningCode.COLUMN_ROLE_UNCERTAIN,
                    message="역할을 정하지 못한 열이 있습니다. 그 열의 값은 쓰지 않았습니다.",
                    page=lay.table.page,
                )
            )

    ordered = [layouts[k] for k in sorted(layouts)]
    items, map_warnings = map_test_report(ordered, keys, subject_hint=subject_hint)
    warnings += map_warnings

    rejected: dict[str, list[str]] = {}
    checked: list[ExtractedFactItem] = []
    for it in items:
        reasons = validate_table_item(it, layouts)
        if reasons:
            rejected[it.key] = reasons
            checked.append(
                ExtractedFactItem(
                    key=it.key,
                    status=ItemStatus.AMBIGUOUS,
                    value_raw=it.value_raw,
                    unit_raw=it.unit_raw,
                    page=it.page,
                    quote=it.quote,
                    item_raw=it.item_raw,
                    cell_ref=it.cell_ref,
                    note=("표 검증 실패: " + "; ".join(reasons))[:500],
                )
            )
        else:
            checked.append(it)

    any_item = any(it.status is not ItemStatus.NOT_FOUND for it in checked)
    result = DocumentExtractionResult(
        document_id=document_id,
        detected_doc_type=DocType.TEST_REPORT if any_item else DocType.OTHER,
        doc_type_confidence=0.8 if any_item else 0.2,
        facts=checked,
        warnings=warnings,
        errors=[err] if err else [],
    )
    return ReadReport(
        result=result, extraction=extraction, layouts=layouts, rejected=rejected, route=route
    )
