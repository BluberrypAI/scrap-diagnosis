"""기업 정보(확인된 값, PROFILE_CONFIRMED)와 기업 데이터 삭제(CORP-009).

계약: docs/api/server-engine-contract.md, docs/handoff-contract.md
"""

from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import func, select

import app.api.deletion as deletion
from app.persistence.models import (
    Company,
    DeletionLog,
    DiagnosisSessionRecord,
    Document,
    DocumentValue,
    FactRecord,
    TraceRecord,
    VerdictRecord,
    WasteCase,
    new_id,
)
from tests.api_support import PROFILE
from tests.test_api import api  # noqa: F401
from tests.test_internal_api import INT, TOKEN, hdr, make_api

CONFIRMED = {"emission_facility": True, "material": "PP"}


@pytest.fixture
def srv(kb, tmp_path):
    return make_api(kb, tmp_path, engine_service_token=TOKEN)


def post(srv, url, company="A", **kw):
    return srv.client.post(f"{INT}{url}", headers=hdr(company), **kw)


def facts_of(srv, case_id, company="A") -> dict:
    r = srv.client.get(f"{INT}/cases/{case_id}/trace", headers=hdr(company))
    assert r.status_code == 200, r.text
    return {f["key"]: f for f in r.json()["sessions"][0]["facts"]}


def create(srv, company="A", **body) -> dict:
    r = post(srv, "/cases", company, json={"memo": None, **body})
    assert r.status_code == 201, r.text
    return r.json()


def reply(srv, cid, key, value=None, kind="value", company="A", **extra) -> dict:
    r = post(
        srv,
        f"/cases/{cid}/diagnosis/messages",
        company,
        json={"quick_reply": {"key": key, "kind": kind, "value": value}, **extra},
    )
    assert r.status_code == 200, r.text
    return r.json()


def confirmed_case(srv, company="A", version="p1") -> str:
    """확인된 기업 정보로 시작 → 형태·오염 답 → 서류 값 적용 → 확정(Trace 불변)."""
    cid = create(srv, company, confirmed_facts=CONFIRMED, company_profile_version=version)["case"][
        "id"
    ]
    reply(srv, cid, "form", "FILM", company=company)
    reply(srv, cid, "contamination_screen", kind="none_all", company=company)
    up = post(
        srv,
        f"/cases/{cid}/documents",
        company,
        files={"file": ("r.txt", b"oil 2%", "text/plain")},
        data={"facts": json.dumps({"oil_content_pct": 2})},
    )
    assert up.status_code == 201, up.text
    body = up.json()
    doc, ver = body["document"]["id"], body["document"]["version"]
    items = [
        {
            "value_id": v["id"],
            "document_version": ver,
            "reviewer": "검수자",
            "reviewed_at": "2026-11-08T10:00:00+09:00",
        }
        for v in body["values"]
    ]
    a = post(srv, f"/cases/{cid}/documents/{doc}/values/apply", company, json={"values": items})
    assert a.status_code == 200, a.text
    c = post(srv, f"/cases/{cid}/confirm", company, json={})
    assert c.status_code == 200, c.text
    return cid


# ---- 3. 기업 정보: 서버가 확인한 값 -------------------------------------------------------


def test_confirmed_facts_stored_as_profile_confirmed_and_version_recorded(srv):
    cid = confirmed_case(srv, version="profile-v7")
    facts = facts_of(srv, cid)
    for k, v in CONFIRMED.items():
        assert facts[k]["source_type"] == "PROFILE_CONFIRMED"
        assert facts[k]["status"] == "CLAIMED" and facts[k]["value"] == v
    detail = srv.client.get(f"{INT}/cases/{cid}", headers=hdr()).json()
    h = detail["handoff"]
    assert h["inputs"] == {
        "company_profile_version": "profile-v7",
        "confirmed_profile_keys": ["emission_facility", "material"],
    }
    assert h["contract"] == "diagnosis-handoff-v1" and h["facts"]["material"]["value"] == "PP"
    assert h["facts"]["material"]["source_type"] == "PROFILE_CONFIRMED"
    assert detail["current_verdict"]["company_profile_version"] == "profile-v7"
    with srv.container().sessionmaker() as db:
        rec = db.scalars(select(DiagnosisSessionRecord)).one()
        assert rec.company_profile_version == "profile-v7"


def test_message_confirmed_facts_update_version_and_do_not_override_later_answers(srv):
    cid = create(srv, confirmed_facts={"emission_facility": True}, company_profile_version="p1")[
        "case"
    ]["id"]
    # 사용자가 소재를 직접 답한 뒤, 서버가 같은 확인값을 다시 보내도 덮어쓰지 않는다
    reply(srv, cid, "material", "PE")
    reply(srv, cid, "form", "FILM", confirmed_facts={"emission_facility": True})
    reply(srv, cid, "contamination_screen", kind="none_all", confirmed_facts={"material": "PP"})
    assert facts_of(srv, cid)["material"]["value"] == "PP"  # 새로 확인된 값은 반영
    t = reply(
        srv,
        cid,
        "oil_content_pct",
        2,
        confirmed_facts={"material": "PP"},  # 같은 값 재전송 -> 건너뜀
        company_profile_version="p2",
    )
    assert t["case_status"] in ("DIAGNOSING", "NEEDS_INFO")
    with srv.container().sessionmaker() as db:
        assert db.scalars(select(DiagnosisSessionRecord)).one().company_profile_version == "p2"
        n = db.scalar(
            select(func.count())
            .select_from(FactRecord)
            .where(FactRecord.source_type == "PROFILE_CONFIRMED", FactRecord.key == "material")
        )
    assert n == 1


def test_confirmed_facts_validated(srv):
    bad = {"material": "NOT_A_MATERIAL", "no_such_key": 1, "emission_facility": ""}
    r = post(srv, "/cases", json={"confirmed_facts": bad})
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "VALIDATION_ERROR"
    assert {p["key"] for p in d["details"]["problems"]} == set(bad)
    cid = create(srv)["case"]["id"]
    r = post(
        srv,
        f"/cases/{cid}/diagnosis/messages",
        json={"text": "PP", "confirmed_facts": {"material": "x"}},
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "VALIDATION_ERROR"
    assert srv.client.get(f"{INT}/cases", headers=hdr()).json()["pagingInfo"]["totalCount"] == 1


def _provision_with_profile(srv, external_id="A") -> None:
    with srv.container().sessionmaker() as db:
        db.add(
            Company(
                id=new_id(), name="n", external_id=external_id, profile=dict(PROFILE) | {"site": 1}
            )
        )
        db.commit()


def test_internal_call_never_seeds_engine_local_profile(kb, tmp_path):
    for env in ("prod", "dev"):
        srv = make_api(kb, tmp_path / env, app_env=env, engine_service_token=TOKEN)
        _provision_with_profile(srv)
        cid = create(srv)["case"]["id"]
        assert [k for k, f in facts_of(srv, cid).items() if f["source_type"] == "PROFILE"] == []
        # 확인된 값은 prod에서도 들어간다
        cid = create(srv, confirmed_facts={"emission_facility": False})["case"]["id"]
        f = facts_of(srv, cid)["emission_facility"]
        assert f["source_type"] == "PROFILE_CONFIRMED" and f["value"] is False


def test_dev_reference_path_still_seeds_local_profile(api):  # noqa: F811
    api.use(api.company())  # PROFILE: emission_facility=True
    cid = api.create_case()["case"]["id"]
    f = {x["key"]: x for x in api.get(f"/cases/{cid}/trace").json()["sessions"][0]["facts"]}
    assert f["emission_facility"]["source_type"] == "PROFILE" and f["emission_facility"]["value"]


# ---- 6. 기업 데이터 삭제 ------------------------------------------------------------------


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def snapshot(srv) -> dict:
    with srv.container().sessionmaker() as db:
        return {
            m.__tablename__: count(db, m)
            for m in (
                WasteCase,
                DiagnosisSessionRecord,
                FactRecord,
                Document,
                DocumentValue,
                VerdictRecord,
                TraceRecord,
            )
        }


def company_snapshot(srv, external_id) -> dict:
    with srv.container().sessionmaker() as db:
        comp = db.scalars(select(Company).where(Company.external_id == external_id)).first()
        if comp is None:
            return {"company": 0}
        cases = db.scalars(select(WasteCase.id).where(WasteCase.company_id == comp.id)).all()
        sess = db.scalars(
            select(DiagnosisSessionRecord.id).where(DiagnosisSessionRecord.case_id.in_(cases))
        ).all()
        return {
            "company": 1,
            "cases": len(cases),
            "sessions": len(sess),
            "facts": db.scalar(
                select(func.count()).select_from(FactRecord).where(FactRecord.session_id.in_(sess))
            ),
            "traces": db.scalar(
                select(func.count())
                .select_from(TraceRecord)
                .where(TraceRecord.session_id.in_(sess))
            ),
            "frozen": db.scalar(
                select(func.count())
                .select_from(TraceRecord)
                .where(TraceRecord.session_id.in_(sess), TraceRecord.immutable.is_(True))
            ),
            "docs": db.scalar(
                select(func.count()).select_from(Document).where(Document.case_id.in_(cases))
            ),
            "verdicts": db.scalar(
                select(func.count())
                .select_from(VerdictRecord)
                .where(VerdictRecord.case_id.in_(cases))
            ),
        }


def delete(srv, ext="A", token=TOKEN):
    return srv.client.delete(f"{INT}/companies/{ext}/data", headers=hdr(company=None, token=token))


def status(srv, ext="A"):
    return srv.client.get(f"{INT}/companies/{ext}/data/deletion", headers=hdr(company=None))


def test_delete_removes_only_that_company_including_frozen_traces_and_is_idempotent(srv):
    a1 = confirmed_case(srv, "A")
    confirmed_case(srv, "A")
    confirmed_case(srv, "B")
    create(srv, "A")  # 진행 중 건
    before_a = company_snapshot(srv, "A")
    before_b = company_snapshot(srv, "B")
    assert before_a["cases"] == 3 and before_a["frozen"] > 0 and before_a["verdicts"] == 2
    total = snapshot(srv)

    assert delete(srv, "A", token="bad").status_code == 401
    assert company_snapshot(srv, "A") == before_a  # 인증 실패는 아무것도 지우지 않음
    r = delete(srv)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "DONE" and body["attempts"] == 1
    assert body["company_hash"] == hashlib.sha256(b"A").hexdigest()
    c = body["counts"]
    assert c["waste_cases"] == 3 and c["verdicts"] == 2 and c["companies"] == 1
    assert c["trace_turns"] == before_a["traces"] and c["fact_records"] == before_a["facts"]
    assert c["documents"] == 2 and c["document_values"] == 2 and c["diagnosis_sessions"] == 3

    assert company_snapshot(srv, "A") == {"company": 0}
    assert company_snapshot(srv, "B") == before_b
    after = snapshot(srv)
    assert after["waste_cases"] == total["waste_cases"] - 3
    assert after["trace_turns"] == total["trace_turns"] - before_a["traces"]

    again = delete(srv)  # 멱등: 같은 결과
    assert again.status_code == 200 and again.json() == body
    assert delete(srv, "never-seen").json()["counts"]["companies"] == 0
    assert company_snapshot(srv, "B") == before_b
    with srv.container().sessionmaker() as db:
        assert count(db, DeletionLog) == 2  # A 한 번, never-seen 한 번
    s = status(srv).json()
    assert s["status"] == "DONE" and s["counts"] == c
    assert status(srv, "zzz").status_code == 404
    assert status(srv, "zzz").json()["detail"]["code"] == "DELETION_NOT_FOUND"
    # 삭제된 기업의 건은 이제 없는 건(같은 ID로 다시 부르면 빈 기업으로 새로 시작)
    assert srv.client.get(f"{INT}/cases/{a1}", headers=hdr("A")).status_code == 404
    assert srv.client.get(f"{INT}/cases", headers=hdr("B")).json()["pagingInfo"]["totalCount"] == 1


def test_delete_requires_service_auth_and_log_has_no_plain_id(srv):
    assert delete(srv, "A", token=None).status_code == 401
    assert status(srv).status_code == 404  # 인증 통과, 이력 없음
    srv.client.get(f"{INT}/cases", headers=hdr("A"))  # 기업 생성
    assert delete(srv).status_code == 200
    with srv.container().sessionmaker() as db:
        log = db.scalars(select(DeletionLog)).one()
        assert "A" != log.company_hash and len(log.company_hash) == 64
    # 루트(참조 화면) 경로에는 삭제 API가 없다
    assert srv.client.delete("/companies/A/data").status_code in (404, 405)


def test_immutable_trace_guard_still_applies_elsewhere(srv):
    from app.persistence.db import ImmutableTraceError

    confirmed_case(srv, "A")
    with srv.container().sessionmaker() as db:
        row = db.scalars(select(TraceRecord).where(TraceRecord.immutable.is_(True))).first()
        db.delete(row)
        with pytest.raises(ImmutableTraceError):
            db.flush()


def test_deletion_failure_rolls_back_logs_failed_and_retry_continues(srv, monkeypatch):
    confirmed_case(srv, "A")
    confirmed_case(srv, "B")
    before_a = company_snapshot(srv, "A")
    before_b = company_snapshot(srv, "B")
    real = deletion.purge_company

    def boom(db, company):  # noqa: ANN001, ANN202
        real(db, company)  # 일부(전부) 지운 뒤 실패 -> 되돌아와야 함
        raise RuntimeError("디스크 오류 시뮬레이션")

    monkeypatch.setattr(deletion, "purge_company", boom)
    r = delete(srv)
    assert r.status_code == 500
    d = r.json()["detail"]
    assert d["code"] == "DELETION_FAILED" and d["details"]["attempts"] == 1
    assert company_snapshot(srv, "A") == before_a  # 롤백
    assert company_snapshot(srv, "B") == before_b
    s = status(srv).json()
    assert s["status"] == "FAILED" and s["attempts"] == 1 and "시뮬레이션" in s["error"]

    assert delete(srv).status_code == 500  # 다시 실패 -> 같은 행의 attempts 증가
    s = status(srv).json()
    assert s["status"] == "FAILED" and s["attempts"] == 2

    monkeypatch.setattr(deletion, "purge_company", real)
    r = delete(srv)  # 재시도 성공
    assert r.status_code == 200 and r.json()["status"] == "DONE" and r.json()["attempts"] == 3
    assert r.json()["counts"]["waste_cases"] == 1
    assert company_snapshot(srv, "A") == {"company": 0}
    assert company_snapshot(srv, "B") == before_b
    with srv.container().sessionmaker() as db:
        rows = db.scalars(select(DeletionLog)).all()
        assert len(rows) == 1 and rows[0].status == "DONE" and rows[0].error is None
    assert status(srv).json()["status"] == "DONE"
