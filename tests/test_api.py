"""M4 API: 응답 스키마 계약(docs/engine/algorithm.md 7절), 상태 전이, 문서 증빙,
confirm/reopen, Trace, 기업 격리.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent.golden import normalize_extract
from app.persistence.db import ImmutableTraceError
from app.persistence.models import Document, FactRecord, TraceRecord
from tests.api_support import Api, build_app, fake_llm, minimal_pdf, to_film_oil_question

TURN_KEYS = {"case_id", "session_id", "turn_id", "branch", "message", "verdict", "ui"}
TURN_KEYS |= {"case_status"}
VERDICT_KEYS = {
    "status",
    "waste_code",
    "waste_name",
    "category",
    "candidates",
    "conditions",
    "rationale",
    "failure_reason",
}
UI_KEYS = {"can_confirm", "suggested_replies", "requested_documents"}
BRANCHES = {"RESOLVE_CONFLICT", "UNSUPPORTED", "ASK_FACT", "REQUEST_EVIDENCE", "FINAL_REVIEW"}
VERDICT_STATUSES = {"CONFIRMABLE", "NEEDS_EVIDENCE", "UNDETERMINABLE", "IN_PROGRESS"}


def assert_turn_contract(t: dict, case_id: str | None = None) -> None:
    assert set(t) >= TURN_KEYS
    assert set(t["verdict"]) >= VERDICT_KEYS
    assert set(t["ui"]) >= UI_KEYS
    assert t["branch"] in BRANCHES
    assert t["verdict"]["status"] in VERDICT_STATUSES
    assert isinstance(t["message"], str) and t["message"]
    assert isinstance(t["ui"]["can_confirm"], bool)
    for c in t["verdict"]["candidates"]:
        assert set(c) >= {"code", "rule_ids"}
    for c in t["verdict"]["conditions"]:
        assert set(c) >= {"fact", "text", "satisfied", "evidence"}
    if case_id is not None:
        assert t["case_id"] == case_id


@pytest.fixture
def api(kb, tmp_path) -> Api:
    llm = fake_llm()
    app = build_app(kb, tmp_path / "api.db", llm)
    a = Api(client=TestClient(app), app=app, llm=llm, db_path=tmp_path / "api.db")
    return a.use(a.company())


def finish_with_document(api: Api, case_id: str) -> dict:
    to_film_oil_question(api, case_id)
    return api.submit_document(case_id, {"oil_content_pct": 2}, b"oil 2%")["turn"]


# ---- 응답 스키마·생성 --------------------------------------------------------------------


def test_create_case_schema_and_memo_extraction(api):
    api.llm.push(
        "extract", normalize_extract({"facts": [{"key": "material", "value": "PP", "quote": "PP"}]})
    )
    body = api.create_case(memo="PP 필름 자투리", period="2026-11")
    case, turn = body["case"], body["turn"]
    assert case["status"] == "DIAGNOSING" and case["session_id"] == turn["session_id"]
    assert case["memo"] == "PP 필름 자투리" and case["quantity"] == 1.5 and case["unit"] == "t"
    assert_turn_contract(turn, case["id"])
    assert turn["branch"] == "ASK_FACT" and turn["case_status"] == "DIAGNOSING"
    assert turn["ui"]["question"]["key"] != "material"  # 메모에서 소재를 뽑았으므로 다시 묻지 않음

    trace = api.get(f"/cases/{case['id']}/trace").json()
    facts = trace["sessions"][0]["facts"]
    by_key = {f["key"]: f for f in facts}
    assert by_key["emission_facility"]["source_type"] == "PROFILE"  # 기업 프로필 사실
    assert "not_in_catalog" not in by_key  # 카탈로그 밖 키는 무시
    assert by_key["material"]["source_type"] == "UTTERANCE" and by_key["material"]["quote"] == "PP"
    first = trace["sessions"][0]["turns"][0]
    assert first["kind"] == "TURN" and first["payload"]["input_text"] == "PP 필름 자투리"
    assert first["payload"]["llm_calls"][0]["name"] == "extract"


def test_message_validation(api):
    cid = api.create_case()["case"]["id"]
    url = f"/cases/{cid}/diagnosis/messages"
    assert api.post(url, json={}).status_code == 422
    assert api.post(url, json={"text": "  "}).status_code == 422
    both = {"text": "PP", "quick_reply": {"key": "material", "value": "PP"}}
    assert api.post(url, json=both).status_code == 422


def test_quick_reply_flow_and_contract(api):
    cid = api.create_case()["case"]["id"]
    t = api.reply(cid, "material", "PP")
    assert_turn_contract(t, cid)
    t = to_film_oil_question(api, cid)
    assert t["branch"] == "ASK_FACT" and t["ui"]["question"]["key"] == "oil_content_pct"
    assert t["ui"]["suggested_replies"] and not t["ui"]["can_confirm"]
    detail = api.get(f"/cases/{cid}").json()
    assert detail["latest_turn"]["turn_id"] == t["turn_id"]
    assert detail["current_verdict"] is None and detail["verdicts"] == []


# ---- 상태 전이 ---------------------------------------------------------------------------


def test_status_transitions_and_list_filter(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    t = api.reply(cid, "oil_content_pct", kind="unknown")  # 모름 → 성적서 요청
    assert t["branch"] == "REQUEST_EVIDENCE" and t["case_status"] == "NEEDS_INFO"
    assert t["verdict"]["status"] == "NEEDS_EVIDENCE"
    assert {d["evidence_type"] for d in t["ui"]["requested_documents"]} == {"TEST_REPORT"}

    other = api.create_case()["case"]["id"]  # 진행 중인 건
    ids = lambda q: {c["id"] for c in api.get(f"/cases{q}").json()}  # noqa: E731
    assert ids("?status=NEEDS_INFO") == {cid}
    assert ids("?status=DIAGNOSING") == {other}
    assert ids("") == {cid, other}
    assert api.get("/cases?status=BOGUS").status_code == 422

    # 증빙 업로드(후보) → 검수 완료 적용 → EVIDENCED → FINAL_REVIEW, 건은 확정 전까지 DIAGNOSING
    t = api.submit_document(cid, {"oil_content_pct": 2}, b"oil 2%")["turn"]
    assert t["branch"] == "FINAL_REVIEW" and t["case_status"] == "DIAGNOSING"
    assert api.get(f"/cases/{cid}").json()["case"]["status"] == "DIAGNOSING"


def test_unsupported_needs_info_then_back_to_diagnosing(api):
    cid = api.create_case()["case"]["id"]
    t = api.reply(cid, "material", "OTHER")  # 샘플 KB에 테이블 없음
    assert t["branch"] == "UNSUPPORTED" and t["case_status"] == "NEEDS_INFO"
    assert t["verdict"]["status"] == "UNDETERMINABLE" and t["verdict"]["failure_reason"]
    # NEEDS_INFO 건도 정보를 고치면 문진을 이어 간다
    t = api.reply(cid, "material", "PE")
    assert t["branch"] == "ASK_FACT" and t["case_status"] == "DIAGNOSING"


# ---- 문서 --------------------------------------------------------------------------------


def test_document_upload_does_not_call_llm_or_add_facts(api):
    """자동 읽기는 하지 않는다: 원문은 저장만 하고 AI에 보내지 않으며, 판정도 바뀌지 않는다."""
    cid = api.create_case()["case"]["id"]
    before = to_film_oil_question(api, cid)
    calls = len(api.llm.calls)
    text = "시험성적서\n시료: PP 필름\n유분 함량: 2.0 %\n"
    r = api.upload(cid, text.encode("utf-8"), filename="성적서.txt")
    assert r.status_code == 201, r.text
    body = r.json()
    doc, turn = body["document"], body["turn"]
    assert_turn_contract(turn, cid)
    assert len(api.llm.calls) == calls  # 문서 원문을 AI에 보내지 않음
    assert turn["branch"] == before["branch"] == "ASK_FACT"
    assert turn["ui"]["question"]["key"] == "oil_content_pct"
    assert doc["extracted_facts"]["method"] == "none" and doc["extracted_facts"]["accepted"] == {}
    assert doc["version"] == 1 and body["values"] == []
    assert doc["sha256"] and doc["size"] == len(text.encode("utf-8"))
    trace = api.get(f"/cases/{cid}/trace").json()["sessions"][0]
    assert not [f for f in trace["facts"] if f["source_type"] == "DOCUMENT"]
    assert [t["kind"] for t in trace["turns"]][-2:] == ["DOCUMENT", "TURN"]
    with api.container().sessionmaker() as db:
        row = db.get(Document, doc["id"])
        assert row.extracted_text == text and row.case_id == cid


def test_document_pdf_text_extraction(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    r = api.upload(cid, minimal_pdf("Oil content 7 percent"), "report.pdf", "application/pdf")
    assert r.status_code == 201, r.text
    assert r.json()["turn"]["branch"] == "ASK_FACT"  # 원문만 저장, 판정 불변
    with api.container().sessionmaker() as db:
        row = db.get(Document, r.json()["document"]["id"])
        assert "Oil content 7" in row.extracted_text


def test_document_errors(api):
    cid = api.create_case()["case"]["id"]
    bad_key = api.upload(cid, b"x", facts=json.dumps({"nope": 1}))
    assert bad_key.status_code == 422
    assert bad_key.json()["detail"]["problems"][0]["key"] == "nope"
    bad_val = api.upload(cid, b"x", facts=json.dumps({"material": "WOOD"}))
    assert bad_val.status_code == 422
    assert api.upload(cid, b"x", facts="[1, 2]").status_code == 422
    assert api.upload(cid, b"MZ\x90", "tool.exe", "application/octet-stream").status_code == 415
    # 실패한 업로드는 문서를 남기지 않는다
    assert api.get(f"/cases/{cid}").json()["documents"] == []


def test_document_without_facts_reevaluates(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    r = api.upload(cid, "참고 사진 설명".encode())  # FakeLLM 기본값: 뽑은 것 없음
    assert r.status_code == 201
    assert r.json()["turn"]["branch"] == "ASK_FACT"
    assert r.json()["document"]["extracted_facts"]["accepted"] == {}


# ---- confirm / reopen --------------------------------------------------------------------


def test_confirm_rejected_when_not_confirmable(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    r = api.post(f"/cases/{cid}/confirm")
    assert r.status_code == 409
    assert r.json()["detail"]["branch"] == "ASK_FACT"
    # 유분을 진술(CLAIMED)만 하면 증빙이 필요해 여전히 확정 불가
    api.reply(cid, "oil_content_pct", {"hi": 5, "hi_inc": False})
    assert api.post(f"/cases/{cid}/confirm").status_code == 409
    assert api.get(f"/cases/{cid}").json()["case"]["status"] != "CODE_CONFIRMED"


def test_confirm_freezes_verdict_and_trace(api):
    cid = api.create_case()["case"]["id"]
    turn = finish_with_document(api, cid)
    assert turn["ui"]["can_confirm"]

    mismatch = api.post(f"/cases/{cid}/confirm", json={"expected_code": "SAMPLE-B"})
    assert mismatch.status_code == 409 and mismatch.json()["detail"]["server_code"] == "SAMPLE-A"

    r = api.post(f"/cases/{cid}/confirm", json={"expected_code": "SAMPLE-A"})
    assert r.status_code == 200, r.text
    body = r.json()
    v = body["verdict"]
    assert body["case"]["status"] == "CODE_CONFIRMED"
    assert v["version"] == 1 and v["code"] == "SAMPLE-A" and v["rule_ids"] == ["PW-001"]
    assert v["table_id"] == "plastic_waste" and v["table_version"] == "2026.11.0"
    assert v["kb_version"] and v["superseded_at"] is None
    assert v["facts_snapshot"]["oil_content_pct"]["status"] == "EVIDENCED"
    assert v["verdict"]["status"] == "CONFIRMABLE" and v["verdict"]["rationale"]
    assert v["trace_turn_id"] == turn["turn_id"]

    trace = api.get(f"/cases/{cid}/trace").json()
    turns = trace["sessions"][0]["turns"]
    assert turns[-1]["kind"] == "CONFIRM" and all(t["immutable"] for t in turns)
    assert body["frozen_trace_rows"] == len(turns)
    assert trace["verdicts"][0]["version"] == 1

    # 확정 뒤에는 문진·업로드·재확정 불가(reopen 필요)
    url = f"/cases/{cid}/diagnosis/messages"
    assert api.post(url, json={"text": "PE예요"}).status_code == 409
    assert api.upload(cid, b"x", facts=json.dumps({"oil_content_pct": 9})).status_code == 409
    assert api.post(f"/cases/{cid}/confirm").status_code == 409
    assert api.get("/cases?status=CODE_CONFIRMED").json()[0]["id"] == cid

    # 불변 Trace는 ORM으로도 고칠 수 없다
    with api.container().sessionmaker() as db:
        row = db.scalars(select(TraceRecord).order_by(TraceRecord.id)).first()
        row.payload = {"tampered": True}
        with pytest.raises(ImmutableTraceError):
            db.flush()
        db.rollback()
        row = db.scalars(select(TraceRecord).order_by(TraceRecord.id)).first()
        db.delete(row)
        with pytest.raises(ImmutableTraceError):
            db.flush()


def test_reopen_only_from_confirmed_and_keeps_versions(api):
    cid = api.create_case()["case"]["id"]
    assert api.post(f"/cases/{cid}/reopen").status_code == 409  # DIAGNOSING
    finish_with_document(api, cid)
    assert api.post(f"/cases/{cid}/confirm").status_code == 200

    r = api.post(f"/cases/{cid}/reopen", json={"reason": "성적서 재발급"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["case"]["status"] == "DIAGNOSING"
    assert body["superseded_verdict"]["version"] == 1
    assert body["superseded_verdict"]["superseded_at"] is not None
    assert_turn_contract(body["turn"], cid)
    assert body["turn"]["branch"] == "FINAL_REVIEW"  # 같은 사실로 이어 감
    assert api.post(f"/cases/{cid}/reopen").status_code == 409  # 이미 열림

    detail = api.get(f"/cases/{cid}").json()
    assert detail["current_verdict"] is None and len(detail["verdicts"]) == 1

    # 새 성적서(유분 7%) → 다른 판정으로 다시 확정 → 버전 2, 버전 1은 보존
    t = api.submit_document(cid, {"oil_content_pct": 7}, b"oil 7%")["turn"]
    assert t["verdict"]["waste_code"] == "SAMPLE-B"
    v2 = api.post(f"/cases/{cid}/confirm").json()["verdict"]
    assert v2["version"] == 2 and v2["code"] == "SAMPLE-B"
    detail = api.get(f"/cases/{cid}").json()
    assert [(v["version"], v["code"]) for v in detail["verdicts"]] == [
        (1, "SAMPLE-A"),
        (2, "SAMPLE-B"),
    ]
    assert detail["verdicts"][0]["superseded_at"] and detail["verdicts"][1]["superseded_at"] is None
    assert detail["current_verdict"]["version"] == 2

    turns = api.get(f"/cases/{cid}/trace").json()["sessions"][0]["turns"]
    kinds = [t["kind"] for t in turns]
    assert kinds.count("CONFIRM") == 2 and kinds.count("REOPEN") == 1
    assert all(t["immutable"] for t in turns)  # 두 번째 확정까지 모두 고정


def test_reopen_trace_rows_mutable_until_next_confirm(api):
    cid = api.create_case()["case"]["id"]
    finish_with_document(api, cid)
    api.post(f"/cases/{cid}/confirm")
    api.post(f"/cases/{cid}/reopen")
    turns = api.get(f"/cases/{cid}/trace").json()["sessions"][0]["turns"]
    i = next(i for i, t in enumerate(turns) if t["kind"] == "REOPEN")
    assert all(t["immutable"] for t in turns[:i])
    assert not any(t["immutable"] for t in turns[i:])


# ---- 기업 격리 ---------------------------------------------------------------------------


def test_company_isolation(api):
    cid = api.create_case()["case"]["id"]
    mine = dict(api.headers)
    other = api.company("다른기업")
    api.use(other)
    for method, url in [
        ("get", f"/cases/{cid}"),
        ("get", f"/cases/{cid}/trace"),
        ("post", f"/cases/{cid}/confirm"),
        ("post", f"/cases/{cid}/reopen"),
    ]:
        assert getattr(api, method)(url).status_code == 404, url
    r = api.post(f"/cases/{cid}/diagnosis/messages", json={"text": "PP"})
    assert r.status_code == 404
    assert api.upload(cid, b"x").status_code == 404
    assert api.get("/cases").json() == []
    assert api.get("/companies/me").json()["name"] == "다른기업"

    api.headers = {}
    assert api.get("/cases").status_code == 401
    api.headers = {"X-Company-Id": "nope"}
    assert api.get("/cases").status_code == 401
    api.headers = mine
    assert api.get(f"/cases/{cid}").status_code == 200


def test_profile_update_applies_to_new_cases(api):
    r = api.client.put(
        "/companies/me/profile",
        headers=api.headers,
        json={"profile": {"facts": {"material": "PE", "form": "FILM"}}},
    )
    assert r.status_code == 200
    turn = api.create_case()["turn"]
    assert turn["ui"]["question"]["key"] == "contamination_screen"


# ---- 저장·복원 ---------------------------------------------------------------------------


def test_fact_rows_are_append_only_in_seq_order(api):
    cid = api.create_case()["case"]["id"]
    api.reply(cid, "material", "PE")
    api.reply(cid, "material", "PP")  # 정정도 덮어쓰지 않고 append
    with api.container().sessionmaker() as db:
        rows = db.scalars(select(FactRecord).order_by(FactRecord.seq)).all()
        assert [r.seq for r in rows] == list(range(len(rows)))
        assert [r.value for r in rows if r.key == "material"] == ["PE", "PP"]
        assert all(r.recorded_at.tzinfo is not None for r in rows)


def test_real_kb_boots_and_answers(real_kb, tmp_path):
    """실제 KB로도 건 생성·한 턴이 계약을 지킨다(질문 키는 고정하지 않는다)."""
    app = build_app(real_kb, tmp_path / "real.db", fake_llm())
    a = Api(client=TestClient(app), app=app, llm=None, db_path=tmp_path / "real.db")
    a.use(a.company(profile={"facts": {}}))
    body = a.create_case(memo="폐합성수지")
    assert_turn_contract(body["turn"], body["case"]["id"])
    assert body["case"]["status"] in {"DIAGNOSING", "NEEDS_INFO"}
    q = body["turn"]["ui"]["question"]
    if q is not None and q["options"]:
        opt = q["options"][0]
        t = a.reply(body["case"]["id"], q["key"], opt.get("value"), opt.get("kind", "value"))
        assert_turn_contract(t, body["case"]["id"])
