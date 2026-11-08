"""서류 값 후보 → 검수 → 적용·효력 해제, 규칙 버전 불일치(KB_CHANGED)·rebase.

docs/api/server-engine-contract.md 3·5절. 엔진은 원문 대조를 하지 않고 형식만 거른다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.domain.facts import (
    Fact,
    FactStatus,
    FactStore,
    active_facts,
    document_id_of,
    document_source_ref,
    revoke_fact,
    source_matches,
)
from app.persistence.models import DiagnosisSessionRecord, DocumentValue, FactRecord
from tests.api_support import REVIEW, Api, build_app, fake_llm, to_film_oil_question
from tests.test_api import assert_turn_contract
from tests.test_internal_api import INT, TOKEN, hdr, make_api, new_case

T0 = datetime(2026, 11, 8, tzinfo=UTC)


@pytest.fixture
def api(kb, tmp_path) -> Api:
    llm = fake_llm()
    app = build_app(kb, tmp_path / "dv.db", llm)
    a = Api(client=TestClient(app), app=app, llm=llm, db_path=tmp_path / "dv.db")
    return a.use(a.company())


def _oil_cond(turn: dict) -> dict:
    return next(c for c in turn["verdict"]["conditions"] if c["fact"] == "oil_content_pct")


def _upload(api: Api, cid: str, facts: dict, content: bytes = b"oil 2%") -> dict:
    r = api.upload(cid, content, facts=json.dumps(facts))
    assert r.status_code == 201, r.text
    return r.json()


def _doc_facts(api: Api, cid: str) -> list[dict]:
    facts = api.get(f"/cases/{cid}/trace").json()["sessions"][0]["facts"]
    return [f for f in facts if f["source_type"] == "DOCUMENT"]


# ---- 사실 효력 규칙(도메인) --------------------------------------------------------------


def _f(key, value, status, t, ref="", source_type="DOCUMENT") -> Fact:
    return Fact(
        key=key,
        value=value,
        status=status,
        source_type=source_type,
        source_ref=ref,
        recorded_at=T0 + timedelta(seconds=t),
    )


def test_source_ref_helpers():
    assert document_source_ref("d1", 2) == "d1@v2" and document_source_ref("d1") == "d1"
    assert document_id_of("d1@v2") == "d1" and document_id_of("d1") == "d1"
    assert source_matches("d1@v2", "d1") and source_matches("d1", "d1")  # 이전 표기 포함
    assert source_matches("d1@v2", "d1@v2") and not source_matches("d1@v1", "d1@v2")
    assert not source_matches("d10@v1", "d1")


def test_revoke_marker_hides_evidence_and_keeps_history():
    claim = _f("oil_content_pct", 6, FactStatus.CLAIMED, 0, "m1", "UTTERANCE")
    ev = _f("oil_content_pct", 2, FactStatus.EVIDENCED, 1, "d1@v1")
    mark = revoke_fact("oil_content_pct", "d1").model_copy(
        update={"recorded_at": T0 + timedelta(2)}
    )
    hist = [claim, ev, mark]
    assert active_facts(hist) == [claim]  # 표시 행도 고르지 않는다
    assert FactStore(hist).effective()["oil_content_pct"] == claim
    assert FactStore(list(reversed(hist))).effective() == FactStore(hist).effective()  # 순서 불변
    # 해제 뒤 다시 적용한 값은 유효
    again = _f("oil_content_pct", 2, FactStatus.EVIDENCED, 3 * 86400, "d1@v1")
    assert FactStore([*hist, again]).effective()["oil_content_pct"] == again
    # 다른 버전·다른 서류의 증빙은 그대로
    other = _f("oil_content_pct", 3, FactStatus.EVIDENCED, 1, "d2@v1")
    assert FactStore([ev, other, mark]).effective()["oil_content_pct"] == other
    only = revoke_fact("material", "d1")
    assert FactStore([only]).effective() == {}  # 표시 행만 남은 키는 사실 없음
    v2_mark = revoke_fact("oil_content_pct", "d1@v2").model_copy(
        update={"recorded_at": T0 + timedelta(2)}
    )
    assert FactStore([ev, v2_mark]).effective()["oil_content_pct"] == ev  # v1은 해당 없음


# ---- 후보: 업로드·직접 입력만으로는 증빙이 아님 -----------------------------------------


def test_upload_facts_are_candidates_only(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    api.reply(cid, "oil_content_pct", kind="unknown")  # 성적서 요청
    body = _upload(api, cid, {"oil_content_pct": "2.0"})
    turn, doc, values = body["turn"], body["document"], body["values"]
    assert_turn_contract(turn, cid)
    assert turn["branch"] == "REQUEST_EVIDENCE" and not turn["ui"]["can_confirm"]
    assert _oil_cond(turn)["satisfied"] is not True
    assert [(v["fact_key"], v["value"], v["status"]) for v in values] == [
        ("oil_content_pct", 2.0, "UNVERIFIED")
    ]
    assert values[0]["document_version"] == 1 and doc["version"] == 1
    assert doc["extracted_facts"]["candidates"] == {"oil_content_pct": 2.0}
    assert _doc_facts(api, cid) == []  # 사실 이력에 없다
    detail = api.get(f"/cases/{cid}").json()
    assert detail["documents"][0]["values"][0]["status"] == "UNVERIFIED"
    assert api.post(f"/cases/{cid}/confirm").status_code == 409


@pytest.mark.parametrize(
    "facts,bad_key",
    [
        ({"oil_content_pct": "-"}, "oil_content_pct"),
        ({"oil_content_pct": "약 2"}, "oil_content_pct"),
        ({"oil_content_pct": "5mg"}, "oil_content_pct"),
        ({"oil_content_pct": "nan"}, "oil_content_pct"),
        ({"oil_content_pct": ""}, "oil_content_pct"),
        ({"oil_content_pct": None}, "oil_content_pct"),
        ({"material": "WOOD"}, "material"),
        ({"nope": 1}, "nope"),
    ],
)
def test_malformed_candidates_rejected(api, facts, bad_key):
    cid = api.create_case()["case"]["id"]
    r = api.upload(cid, b"x", facts=json.dumps({"form": "FILM", **facts}))
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["code"] == "VALIDATION_ERROR"
    assert [p["key"] for p in d["details"]["problems"]] == [bad_key]  # 항목별
    assert api.get(f"/cases/{cid}").json()["documents"] == []  # 아무것도 남기지 않음


# ---- 적용 --------------------------------------------------------------------------------


def test_apply_makes_evidenced_and_changes_decision(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    body = _upload(api, cid, {"oil_content_pct": 2})
    doc_id, vid = body["document"]["id"], body["values"][0]["id"]
    r = api.apply(cid, doc_id, [{"value_id": vid, "document_version": 1}])
    assert r.status_code == 200, r.text
    turn = r.json()
    assert_turn_contract(turn, cid)
    assert turn["branch"] == "FINAL_REVIEW" and turn["verdict"]["waste_code"] == "SAMPLE-A"
    assert _oil_cond(turn)["satisfied"] is True
    (row,) = _doc_facts(api, cid)
    assert row["status"] == "EVIDENCED" and row["source_ref"] == f"{doc_id}@v1"
    board = {f["key"]: f for f in turn["ui"]["board"]["facts"]}
    assert board["oil_content_pct"]["document_id"] == doc_id  # 화면 링크는 문서 id
    (v,) = api.get(f"/cases/{cid}").json()["documents"][0]["values"]
    assert v["status"] == "APPLIED" and v["reviewer"] == REVIEW["reviewer"] and v["reviewed_at"]
    turns = api.get(f"/cases/{cid}/trace").json()["sessions"][0]["turns"]
    assert [t["kind"] for t in turns][-2:] == ["APPLY", "TURN"]
    assert turns[-2]["payload"]["appended_facts"][0]["source_ref"] == f"{doc_id}@v1"
    h = api.post(f"/cases/{cid}/confirm").json()["handoff"]
    assert h["evidence"] == [{"fact": "oil_content_pct", "document_id": doc_id}]


def test_apply_by_fact_key_corrected_value_and_reject(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    body = _upload(api, cid, {"oil_content_pct": 2, "form": "FILM"})
    doc_id = body["document"]["id"]
    vals = {v["fact_key"]: v["id"] for v in body["values"]}
    r = api.apply(
        cid,
        doc_id,
        [
            {"value_id": vals["oil_content_pct"], "value": 7, "document_version": 1},  # 검수 수정
            {"value_id": vals["form"], "reject": True, "document_version": 1},
        ],
    )
    assert r.status_code == 200, r.text
    assert r.json()["verdict"]["waste_code"] == "SAMPLE-B"
    rows = {v["fact_key"]: v for v in api.get(f"/cases/{cid}").json()["documents"][0]["values"]}
    assert rows["oil_content_pct"]["status"] == "APPLIED" and rows["oil_content_pct"]["value"] == 7
    assert "검수에서" in rows["oil_content_pct"]["note"]
    assert rows["form"]["status"] == "REJECTED"
    assert [f["key"] for f in _doc_facts(api, cid)] == ["oil_content_pct"]
    # 후보 없이 키로 바로 적용(새 값 행)
    r = api.apply(cid, doc_id, [{"fact_key": "oil_content_pct", "value": 2, "document_version": 1}])
    assert r.status_code == 200 and r.json()["verdict"]["waste_code"] == "SAMPLE-A"
    assert len(api.get(f"/cases/{cid}").json()["documents"][0]["values"]) == 3


def test_apply_rejects_malformed_and_bad_refs(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    body = _upload(api, cid, {"oil_content_pct": 2})
    doc_id = body["document"]["id"]
    url = f"/cases/{cid}/documents/{doc_id}/values/apply"
    for bad in ("-", "두 퍼센트", "", None):
        r = api.apply(
            cid, doc_id, [{"fact_key": "oil_content_pct", "value": bad, "document_version": 1}]
        )
        assert r.status_code == 422, bad
        assert r.json()["detail"]["details"]["problems"][0]["key"] == "oil_content_pct"
    r = api.apply(cid, doc_id, [{"fact_key": "material", "value": "WOOD", "document_version": 1}])
    assert r.status_code == 422
    r = api.apply(cid, doc_id, [{"fact_key": "nope", "value": 1, "document_version": 1}])
    assert r.status_code == 422
    r = api.apply(cid, doc_id, [{"value_id": "x" * 32, "document_version": 1}])
    assert r.status_code == 422
    # 단위가 카탈로그 기준과 다르면 거절(환산하지 않음)
    r = api.apply(
        cid,
        doc_id,
        [{"fact_key": "oil_content_pct", "value": 2, "unit": "ppm", "document_version": 1}],
    )
    assert r.status_code == 422
    # 형식 오류(본문): value_id·fact_key 없음, reviewer 없음
    assert api.post(url, json={"values": [{**REVIEW, "document_version": 1}]}).status_code == 422
    assert (
        api.post(
            url,
            json={"values": [{"fact_key": "oil_content_pct", "value": 2, "document_version": 1}]},
        ).status_code
        == 422
    )
    assert (
        api.post(
            f"/cases/{cid}/documents/{'z' * 32}/values/apply",
            json={
                "values": [
                    {**REVIEW, "fact_key": "oil_content_pct", "value": 2, "document_version": 1}
                ]
            },
        ).json()["detail"]["code"]
        == "DOCUMENT_NOT_FOUND"
    )
    assert _doc_facts(api, cid) == []  # 실패한 적용은 아무것도 남기지 않음
    assert {v["status"] for v in api.get(f"/cases/{cid}").json()["documents"][0]["values"]} == {
        "UNVERIFIED"
    }


# ---- 효력 해제·교체 ----------------------------------------------------------------------


def test_revoke_removes_effect_keeps_history_and_reapply_works(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    sub = api.submit_document(cid, {"oil_content_pct": 2})
    doc_id, vid = sub["document"]["id"], sub["values"][0]["id"]
    assert sub["turn"]["branch"] == "FINAL_REVIEW"

    r = api.post(f"/cases/{cid}/documents/{doc_id}/revoke", json={"reason": "검수 취소"})
    assert r.status_code == 200, r.text
    turn = r.json()
    assert turn["branch"] != "FINAL_REVIEW" and not turn["ui"]["can_confirm"]
    assert not [f for f in turn["ui"]["board"]["facts"] if f["key"] == "oil_content_pct"]
    rows = _doc_facts(api, cid)
    assert [(f["status"], f["revoked"]) for f in rows] == [("EVIDENCED", False), ("UNKNOWN", True)]
    assert rows[1]["source_ref"] == doc_id and "검수 취소" in rows[1]["note"]
    (v,) = api.get(f"/cases/{cid}").json()["documents"][0]["values"]
    assert v["status"] == "REVOKED"
    turns = api.get(f"/cases/{cid}/trace").json()["sessions"][0]["turns"]
    assert turns[-2]["kind"] == "REVOKE"
    assert turns[-2]["payload"]["revoked_keys"] == ["oil_content_pct"]

    # 같은 값 행을 다시 적용하면 유효
    r = api.apply(cid, doc_id, [{"value_id": vid, "document_version": 1}])
    assert r.status_code == 200 and r.json()["branch"] == "FINAL_REVIEW"
    assert len(_doc_facts(api, cid)) == 3  # 이력 보존(EVIDENCED, 표시 행, EVIDENCED)

    # 없는 버전 해제는 409, 다른 기업·없는 서류는 404
    r = api.post(f"/cases/{cid}/documents/{doc_id}/revoke", json={"document_version": 5})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DOCUMENT_VERSION_MISMATCH"
    assert api.post(f"/cases/{cid}/documents/{'z' * 32}/revoke").status_code == 404


def test_new_file_version_auto_revokes_and_stale_version_409(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    sub = api.submit_document(cid, {"oil_content_pct": 2})
    doc_id, old_vid = sub["document"]["id"], sub["values"][0]["id"]
    pending = _upload(api, cid, {"form": "FILM"})  # 다른 서류는 영향 없음
    r = api.post(
        f"/cases/{cid}/documents/{doc_id}/versions",
        files={"file": ("report-v2.txt", b"oil 7%", "text/plain")},
        data={"facts": json.dumps({"oil_content_pct": 7})},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["document"]["version"] == 2 and body["document"]["filename"] == "report-v2.txt"
    assert (
        body["values"][0]["document_version"] == 2 and body["values"][0]["status"] == "UNVERIFIED"
    )
    turn = body["turn"]
    assert turn["branch"] != "FINAL_REVIEW"  # v1 증빙 해제, v2는 아직 후보
    by_id = {v["id"]: v for v in body["document"]["values"]}
    assert by_id[old_vid]["status"] == "REVOKED" and by_id[old_vid]["document_version"] == 1
    other = api.get(f"/cases/{cid}").json()["documents"]
    assert [
        v["status"] for d in other if d["id"] == pending["document"]["id"] for v in d["values"]
    ] == ["UNVERIFIED"]
    trace = api.get(f"/cases/{cid}/trace").json()["sessions"][0]["turns"]
    doc_tr = [t for t in trace if t["kind"] == "DOCUMENT"][-1]["payload"]
    assert doc_tr["replaced_version"] == 1 and doc_tr["revoked_keys"] == ["oil_content_pct"]

    # 이전 버전 기준 검수 결과는 409
    for item in (
        {"value_id": old_vid, "document_version": 2},
        {"fact_key": "oil_content_pct", "value": 2, "document_version": 1},
    ):
        r = api.apply(cid, doc_id, [item])
        assert r.status_code == 409, item
        d = r.json()["detail"]
        assert d["code"] == "DOCUMENT_VERSION_MISMATCH"
        assert d["details"]["current_version"] == 2 and d["details"]["sent_versions"] == [1]

    r = api.apply(cid, doc_id, [{"value_id": body["values"][0]["id"], "document_version": 2}])
    assert r.status_code == 200 and r.json()["verdict"]["waste_code"] == "SAMPLE-B"
    refs = [f["source_ref"] for f in _doc_facts(api, cid) if f["status"] == "EVIDENCED"]
    assert refs == [f"{doc_id}@v1", f"{doc_id}@v2"]


def test_document_ops_409_on_confirmed_case(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    sub = api.submit_document(cid, {"oil_content_pct": 2})
    doc_id = sub["document"]["id"]
    assert api.post(f"/cases/{cid}/confirm").status_code == 200
    item = {"fact_key": "oil_content_pct", "value": 7, "document_version": 1}
    for r in (
        api.apply(cid, doc_id, [item]),
        api.post(f"/cases/{cid}/documents/{doc_id}/revoke"),
        api.post(
            f"/cases/{cid}/documents/{doc_id}/versions",
            files={"file": ("v2.txt", b"x", "text/plain")},
        ),
    ):
        assert r.status_code == 409 and r.json()["detail"]["code"] == "CASE_NOT_DIAGNOSABLE"


def test_internal_apply_and_revoke(kb, tmp_path):
    srv = make_api(kb, tmp_path, engine_service_token=TOKEN)
    h = hdr()
    cid = new_case(srv)
    for k, v, kind in (("material", "PP", "value"), ("form", "FILM", "value")):
        srv.client.post(
            f"{INT}/cases/{cid}/diagnosis/messages",
            headers=h,
            json={"quick_reply": {"key": k, "value": v, "kind": kind}},
        )
    srv.client.post(
        f"{INT}/cases/{cid}/diagnosis/messages",
        headers=h,
        json={"quick_reply": {"key": "contamination_screen", "kind": "none_all"}},
    )
    r = srv.client.post(
        f"{INT}/cases/{cid}/documents",
        headers=h,
        files={"file": ("r.txt", b"oil", "text/plain")},
        data={"facts": json.dumps({"oil_content_pct": 2})},
    )
    doc = r.json()["document"]
    r = srv.client.post(
        f"{INT}/cases/{cid}/documents/{doc['id']}/values/apply",
        headers=h,
        json={"values": [{**REVIEW, "value_id": doc["values"][0]["id"], "document_version": 1}]},
    )
    assert r.status_code == 200 and r.json()["branch"] == "FINAL_REVIEW"
    r = srv.client.post(f"{INT}/cases/{cid}/documents/{doc['id']}/revoke", headers=h, json={})
    assert r.status_code == 200 and r.json()["branch"] != "FINAL_REVIEW"
    # 다른 기업은 그 건을 볼 수 없다
    r = srv.client.post(f"{INT}/cases/{cid}/rebase", headers=hdr("B"))
    assert r.status_code == 404


# ---- 규칙 버전 불일치 --------------------------------------------------------------------


def _age_kb(api: Api, cid: str, version: str = "old-kb") -> None:
    with api.container().sessionmaker() as db:
        rec = db.scalars(
            select(DiagnosisSessionRecord).where(DiagnosisSessionRecord.case_id == cid)
        ).one()
        rec.kb_version = version
        db.commit()


def test_kb_changed_blocks_writes_and_rebase_continues(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    body = _upload(api, cid, {"oil_content_pct": 2})
    doc_id = body["document"]["id"]
    current = api.container().kb_info.version
    _age_kb(api, cid)

    # 읽기는 된다(kb_changed 표시)
    detail = api.get(f"/cases/{cid}").json()
    assert detail["case"]["kb_changed"] is True and detail["latest_turn"]
    assert next(c for c in api.get("/cases").json() if c["id"] == cid)["kb_changed"] is True
    assert api.get(f"/cases/{cid}/trace").status_code == 200

    # 쓰기는 409 KB_CHANGED
    for r in (
        api.post(f"/cases/{cid}/diagnosis/messages", json={"text": "PP"}),
        api.upload(cid, b"x"),
        api.apply(cid, doc_id, [{"value_id": body["values"][0]["id"], "document_version": 1}]),
        api.post(f"/cases/{cid}/documents/{doc_id}/revoke"),
        api.post(f"/cases/{cid}/confirm"),
    ):
        assert r.status_code == 409, r.text
        d = r.json()["detail"]
        assert d["code"] == "KB_CHANGED"
        assert d["details"] == {"session_kb_version": "old-kb", "current_kb_version": current}

    r = api.post(f"/cases/{cid}/rebase")
    assert r.status_code == 200, r.text
    assert_turn_contract(r.json(), cid)
    assert api.get(f"/cases/{cid}").json()["case"]["kb_changed"] is False
    trace = api.get(f"/cases/{cid}/trace").json()["sessions"][0]
    assert trace["kb_version"] == current
    rb = [t for t in trace["turns"] if t["kind"] == "REBASE"][-1]["payload"]
    assert rb["from_kb_version"] == "old-kb" and rb["to_kb_version"] == current and rb["changed"]
    # 이어 간다
    r = api.apply(cid, doc_id, [{"value_id": body["values"][0]["id"], "document_version": 1}])
    assert r.status_code == 200 and r.json()["branch"] == "FINAL_REVIEW"


def test_kb_changed_on_confirmed_case_keeps_verdict(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    api.submit_document(cid, {"oil_content_pct": 2})
    v1 = api.post(f"/cases/{cid}/confirm").json()["verdict"]
    _age_kb(api, cid)

    detail = api.get(f"/cases/{cid}").json()
    assert detail["case"]["kb_changed"] is True
    assert (
        detail["current_verdict"] == v1
        and detail["current_verdict"]["kb_version"] == v1["kb_version"]
    )
    r = api.post(f"/cases/{cid}/rebase")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CASE_NOT_DIAGNOSABLE"
    assert api.post(f"/cases/{cid}/confirm").json()["detail"]["code"] == "ALREADY_CONFIRMED"
    assert api.get(f"/cases/{cid}").json()["verdicts"] == [v1]  # 확정본 그대로

    # reopen은 지금 규칙으로 맞춰 이어 간다(이전 판정은 보존)
    r = api.post(f"/cases/{cid}/reopen", json={"reason": "규칙 갱신"})
    assert r.status_code == 200, r.text
    after = api.get(f"/cases/{cid}").json()
    assert after["case"]["kb_changed"] is False
    assert after["verdicts"][0]["code"] == v1["code"] and after["verdicts"][0]["superseded_at"]
    kinds = [t["kind"] for t in api.get(f"/cases/{cid}/trace").json()["sessions"][0]["turns"]]
    assert kinds[-3:] == ["REOPEN", "REBASE", "TURN"]


def test_fact_record_revoked_column_round_trips(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    sub = api.submit_document(cid, {"oil_content_pct": 2})
    api.post(f"/cases/{cid}/documents/{sub['document']['id']}/revoke")
    with api.container().sessionmaker() as db:
        rows = db.scalars(select(FactRecord).where(FactRecord.revoked.is_(True))).all()
        assert len(rows) == 1 and rows[0].key == "oil_content_pct"
        assert db.scalars(select(DocumentValue)).one().status == "REVOKED"
