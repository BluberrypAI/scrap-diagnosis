"""증빙 문서 텍스트 추출. .txt/.md(텍스트)와 PDF(pypdf, 텍스트 층만 — 스캔본 OCR은 TODO)."""

from __future__ import annotations

import io
from pathlib import PurePath

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv"}
PDF_SUFFIXES = {".pdf"}


class UnsupportedDocument(ValueError):
    pass


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise UnsupportedDocument("텍스트 인코딩을 알 수 없습니다(UTF-8 또는 CP949)")


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [p.extract_text() or "" for p in reader.pages]
    except (PdfReadError, ValueError, KeyError) as exc:
        raise UnsupportedDocument(f"PDF를 읽을 수 없습니다: {exc}") from exc
    return "\n\n".join(t.strip() for t in pages if t.strip())


def extract_text(filename: str, content_type: str | None, data: bytes) -> str:
    suffix = PurePath(filename or "").suffix.lower()
    ct = (content_type or "").split(";")[0].strip().lower()
    if suffix in PDF_SUFFIXES or ct == "application/pdf":
        return _pdf_text(data)
    if suffix in TEXT_SUFFIXES or ct.startswith("text/"):
        return _decode(data)
    raise UnsupportedDocument(f"지원하지 않는 문서 형식입니다: {filename} ({content_type})")
