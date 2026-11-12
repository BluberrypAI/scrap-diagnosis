"""업로드 API ↔ 시험성적서 표 자동 읽기.

읽은 값은 검수 대기 후보(UNVERIFIED)일 뿐 판정에 쓰지 않는다.

설계 docs/design/test-report-table-extraction.md 13절. Azure 호출은 가짜로 바꾼다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.tables import PageInfo, TableCell, TableExtraction, TableGrid
from app.reading import azure_tables
from tests.api_support import Api, build_app, fake_llm
from tests.pdf_fixtures import scanned_like_pdf, simple_report_pdf
from tests.test_handoff import NOT_WASTE_FACTS


@pytest.fixture
def api(real_kb, tmp_path) -> Api:
    app = build_app(real_kb, tmp_path / "tbl.db", fake_llm())
    a = Api(client=TestClient(app), app=app, llm=None, db_path=tmp_path / "tbl.db")
    return a.use(a.company(profile={"facts": NOT_WASTE_FACTS}))


@pytest.fixture
def ocr(monkeypatch):
    """OCR을 켠 것처럼 하고, Azure 대신 정해 둔 표를 돌려준다. 호출 기록을 돌려준다."""
    calls: list[str] = []
    fake = TableExtraction(
        source="ocr",
        pages=[PageInfo(page=1, text="시험성적서 카드뮴 0.05 mg/L")],
        tables=[
            TableGrid(
                page=1,
                table_index=0,
                n_rows=2,
                n_cols=3,
                source="ocr",
                cells=[
                    TableCell(row=r, col=c, text=t, confidence=0.99, is_header=r == 0)
                    for r, row in enumerate(
                        [["시험항목", "결과", "단위"], ["카드뮴", "0.05", "mg/L"]]
                    )
                    for c, t in enumerate(row)
                ],
            )
        ],
        backend="azure-prebuilt-layout",
    )

    def fake_analyze(data, ct, *, settings, client=None):  # noqa: ANN001, ANN202
        calls.append(ct)
        return fake

    monkeypatch.setattr(Settings, "ocr_enabled", property(lambda self: True))
    monkeypatch.setattr(azure_tables, "analyze_layout", fake_analyze)
    return calls


@pytest.fixture
def no_ocr(monkeypatch):
    monkeypatch.setattr(Settings, "ocr_enabled", property(lambda self: False))


def _upload(api: Api, content: bytes, filename: str, ct: str, facts: str | None = None):  # noqa: ANN202
    cid = api.create_case()["case"]["id"]
    return cid, api.upload(cid, content, filename, ct, facts=facts)


def _doc_facts(api: Api, cid: str) -> list[dict]:
    facts = api.get(f"/cases/{cid}/trace").json()["sessions"][0]["facts"]
    return [f for f in facts if f["source_type"] == "DOCUMENT"]


def test_text_pdf_values_become_unverified_candidates(api, no_ocr):
    cid, r = _upload(api, simple_report_pdf(), "report.pdf", "application/pdf")
    assert r.status_code == 201, r.text
    body = r.json()
    vals = {v["fact_key"]: v for v in body["values"]}
    assert vals["leach_pb"]["value"] == 0.12 and vals["leach_pb"]["unit"] == "mg/L"
    assert vals["leach_pb"]["status"] == "UNVERIFIED"
    assert "표 자동 읽기" in vals["leach_pb"]["note"] and "1쪽 표1" in vals["leach_pb"]["note"]
    # 불검출은 0이 아니라 '검출한계 미만' 구간
    assert vals["leach_cd"]["value"]["hi"] == 0.01 and vals["leach_cd"]["value"]["lo"] is None
    ef = body["document"]["extracted_facts"]
    assert ef["method"] == "table"
    tr = ef["table_read"]
    assert tr["backend"] == "pdfplumber" and tr["tables"] >= 1
    pb = next(i for i in tr["items"] if i["key"] == "leach_pb")
    assert pb["status"] == "FOUND" and pb["cell_ref"]["page"] == 1
    # 판정에는 아직 쓰지 않는다(검수 전)
    assert _doc_facts(api, cid) == []


def test_auto_candidates_apply_after_review(api, no_ocr):
    cid, r = _upload(api, simple_report_pdf(), "report.pdf", "application/pdf")
    body = r.json()
    pb = next(v for v in body["values"] if v["fact_key"] == "leach_pb")
    a = api.apply(cid, body["document"]["id"], [{"value_id": pb["id"], "document_version": 1}])
    assert a.status_code == 200, a.text
    (fact,) = _doc_facts(api, cid)
    assert fact["key"] == "leach_pb" and fact["status"] == "EVIDENCED"


def test_manual_facts_win_over_table(api, no_ocr):
    _, r = _upload(
        api, simple_report_pdf(), "report.pdf", "application/pdf", facts='{"leach_pb": 0.5}'
    )
    assert r.status_code == 201, r.text
    body = r.json()
    pb = [v for v in body["values"] if v["fact_key"] == "leach_pb"]
    assert len(pb) == 1 and pb[0]["value"] == 0.5 and "직접 입력" in pb[0]["note"]
    assert body["document"]["extracted_facts"]["method"] == "manual+table"
    assert any(v["fact_key"] == "leach_cd" for v in body["values"])


def test_text_file_is_not_table_read(api, no_ocr):
    _, r = _upload(api, b"lead 0.1", "memo.txt", "text/plain")
    ef = r.json()["document"]["extracted_facts"]
    assert ef["method"] == "none" and "table_read" not in ef


def test_scanned_pdf_without_ocr_still_uploads(api, no_ocr):
    _, r = _upload(api, scanned_like_pdf(), "scan.pdf", "application/pdf")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["values"] == []
    assert body["document"]["extracted_facts"]["table_read"]["errors"][0]["code"] == (
        "EMPTY_CONTENT"
    )


def test_scanned_pdf_with_ocr(api, ocr):
    cid, r = _upload(api, scanned_like_pdf(), "scan.pdf", "application/pdf")
    assert r.status_code == 201, r.text
    assert ocr == ["application/pdf"]
    body = r.json()
    (cd,) = [v for v in body["values"] if v["fact_key"] == "leach_cd"]
    assert cd["value"] == 0.05 and cd["status"] == "UNVERIFIED"
    assert body["document"]["extracted_facts"]["table_read"]["source"] == "ocr"


def test_image_rejected_without_ocr(api, no_ocr):
    _, r = _upload(api, b"\x89PNG\r\n\x1a\n", "photo.png", "image/png")
    assert r.status_code == 415
    assert "문서 인식" in r.text


def test_image_with_ocr(api, ocr):
    _, r = _upload(api, b"\x89PNG\r\n\x1a\n", "photo.png", "image/png")
    assert r.status_code == 201, r.text
    assert ocr == ["image/png"]
    assert [v["fact_key"] for v in r.json()["values"]] == ["leach_cd"]


def test_replace_document_rereads_tables(api, no_ocr):
    cid, r = _upload(api, b"memo", "memo.txt", "text/plain")
    doc_id = r.json()["document"]["id"]
    r2 = api.post(
        f"/cases/{cid}/documents/{doc_id}/versions",
        files={"file": ("report.pdf", simple_report_pdf(), "application/pdf")},
    )
    assert r2.status_code == 201, r2.text
    vals = r2.json()["values"]
    assert {v["fact_key"] for v in vals} >= {"leach_pb", "leach_cd"}
    assert all(v["document_version"] == 2 for v in vals)
