"""서류(성적서) 흐름: 기름 묻음 → 서류 요청 → 업로드(검수 대기) → 적용(EVIDENCED) → 판정."""

import json
from types import SimpleNamespace as NS

from conftest import headers, make_client
from test_api import PP_SCRAP, new_case, reply, run_answers

from tests.pdf_fixtures import HEADER, _build, _table
from tests.test_azure_tables import _Doc, _FakeClient, _FakePoller, _page, _poly

H = headers()
OIL = "oil_pct_evidenced"


def to_evidence_request(client, h=H):
    """PP 스크랩, 기름이 묻었다고 답해 서류 요청 단계까지 간다."""
    cid = new_case(client, h=h)["case"]["id"]
    run_answers(client, cid, PP_SCRAP[:4], h=h)
    reply(client, cid, "Q-CONTAMINATION", "expand", h=h)
    reply(client, cid, "oil_presence", "present", h=h)
    reply(client, cid, "residue", "none", h=h)
    turn = reply(client, cid, "chemical_itself", "no", h=h).json()
    return cid, turn


def upload(client, cid, *, facts=None, name="values.txt", data=b"manual", ctype="text/plain"):
    form = {"facts": json.dumps(facts)} if facts is not None else {}
    return client.post(
        f"/internal/v1/cases/{cid}/documents",
        files={"file": (name, data, ctype)},
        data=form,
        headers=H,
    )


def apply(client, cid, doc, values, **extra):
    body = {
        "values": [
            {"value_id": v["id"], "document_version": doc["version"], "reviewer": "u1", **extra}
            for v in values
        ]
    }
    return client.post(
        f"/internal/v1/cases/{cid}/documents/{doc['id']}/values/apply", json=body, headers=H
    )


def finish(client, cid, turn):
    while turn["branch"] == "ASK_FACT":
        q = turn["ui"]["question"]
        turn = reply(client, cid, q["key"], "none_all" if q["unit"] == "group" else "yes").json()
    return turn


def test_oil_present_requests_test_report(client):
    cid, turn = to_evidence_request(client)
    assert turn["branch"] == "REQUEST_EVIDENCE"
    assert turn["ui"]["question"] is None
    docs = turn["ui"]["requested_documents"]
    assert [(d["evidence_type"], d["facts"]) for d in docs] == [("TEST_REPORT", [OIL])]
    assert turn["ui"]["board"]["documents_needed"] == docs
    assert turn["ui"]["board"]["pending"][0]["reason"] == "NEEDS_EVIDENCE"
    detail = client.get(f"/internal/v1/cases/{cid}", headers=H).json()
    assert detail["case"]["status"] == "NEEDS_INFO"


def test_oil_value_by_button_is_rejected(client):
    cid, _ = to_evidence_request(client)
    res = reply(client, cid, OIL, 2)
    assert res.status_code == 422
    assert res.json()["detail"]["details"]["problems"][0]["reason"] == "서류로만 받는 값"


def test_refusing_document_stops_at_designated_possible(client):
    cid, _ = to_evidence_request(client)
    res = client.post(
        f"/internal/v1/cases/{cid}/diagnosis/messages", json={"text": "서류가 없어요"}, headers=H
    )
    turn = finish(client, cid, res.json())
    assert turn["ui"]["result"]["outcome"] == "DESIGNATED_POSSIBLE"


def test_upload_is_candidate_only_then_apply_decides(client):
    cid, _ = to_evidence_request(client)
    res = upload(client, cid, facts={OIL: {"hi": 0.5, "hi_inc": False}})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["turn"]["branch"] == "REQUEST_EVIDENCE"  # 검수 전에는 판정이 그대로
    assert [v["status"] for v in body["values"]] == ["UNVERIFIED"]
    assert body["document"]["extracted_facts"]["method"] == "manual"
    turn = apply(client, cid, body["document"], body["values"]).json()
    turn = finish(client, cid, turn)
    assert turn["ui"]["result"]["code"] == "51-03-01"
    fact = next(f for f in turn["ui"]["board"]["facts"] if f["key"] == OIL)
    assert (fact["status"], fact["source_type"], fact["editable"]) == (
        "EVIDENCED",
        "DOCUMENT",
        False,
    )
    assert fact["value_label"] == "0.5% 미만"
    h = client.post(f"/internal/v1/cases/{cid}/confirm", headers=H).json()["handoff"]
    assert h["evidence"] == [{"fact": OIL, "document_id": body["document"]["id"]}]
    conv = client.get(f"/internal/v1/cases/{cid}", headers=H).json()["conversation"]
    assert any(m.get("document_id") == body["document"]["id"] for m in conv)


def test_oil_ge5_is_designated_possible(client):
    cid, _ = to_evidence_request(client)
    body = upload(client, cid, facts={OIL: 7.5}).json()
    turn = finish(client, cid, apply(client, cid, body["document"], body["values"]).json())
    assert turn["ui"]["result"]["outcome"] == "DESIGNATED_POSSIBLE"
    assert "5% 이상" in turn["ui"]["result"]["reason"]


def test_reviewer_can_fix_or_reject(client):
    cid, _ = to_evidence_request(client)
    body = upload(client, cid, facts={OIL: 7.5}).json()
    doc = body["document"]
    turn = apply(client, cid, doc, body["values"], value=1.0).json()  # 검수에서 고침
    assert turn["branch"] != "REQUEST_EVIDENCE"
    value = client.get(f"/internal/v1/cases/{cid}", headers=H).json()["documents"][0]["values"][0]
    assert value["status"] == "APPLIED" and value["value"] == 1.0 and "고침" in value["note"]
    other = upload(client, cid, facts={OIL: 3}).json()
    apply(client, cid, other["document"], other["values"], reject=True)
    detail = client.get(f"/internal/v1/cases/{cid}", headers=H).json()
    assert detail["documents"][1]["values"][0]["status"] == "REJECTED"


def test_version_mismatch_replace_and_revoke(client):
    cid, _ = to_evidence_request(client)
    body = upload(client, cid, facts={OIL: 1}).json()
    doc = body["document"]
    res = client.post(
        f"/internal/v1/cases/{cid}/documents/{doc['id']}/values/apply",
        json={"values": [{"value_id": body["values"][0]["id"], "document_version": 2}]},
        headers=H,
    )
    assert res.status_code == 409 and res.json()["detail"]["code"] == "DOCUMENT_VERSION_MISMATCH"
    assert apply(client, cid, doc, body["values"]).json()["branch"] != "REQUEST_EVIDENCE"
    # 파일 교체: 이전 버전의 적용 값은 효력 해제 → 다시 서류 요청
    res = client.post(
        f"/internal/v1/cases/{cid}/documents/{doc['id']}/versions",
        files={"file": ("new.txt", b"v2", "text/plain")},
        headers=H,
    )
    assert res.status_code == 201
    assert res.json()["document"]["version"] == 2
    assert res.json()["turn"]["branch"] == "REQUEST_EVIDENCE"
    statuses = [v["status"] for v in res.json()["document"]["values"]]
    assert statuses == ["REVOKED"]
    # 새 버전 값 적용 후 효력 해제
    body2 = upload(client, cid, facts={OIL: 2}).json()
    apply(client, cid, body2["document"], body2["values"])
    res = client.post(
        f"/internal/v1/cases/{cid}/documents/{body2['document']['id']}/revoke",
        json={"reason": "잘못 올림"},
        headers=H,
    )
    assert res.status_code == 200 and res.json()["branch"] == "REQUEST_EVIDENCE"


def test_upload_errors(client):
    cid, _ = to_evidence_request(client)
    assert upload(client, cid, name="a.exe", ctype="application/octet-stream").status_code == 415
    res = upload(client, cid, name="s.png", ctype="image/png")  # 사진 읽기가 꺼져 있음
    assert res.status_code == 415 and res.json()["detail"]["code"] == "UNSUPPORTED_DOCUMENT"
    res = upload(client, cid, facts={"material": "pp"})
    assert res.status_code == 422
    assert res.json()["detail"]["details"]["problems"][0]["reason"] == "서류로 받지 않는 값"
    res = upload(client, cid, facts={OIL: "약 2"})
    assert res.status_code == 422
    res = client.post(f"/internal/v1/cases/{cid}/documents/nope/revoke", json={}, headers=H)
    assert res.status_code == 404 and res.json()["detail"]["code"] == "DOCUMENT_NOT_FOUND"


def test_file_too_large(tmp_path):
    with make_client(tmp_path, max_upload_bytes=10) as c:
        cid = new_case(c)["case"]["id"]
        res = upload(c, cid, data=b"x" * 11)
        assert res.status_code == 413 and res.json()["detail"]["code"] == "FILE_TOO_LARGE"


def test_pdf_table_is_read_into_candidates(client):
    cid, _ = to_evidence_request(client)
    pdf = _build(
        [
            _table(
                [
                    HEADER,
                    ["기름성분", "ES 06302.1b", "0.8", "%", "5"],
                    ["납(Pb)", "ES 06402.1", "0.12", "mg/L", "3"],
                ]
            )
        ]
    )
    body = upload(client, cid, name="report.pdf", data=pdf, ctype="application/pdf").json()
    ext = body["document"]["extracted_facts"]
    assert ext["method"] == "table" and ext["table_read"]["backend"] == "pdfplumber"
    assert [(v["fact_key"], v["value"], v["status"]) for v in body["values"]] == [
        (OIL, 0.8, "UNVERIFIED")
    ]
    assert body["values"][0]["note"].startswith("표 자동 읽기")
    assert [i["key"] for i in ext["table_read"]["items"]] == [OIL]  # 엔진 사실 키로 보인다


def _photo_result():
    d = _Doc()
    cells = [
        d.cell(1, 0, 0, "시험항목", (1, 2, 3, 2.5), kind="columnHeader"),
        d.cell(1, 0, 1, "결과", (3, 2, 4, 2.5), kind="columnHeader"),
        d.cell(1, 0, 2, "단위", (4, 2, 5, 2.5), kind="columnHeader"),
        d.cell(1, 1, 0, "기름성분", (1, 2.5, 3, 3)),
        d.cell(1, 1, 1, "1.2", (3, 2.5, 4, 3)),
        d.cell(1, 1, 2, "%", (4, 2.5, 5, 3)),
    ]
    table = NS(
        row_count=2,
        column_count=3,
        cells=cells,
        bounding_regions=[NS(page_number=1, polygon=_poly(1, 2, 5, 3))],
    )
    page = _page(1, [("시험성적서", (1, 1, 4, 1.3))], d.words[1])
    return NS(model_id="prebuilt-layout", pages=[page], tables=[table])


def test_photo_is_read_with_ocr_when_enabled(tmp_path):
    ocr = {
        "allow_document_ocr": True,
        "azure_docintel_endpoint": "https://example.invalid/",
        "azure_docintel_api_key": "fake",
    }
    with make_client(tmp_path, **ocr) as c:
        fake = _FakeClient(_FakePoller(_photo_result()))
        c.app.state.azure_client = fake
        cid, _ = to_evidence_request(c)
        body = upload(c, cid, name="photo.png", data=b"img", ctype="image/png").json()
        assert body["document"]["extracted_facts"]["table_read"]["source"] == "ocr"
        assert [(v["fact_key"], v["value"]) for v in body["values"]] == [(OIL, 1.2)]
        assert len(fake.calls) == 1  # Azure는 사진 한 장에 한 번만 부른다
