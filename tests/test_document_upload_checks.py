"""서류 업로드 검사: 실제 내용(매직 바이트)이 형식과 맞는지, 건당 서류 수 상한."""

from app.interview.documents import content_matches
from tests.conftest import make_client
from tests.test_documents import PNG, to_evidence_request, upload

OCR = {
    "allow_document_ocr": True,
    "azure_docintel_endpoint": "https://example.invalid/",
    "azure_docintel_api_key": "fake",
}
EXE = b"MZ\x90\x00" + b"\x00" * 64


def test_upload_rejects_content_that_does_not_match_its_type(tmp_path):
    with make_client(tmp_path, **OCR) as c:
        cid, _ = to_evidence_request(c)
        cases = [
            ("a.svg", b"<svg onload=alert(1)>", "image/svg+xml"),
            ("a.jpg.exe", EXE, "image/jpeg"),
            ("fake.pdf", EXE, "application/pdf"),
            ("bin.txt", EXE, "text/plain"),
        ]
        for name, data, ctype in cases:
            res = upload(c, cid, name=name, data=data, ctype=ctype)
            assert res.status_code == 415, name
            assert res.json()["detail"]["code"] == "UNSUPPORTED_DOCUMENT"


def test_content_matches_known_signatures():
    assert content_matches("pdf", b"%PDF-1.7\n")
    assert content_matches("image", b"\xff\xd8\xff\xe0rest")
    assert content_matches("image", PNG)
    assert content_matches("image", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 8)
    assert content_matches("text", "납 0.5 mg/L".encode())
    assert content_matches("text", "납 0.5 mg/L".encode("cp949"))
    assert not content_matches("image", b"GIF89a")


def test_documents_per_case_are_capped(tmp_path):
    with make_client(tmp_path, max_documents_per_case=2) as c:
        cid, _ = to_evidence_request(c)
        assert upload(c, cid).status_code == 201
        assert upload(c, cid).status_code == 201
        res = upload(c, cid)
        assert res.status_code == 409
        assert res.json()["detail"]["code"] == "TOO_MANY_DOCUMENTS"
