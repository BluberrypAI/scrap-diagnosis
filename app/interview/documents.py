"""서류(시험성적서 등): 업로드 → 검수 대기 후보 → 서버 검수 → 적용(EVIDENCED) → 효력 해제.

- 엔진은 서류 원문과 값을 대조하지 않는다. 검수가 끝난 값(apply)만 판정에 쓴다.
- 원문 파일은 저장하지 않는다(이름·형식·크기·해시와 자동 읽기 요약만). 원문 보기는 화면이 맡는다.
- 서류로 받는 사실은 facts.yaml에서 source: document인 것만이다(지금은 기름성분 함량).
- 표 자동 읽기: 글자 있는 PDF는 엔진 안(pdfplumber), 스캔본 PDF·사진은 Azure Document
  Intelligence(ALLOW_DOCUMENT_OCR와 키가 있을 때만). 읽은 값은 후보일 뿐이다.

경로·응답 모양은 기존 엔진의 서류 계약과 같다(기존 엔진 참조: app/api/documents.py,
app/api/document_reading.py). 판정 연결(EVIDENCED 사실, 효력 해제)은 v2 사실 기록에 맞춰 새로 썼다.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import PurePath
from typing import Any

from sqlalchemy import select

from app.api.errors import ApiError
from app.engine.ranges import NumRange
from app.interview import catalog as cat
from app.interview import present as pr
from app.persistence.models import Company, Document, DocumentValue, new_id, now
from app.reading.contract import Comparator, ExtractedFactItem, ItemStatus
from app.reading.pipeline import IMAGE_TYPES, read_test_report

logger = logging.getLogger(__name__)

TEXT_SUFFIXES = {".txt", ".md"}
TEXT_TYPES = {"text/plain", "text/markdown"}


def _ct(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def file_kind(filename: str, content_type: str | None) -> str | None:
    """pdf | image | text | None(받지 않는 형식)."""
    suffix = PurePath(filename or "").suffix.lower()
    ct = _ct(content_type)
    if suffix == ".pdf" or ct == "application/pdf":
        return "pdf"
    if suffix in IMAGE_TYPES or ct in set(IMAGE_TYPES.values()) or ct.startswith("image/"):
        return "image"
    if suffix in TEXT_SUFFIXES or ct in TEXT_TYPES:
        return "text"
    return None


# 사진 형식별 파일 앞부분(매직 바이트). SVG는 스크립트를 담을 수 있어 받지 않는다
_IMAGE_SIGNATURES = (
    b"\xff\xd8\xff",  # JPEG
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"II*\x00",  # TIFF(리틀 엔디언)
    b"MM\x00*",  # TIFF(빅 엔디언)
    b"BM",  # BMP
)
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heif"}


def content_matches(kind: str, data: bytes) -> bool:
    """확장자·Content-Type이 말하는 형식과 실제 내용이 맞는지 본다(이름만 바꾼 실행 파일 등 거부)."""
    if kind == "pdf":
        return b"%PDF-" in data[:1024]
    if kind == "image":
        if data.startswith(_IMAGE_SIGNATURES):
            return True
        return data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS
    if kind == "text":
        head = data[:65536]
        if b"\x00" in head:
            return False
        for encoding in ("utf-8", "cp949"):
            try:
                head.decode(encoding)
                return True
            except UnicodeDecodeError:
                continue
        return False
    return False


def item_value(item: ExtractedFactItem) -> Any:
    """FOUND 항목의 값. 불검출은 '검출한계 미만', 부등호 값은 구간이다(값을 지어내지 않음)."""
    if item.below_detection_limit:
        return NumRange(hi=item.detection_limit, hi_inc=False).model_dump()
    if item.comparator is Comparator.EQ:
        return item.value
    v = float(item.value)
    return {
        Comparator.LT: {"hi": v, "hi_inc": False},
        Comparator.LTE: {"hi": v, "hi_inc": True},
        Comparator.GT: {"lo": v, "lo_inc": False},
    }.get(item.comparator, {"lo": v, "lo_inc": True})


def _where(item: ExtractedFactItem) -> str:
    c = item.cell_ref
    if c is None:
        return f"{item.page}쪽" if item.page else ""
    return f"{c.page}쪽 표{c.table_index + 1} {c.row + 1}행 {c.col + 1}열"


SUMMARY_FIELDS = {
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
}


class DocumentMixin:
    """CaseService에 섞어 쓴다(self.db, self.kb, self.settings, self.catalog, record, ...)."""

    # ---- 조회·출력 ---------------------------------------------------------------------------

    def document_facts(self) -> dict[str, dict]:
        return {
            p: cat.spec(self.catalog, p)
            for p in cat.all_paths(self.catalog)
            if cat.is_document_fact(self.catalog, p)
        }

    def get_document(self, case, doc_id: str) -> Document:
        doc = self.db.get(Document, doc_id)
        if doc is None or doc.case_id != case.id:
            raise ApiError(404, "DOCUMENT_NOT_FOUND", "서류를 찾을 수 없습니다")
        return doc

    def value_out(self, v: DocumentValue) -> dict:
        return {
            "id": v.id,
            "document_id": v.document_id,
            "document_version": v.document_version,
            "fact_key": v.fact_key,
            "value": v.value,
            "unit": v.unit,
            "status": v.status,
            "reviewer": v.reviewer,
            "reviewed_at": pr.iso(v.reviewed_at),
            "note": v.note,
            "created_at": pr.iso(v.created_at),
            "updated_at": pr.iso(v.updated_at),
        }

    def document_out(self, doc: Document) -> dict:
        values = self.db.scalars(
            select(DocumentValue)
            .where(DocumentValue.document_id == doc.id)
            .order_by(DocumentValue.created_at, DocumentValue.id)
        )
        return {
            "id": doc.id,
            "filename": doc.filename,
            "content_type": doc.content_type,
            "size": doc.size,
            "sha256": doc.sha256,
            "extracted_facts": doc.extracted_facts,
            "version": doc.version,
            "created_at": pr.iso(doc.created_at),
            "updated_at": pr.iso(doc.updated_at),
            "values": [self.value_out(v) for v in values],
        }

    def documents_out(self, case) -> list[dict]:
        docs = self.db.scalars(
            select(Document).where(Document.case_id == case.id).order_by(Document.created_at)
        )
        return [self.document_out(d) for d in docs]

    # ---- 입력 검사 ---------------------------------------------------------------------------

    def check_file(self, filename: str, content_type: str | None, data: bytes) -> str:
        if len(data) > self.settings.max_upload_bytes:
            raise ApiError(413, "FILE_TOO_LARGE", "파일이 너무 큽니다")
        kind = file_kind(filename, content_type)
        if kind is None or not content_matches(kind, data):
            raise ApiError(415, "UNSUPPORTED_DOCUMENT", "PDF·사진·텍스트 파일만 올릴 수 있습니다")
        if kind == "image" and not self.settings.ocr_enabled:
            raise ApiError(
                415,
                "UNSUPPORTED_DOCUMENT",
                "사진 읽기가 꺼져 있습니다. PDF를 올리거나 값을 직접 적어 주세요",
            )
        return kind

    def check_values(self, raw: dict[str, Any], units: dict[str, str | None] | None = None):
        """서류 값 형식 검사. 하나라도 틀리면 422(details.problems)이고 아무것도 저장하지 않는다."""
        out, problems = {}, []
        doc_facts = self.document_facts()
        for key, value in raw.items():
            if key not in doc_facts:
                reason = (
                    "카탈로그에 없는 사실"
                    if cat.spec(self.catalog, key) is None
                    else "서류로 받지 않는 값"
                )
                problems.append({"key": key, "value": value, "reason": reason})
                continue
            unit = (units or {}).get(key)
            if unit and unit != doc_facts[key].get("unit"):
                problems.append({"key": key, "value": value, "reason": "단위가 다름"})
                continue
            try:
                out[key] = cat.validate(self.catalog, key, value, allow_range=True)
            except cat.FactValueError as e:
                problems.append({"key": key, "value": value, "reason": e.reason})
        if problems:
            raise ApiError(
                422, "VALIDATION_ERROR", "서류 값 형식이 올바르지 않습니다", {"problems": problems}
            )
        return out

    def parse_facts(self, facts: str | None) -> dict[str, Any]:
        if not facts:
            return {}
        try:
            raw = json.loads(facts)
        except ValueError:
            raise ApiError(422, "VALIDATION_ERROR", "facts는 JSON 객체여야 합니다") from None
        if not isinstance(raw, dict):
            raise ApiError(422, "VALIDATION_ERROR", "facts는 JSON 객체여야 합니다")
        return self.check_values(raw)

    # ---- 표 자동 읽기 --------------------------------------------------------------------------

    def read_tables(
        self, kind: str, filename: str, content_type: str | None, data: bytes, doc_id: str, skip
    ) -> tuple[list[tuple[str, Any, str]], dict | None]:
        """시험성적서 표에서 서류 사실 후보를 읽는다: (후보[(사실, 값, 메모)], 요약).

        읽기가 실패해도 업로드는 실패시키지 않는다(사람이 직접 적을 수 있다).
        """
        if not self.settings.document_table_reading or kind not in ("pdf", "image"):
            return [], None
        by_read = {
            s["evidence"]["read_key"]: p
            for p, s in self.document_facts().items()
            if (s.get("evidence") or {}).get("read_key") and p not in skip
        }
        if not by_read:
            return [], None
        try:
            report = read_test_report(
                data,
                filename,
                content_type,
                settings=self.settings,
                document_id=doc_id,
                requested_keys=list(by_read),
                azure_client=getattr(self, "azure_client", None),
            )
        except Exception as exc:  # 읽기 실패는 업로드 실패가 아니다(사람이 직접 적을 수 있다)
            logger.warning("Test report reading failed: %r", exc)
            return [], {"errors": [{"code": "READ_FAILED", "message": type(exc).__name__}]}
        res, ext = report.result, report.extraction
        candidates, rejected = [], []
        for item in res.facts:
            path = by_read.get(item.key)
            if path is None or item.status is not ItemStatus.FOUND:
                continue
            try:
                value = self.check_values({path: item_value(item)})[path]
            except ApiError as exc:
                rejected.append({"key": path, "reason": exc.details.get("problems")})
                continue
            raw = " ".join(x for x in (item.value_raw, item.unit_raw) if x)
            note = f"표 자동 읽기(검수 대기) · {_where(item)} · 원문 {raw!r}"
            if item.below_detection_limit:
                note += f" · 불검출(검출한계 {item.detection_limit:g} 미만으로 봄)"
            candidates.append((path, value, note[:500]))

        def summary_item(it: ExtractedFactItem) -> dict:
            out = it.model_dump(mode="json", include=SUMMARY_FIELDS, exclude_none=True)
            out["key"] = by_read.get(it.key, it.key)  # 화면은 엔진 사실 키로 본다
            if report.rejected.get(it.key):
                out["guard_reasons"] = report.rejected[it.key]
            return out

        summary = {
            "backend": ext.backend if ext else None,
            "source": ext.source if ext else None,
            "route": report.route,
            "doc_type": res.detected_doc_type.value,
            "tables": len(ext.tables) if ext else 0,
            "items": [
                summary_item(it) for it in res.facts if it.status is not ItemStatus.NOT_FOUND
            ],
            "not_found": [
                by_read.get(it.key, it.key) for it in res.facts if it.status is ItemStatus.NOT_FOUND
            ],
            "value_check_failed": rejected,
            "warnings": [w.model_dump(mode="json", exclude_none=True) for w in res.warnings],
            "errors": [e.model_dump(mode="json") for e in res.errors],
        }
        return candidates, summary

    # ---- 쓰기 -------------------------------------------------------------------------------

    def _store_candidates(
        self, case, doc: Document, manual: dict, kind: str, data: bytes, content_type
    ) -> list[DocumentValue]:
        rows = [
            DocumentValue(
                id=new_id(),
                document_id=doc.id,
                case_id=case.id,
                document_version=doc.version,
                fact_key=k,
                value=v,
                unit=(cat.spec(self.catalog, k) or {}).get("unit"),
                status="UNVERIFIED",
                note="직접 입력(검수 대기)",
            )
            for k, v in manual.items()
        ]
        table, summary = self.read_tables(
            kind, doc.filename, content_type, data, doc.id, skip=set(manual)
        )
        rows += [
            DocumentValue(
                id=new_id(),
                document_id=doc.id,
                case_id=case.id,
                document_version=doc.version,
                fact_key=k,
                value=v,
                unit=(cat.spec(self.catalog, k) or {}).get("unit"),
                status="UNVERIFIED",
                note=note,
            )
            for k, v, note in table
        ]
        method = "+".join(m for m, on in (("manual", manual), ("table", table)) if on) or "none"
        extracted = {
            "method": method,
            "candidates": {r.fact_key: r.value for r in rows},
            "accepted": {},
        }
        if summary is not None:
            extracted["table_read"] = summary
        doc.extracted_facts = extracted
        for r in rows:
            self.db.add(r)
        return rows

    def upload_document(
        self,
        company: Company,
        case_id: str,
        *,
        filename: str,
        content_type: str | None,
        data: bytes,
        facts: str | None,
    ) -> dict:
        case = self.get_case(company, case_id)
        self.writable(case)
        kind = self.check_file(filename, content_type, data)
        # 건당 서류 수 상한: 사진·스캔본 읽기(OCR)는 쪽마다 과금되므로 반복 업로드를 묶어 둔다
        count = len(self.db.scalars(select(Document.id).where(Document.case_id == case.id)).all())
        if count >= self.settings.max_documents_per_case:
            raise ApiError(
                409,
                "TOO_MANY_DOCUMENTS",
                f"서류는 한 건에 {self.settings.max_documents_per_case}개까지 올릴 수 있습니다",
            )
        manual = self.parse_facts(facts)
        doc = Document(
            id=new_id(),
            case_id=case.id,
            filename=(filename or "document")[:255],
            content_type=_ct(content_type) or None,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            version=1,
            extracted_facts={},
        )
        self.db.add(doc)
        self.db.flush()
        rows = self._store_candidates(case, doc, manual, kind, data, content_type)
        turn_id = new_id()
        self.log(case, turn_id, "user", f"서류를 올렸어요: {doc.filename}", document_id=doc.id)
        turn = self.finish_turn(
            case, turn_id, "DOCUMENT", {"document_id": doc.id, "candidates": len(rows)}
        )
        self.commit()
        return {
            "document": self.document_out(doc),
            "turn": turn,
            "values": [self.value_out(r) for r in rows],
        }

    def replace_document(
        self,
        company: Company,
        case_id: str,
        doc_id: str,
        *,
        filename: str,
        content_type: str | None,
        data: bytes,
        facts: str | None,
    ) -> dict:
        """파일 교체: 버전 +1, 이전 버전의 적용 값·대기 후보는 효력 해제(REVOKED)."""
        case = self.get_case(company, case_id)
        self.writable(case)
        doc = self.get_document(case, doc_id)
        kind = self.check_file(filename, content_type, data)
        manual = self.parse_facts(facts)
        turn_id = new_id()
        revoked = self._revoke_values(case, doc, None, turn_id)
        old = doc.version
        doc.version += 1
        doc.filename = (filename or doc.filename)[:255]
        doc.content_type = _ct(content_type) or None
        doc.size, doc.sha256, doc.updated_at = len(data), hashlib.sha256(data).hexdigest(), now()
        rows = self._store_candidates(case, doc, manual, kind, data, content_type)
        self.log(case, turn_id, "user", f"서류를 바꿔 올렸어요: {doc.filename}", document_id=doc.id)
        turn = self.finish_turn(
            case,
            turn_id,
            "DOCUMENT",
            {"document_id": doc.id, "replaced_version": old, "revoked_keys": revoked},
        )
        self.commit()
        return {
            "document": self.document_out(doc),
            "turn": turn,
            "values": [self.value_out(r) for r in rows],
        }

    def apply_values(self, company: Company, case_id: str, doc_id: str, items: list[dict]) -> dict:
        """서버가 검수한 값을 판정에 반영한다(EVIDENCED, 출처 DOCUMENT, 근거 '문서id@v버전')."""
        case = self.get_case(company, case_id)
        self.writable(case)
        doc = self.get_document(case, doc_id)
        sent = sorted({i["document_version"] for i in items})
        if sent != [doc.version]:
            raise ApiError(
                409,
                "DOCUMENT_VERSION_MISMATCH",
                "서류가 그사이 바뀌었습니다. 최신 버전으로 다시 검수해 주세요",
                {"document_id": doc.id, "current_version": doc.version, "sent_versions": sent},
            )
        rows = {
            v.id: v
            for v in self.db.scalars(
                select(DocumentValue).where(DocumentValue.document_id == doc.id)
            )
        }
        # 형식 검사를 먼저 모두 한다(하나라도 틀리면 아무것도 저장하지 않음)
        plan, problems = [], []
        for idx, it in enumerate(items):
            row = rows.get(it.get("value_id") or "")
            if it.get("value_id") and (row is None or row.status != "UNVERIFIED"):
                problems.append(
                    {"index": idx, "value_id": it["value_id"], "reason": "검수 대기 값이 아님"}
                )
                continue
            if it.get("reject"):
                plan.append((row, None, None, it))
                continue
            key = row.fact_key if row else it.get("fact_key")
            value = row.value if (row and it.get("value") is None) else it.get("value")
            try:
                checked = self.check_values({key: value}, {key: it.get("unit")})[key]
            except ApiError as exc:
                problems += [{"index": idx, **p} for p in exc.details.get("problems", [])]
                continue
            plan.append((row, key, checked, it))
        if problems:
            raise ApiError(
                422, "VALIDATION_ERROR", "서류 값 형식이 올바르지 않습니다", {"problems": problems}
            )
        turn_id = new_id()
        ref = f"{doc.id}@v{doc.version}"
        applied = []
        for row, key, value, it in plan:
            when = it.get("reviewed_at") or now()
            if row is not None and it.get("reject"):
                row.status, row.updated_at = "REJECTED", now()
                row.reviewer, row.reviewed_at = it.get("reviewer"), when
                continue
            if row is None:
                row = DocumentValue(
                    id=new_id(),
                    document_id=doc.id,
                    case_id=case.id,
                    document_version=doc.version,
                    fact_key=key,
                    unit=(cat.spec(self.catalog, key) or {}).get("unit"),
                    note="검수에서 직접 입력",
                )
                self.db.add(row)
            elif value != row.value:
                row.note = f"{row.note or ''} · 검수에서 고침(원래 {row.value!r})".strip(" ·")
            row.value, row.status, row.updated_at = value, "APPLIED", now()
            row.reviewer, row.reviewed_at = it.get("reviewer"), when
            self.record(case, key, value, "DOCUMENT", turn_id, source_ref=ref)
            applied.append(key)
        turn = self.finish_turn(
            case, turn_id, "APPLY", {"document_id": doc.id, "version": doc.version, "keys": applied}
        )
        self.commit()
        return turn

    def _revoke_values(self, case, doc: Document, version: int | None, turn_id: str) -> list[str]:
        """그 서류(버전)의 적용 값·대기 후보를 REVOKED로 두고, 거기서 온 유효 사실을 철회한다."""
        q = select(DocumentValue).where(
            DocumentValue.document_id == doc.id,
            DocumentValue.status.in_(("APPLIED", "UNVERIFIED")),
        )
        if version is not None:
            q = q.where(DocumentValue.document_version == version)
        for v in self.db.scalars(q):
            v.status, v.updated_at = "REVOKED", now()
        refs = {f"{doc.id}@v{version}"} if version is not None else None
        keys = []
        for path, st in self.states(case).items():
            if st.source_type != "DOCUMENT" or not st.source_ref:
                continue
            same_doc = st.source_ref.split("@")[0] == doc.id
            if same_doc and (refs is None or st.source_ref in refs):
                self.record(case, path, "retract", "DOCUMENT", turn_id, source_ref=st.source_ref)
                keys.append(path)
        return keys

    def revoke_document(
        self,
        company: Company,
        case_id: str,
        doc_id: str,
        *,
        reason: str | None,
        document_version: int | None,
    ) -> dict:
        case = self.get_case(company, case_id)
        self.writable(case)
        doc = self.get_document(case, doc_id)
        if document_version is not None and not 1 <= document_version <= doc.version:
            raise ApiError(
                409,
                "DOCUMENT_VERSION_MISMATCH",
                "없는 서류 버전입니다",
                {
                    "document_id": doc.id,
                    "current_version": doc.version,
                    "sent_versions": [document_version],
                },
            )
        turn_id = new_id()
        keys = self._revoke_values(case, doc, document_version, turn_id)
        turn = self.finish_turn(
            case,
            turn_id,
            "REVOKE",
            {"document_id": doc.id, "version": document_version, "reason": reason, "keys": keys},
        )
        self.commit()
        return turn
