"""업로드한 서류에서 시험성적서 표 값을 자동으로 읽어 검수 대기 후보로 만든다.

설계: docs/design/test-report-table-extraction.md 3·13절.
- PDF·이미지만 읽는다. 글자 있는 PDF는 로컬(pdfplumber), 스캔본·이미지는 OCR이 켜져 있을 때 Azure.
- 읽은 값은 사실이 아니다. 서버 검수 뒤 `values/apply`로만 판정에 들어간다(UNVERIFIED 후보).
- 표 검증(T1~T10)을 통과한 FOUND 항목만 후보가 된다. 나머지(AMBIGUOUS 등)는 요약에만 남긴다.
- 읽기가 실패해도 업로드는 실패시키지 않는다(사람이 직접 입력할 수 있다). 실패는 요약에 남긴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

from app.config import Settings
from app.domain.document import ExtractedFactItem, ItemStatus, item_to_value
from app.domain.ranges import NumRange
from app.reading.pipeline import IMAGE_TYPES, TEST_REPORT_KEYS, read_test_report
from app.rules.answers import AnswerError, check_document_value
from app.rules.model import KnowledgeBase

IMAGE_SUFFIXES = set(IMAGE_TYPES)
IMAGE_CONTENT_TYPES = set(IMAGE_TYPES.values())


@dataclass
class TableCandidate:
    key: str
    value: Any  # 카탈로그 타입으로 바꾼 값(구간이면 NumRange)
    unit: str | None
    note: str
    item: ExtractedFactItem


@dataclass
class TableReadOutcome:
    candidates: list[TableCandidate] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)  # Document.extracted_facts["table_read"]
    page_text: str = ""  # OCR로 읽은 쪽 글자(이미지·스캔본의 extracted_text로 쓴다)


def _ct(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def is_pdf(filename: str, content_type: str | None) -> bool:
    return PurePath(filename or "").suffix.lower() == ".pdf" or _ct(content_type) == (
        "application/pdf"
    )


def is_image(filename: str, content_type: str | None) -> bool:
    return (
        PurePath(filename or "").suffix.lower() in IMAGE_SUFFIXES
        or _ct(content_type) in IMAGE_CONTENT_TYPES
    )


def _where(item: ExtractedFactItem) -> str:
    c = item.cell_ref
    if c is None:
        return f"{item.page}쪽" if item.page else ""
    return f"{c.page}쪽 표{c.table_index + 1} {c.row + 1}행 {c.col + 1}열"


def _item_summary(item: ExtractedFactItem, rejected: list[str] | None) -> dict[str, Any]:
    out = item.model_dump(
        mode="json",
        include={
            "key",
            "status",
            "value_raw",
            "unit_raw",
            "page",
            "quote",
            "item_raw",
            "sample_label",
            "below_detection_limit",
            "detection_limit",
            "detection_limit_basis",
            "note",
            "cell_ref",
            "unit_ref",
            "detection_limit_ref",
        },
        exclude_none=True,
    )
    if rejected:
        out["guard_reasons"] = rejected
    return out


def read_document_tables(
    kb: KnowledgeBase,
    settings: Settings,
    *,
    filename: str,
    content_type: str | None,
    data: bytes,
    document_id: str,
    skip_keys: set[str],
    azure_client=None,  # noqa: ANN001 - 시험용 주입
) -> TableReadOutcome | None:
    """PDF·이미지가 아니거나 표 읽기가 꺼져 있으면 None."""
    if not settings.document_table_reading:
        return None
    if not (is_pdf(filename, content_type) or is_image(filename, content_type)):
        return None
    keys = [k for k in TEST_REPORT_KEYS if k in kb.catalog and k not in skip_keys]
    if not keys:
        return None
    report = read_test_report(
        data,
        filename,
        content_type,
        settings=settings,
        document_id=document_id,
        requested_keys=keys,
        azure_client=azure_client,
    )
    res = report.result
    out = TableReadOutcome()
    rejected_values: list[dict[str, Any]] = []
    for item in res.facts:
        if item.status is not ItemStatus.FOUND:
            continue
        unit = kb.catalog[item.key].unit
        try:
            value = check_document_value(kb, item.key, item_to_value(item))
        except AnswerError as exc:
            rejected_values.append({"key": item.key, "reason": str(exc)})
            continue
        raw = " ".join(x for x in (item.value_raw, item.unit_raw) if x)
        note = f"표 자동 읽기(검수 대기) · {_where(item)} · 원문 {raw!r}"
        if item.below_detection_limit and item.detection_limit_basis == "limit_column":
            note += f" · 불검출(검출한계 없음 → 같은 행 기준 {item.detection_limit:g} 미만으로 봄)"
        elif item.below_detection_limit:
            note += f" · 불검출(검출한계 {item.detection_limit:g})"
        out.candidates.append(
            TableCandidate(key=item.key, value=value, unit=unit, note=note[:500], item=item)
        )
    ext = report.extraction
    if ext is not None and ext.source == "ocr":
        out.page_text = "\n\n".join(p.text.strip() for p in ext.pages if p.text.strip())
    out.summary = {
        "backend": ext.backend if ext else None,
        "source": ext.source if ext else None,
        "route": report.route,
        "doc_type": res.detected_doc_type.value,
        "tables": len(ext.tables) if ext else 0,
        "items": [
            _item_summary(it, report.rejected.get(it.key))
            for it in res.facts
            if it.status is not ItemStatus.NOT_FOUND
        ],
        "not_found": [it.key for it in res.facts if it.status is ItemStatus.NOT_FOUND],
        "value_check_failed": rejected_values,
        "warnings": [w.model_dump(mode="json", exclude_none=True) for w in res.warnings],
        "errors": [e.model_dump(mode="json") for e in res.errors],
    }
    return out


def json_value(v: Any) -> Any:
    return v.model_dump(mode="json") if isinstance(v, NumRange) else v
