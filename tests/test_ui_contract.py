"""ui-v1 API 보강(docs/ui/ui-contract.md): 기업 정보·카탈로그·오류·대화 기록·건 요약."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api_support import Api, build_app, fake_llm, to_film_oil_question

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def api(kb, tmp_path) -> Api:
    llm = fake_llm()
    app = build_app(kb, tmp_path / "ui.db", llm)
    a = Api(client=TestClient(app), app=app, llm=llm, db_path=tmp_path / "ui.db")
    return a.use(a.company())


# ---- 기업 정보 ---------------------------------------------------------------------------


def test_profile_options_without_auth(api):
    r = api.client.get("/companies/profile-options")
    assert r.status_code == 200
    opts = r.json()["facilities"]
    assert [o["value"] for o in opts] == [
        "air_emission",
        "water_emission",
        "noise_vibration",
        "waste_treatment",
        "none",
    ]
    assert all(o["label"] for o in opts)


@pytest.mark.parametrize(
    ("facilities", "expected"),
    [
        (["air_emission"], {"emission_facility": True}),
        (
            ["noise_vibration", "waste_treatment"],
            {"emission_facility": True, "waste_facility": True},
        ),
        (["waste_treatment"], {"waste_facility": True}),
        (["none"], {"emission_facility": False, "waste_facility": False}),
        ([], {}),
    ],
)
def test_profile_facts_computed(api, facilities, expected):
    body = {"basic": {"industry": "제조업"}, "facilities": facilities, "products": ["부품"]}
    c = api.client.post("/companies", json={"name": "A", "profile": body}).json()
    assert c["profile"]["facts"] == expected
    assert c["profile"]["facilities"] == facilities and c["profile"]["products"] == ["부품"]
    me = api.client.get("/companies/me", headers={"X-Company-Id": c["id"]}).json()
    assert me["profile"]["facts"] == expected


def test_profile_explicit_facts_win_and_update(api):
    api.use(api.company(profile={}))
    r = api.client.put(
        "/companies/me/profile",
        headers=api.headers,
        json={"profile": {"facilities": ["air_emission"], "facts": {"emission_facility": False}}},
    )
    assert r.status_code == 200
    assert r.json()["profile"]["facts"] == {"emission_facility": False}


def test_profile_validation_wrapped_422(api):
    r = api.client.post(
        "/companies", json={"name": "A", "profile": {"facilities": ["none", "air_emission"]}}
    )
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "VALIDATION_ERROR"
    assert d["details"]["errors"][0]["loc"][:2] == ["body", "profile"]
    r = api.client.post("/companies", json={"name": "A", "profile": {"facilities": ["x"]}})
    assert r.status_code == 422


def test_computed_facts_seed_diagnosis(api):
    api.use(api.company(profile={"facilities": ["air_emission"]}))
    board = api.create_case()["turn"]["ui"]["board"]
    facts = {f["key"]: f for f in board["facts"]}
    assert facts["emission_facility"]["value"] is True
    assert facts["emission_facility"]["source_type"] == "PROFILE"


# ---- 카탈로그 ----------------------------------------------------------------------------


def test_catalog_facts(api, kb):
    r = api.client.get("/catalog/facts")
    assert r.status_code == 200
    facts = r.json()
    assert [f["key"] for f in facts] == [k for k, fd in kb.catalog.items() if not fd.internal]
    for f in facts:
        assert f["label"] and f["type"] in {"enum", "bool", "number"}
    enums = [f for f in facts if f["type"] == "enum"]
    assert enums and all(v["label"] for f in enums for v in f["values"])
    for t, check in (("bool", [True, False]), ("number", None)):
        f = next((f for f in facts if f["type"] == t), None)
        if f is not None:
            vals = [v["value"] for v in f["values"]]
            assert vals == (check or [])
    children = [f for f in facts if f["parent"]]
    for f in children:
        assert any(v["parent_value"] for v in f["values"])


# ---- 오류 형식 ---------------------------------------------------------------------------


def test_error_format_is_detail_message(api):
    rs = [
        api.client.get("/cases"),  # 401 헤더 없음
        api.client.get("/cases", headers={"X-Company-Id": "nope"}),  # 401 모르는 기업
        api.get("/cases/nope"),  # 404
        api.post("/cases/nope/confirm"),  # 404
    ]
    assert [r.status_code for r in rs] == [401, 401, 404, 404]
    assert [r.json()["detail"]["code"] for r in rs] == [
        "COMPANY_REQUIRED",
        "COMPANY_REQUIRED",
        "CASE_NOT_FOUND",
        "CASE_NOT_FOUND",
    ]
    cid = api.create_case()["case"]["id"]
    rs += [
        api.post(f"/cases/{cid}/confirm"),  # 409
        api.upload(cid, b"xx", filename="a.exe", content_type="application/x-x"),  # 415
    ]
    assert [r.status_code for r in rs[-2:]] == [409, 415]
    for r in rs:
        d = r.json()["detail"]
        assert isinstance(d, dict) and isinstance(d["message"], str) and d["message"]
        assert isinstance(d["code"], str) and isinstance(d["details"], dict)


def test_upload_too_large_and_bad_facts_use_detail_message(api):
    cid = api.create_case()["case"]["id"]
    big = api.upload(cid, b"x" * (api.container().settings.max_upload_bytes + 1))
    assert big.status_code == 413 and isinstance(big.json()["detail"]["message"], str)
    bad = api.upload(cid, b"x", facts="[1]")
    assert bad.status_code == 422 and isinstance(bad.json()["detail"]["message"], str)


# ---- 대화 기록 ---------------------------------------------------------------------------


def test_conversation_persists_with_quick_reply_labels(api):
    cid = api.create_case(memo="PP 필름 자투리")["case"]["id"]
    to_film_oil_question(api, cid)
    api.submit_document(cid, {"oil_content_pct": 2}, b"oil 2%", "rep.txt")
    conv = api.get(f"/cases/{cid}").json()["conversation"]
    assert conv[0]["role"] == "user" and conv[0]["memo"] and conv[0]["text"] == "PP 필름 자투리"
    users = [m for m in conv if m["role"] == "user"]
    replies = [m for m in users if m["quick_reply"]]
    assert [m["quick_reply"]["key"] for m in replies] == [
        "material",
        "form",
        "contamination_screen",
    ]
    assert all(m["text"] and m["turn_id"] for m in replies)
    assert replies[2]["quick_reply"]["kind"] == "none_all"
    assert replies[2]["text"] != "none_all"  # 고른 선택지 라벨
    docs = [m for m in users if m["document_id"]]
    assert len(docs) == 1 and "rep.txt" in docs[0]["text"]
    asst = [m for m in conv if m["role"] == "assistant"]
    assert asst and all(m["branch"] and m["text"] for m in asst)
    assert all(m["at"] for m in conv)
    assert api.get(f"/cases/{cid}").json()["conversation"] == conv  # 저장된 기록


def test_conversation_survives_reopen(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    api.submit_document(cid, {"oil_content_pct": 2}, b"oil 2%")
    before = api.get(f"/cases/{cid}").json()["conversation"]
    assert api.post(f"/cases/{cid}/confirm").status_code == 200
    assert api.post(f"/cases/{cid}/reopen").status_code == 200
    after = api.get(f"/cases/{cid}").json()["conversation"]
    assert after[: len(before)] == before


# ---- 건 요약 -----------------------------------------------------------------------------


def test_case_summary_in_list_and_detail(api):
    fresh = api.create_case()["case"]
    assert fresh["summary"]["title"] == "새 폐기물"
    assert fresh["summary"]["status_label"] == "문진 중"
    assert fresh["summary"]["code"] is None and fresh["summary"]["result_label"] is None

    memo = api.create_case(memo="첫 줄 메모\n둘째 줄")["case"]
    assert memo["summary"]["title"] == "첫 줄 메모"

    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    s = api.get(f"/cases/{cid}").json()["case"]["summary"]
    assert s["title"] != "새 폐기물" and s["next_action"]
    api.submit_document(cid, {"oil_content_pct": 2}, b"oil 2%")
    s = api.get(f"/cases/{cid}").json()["case"]["summary"]
    assert s["code"] == "SAMPLE-A" and s["result_label"].startswith("SAMPLE-A")  # 확정 검토 중
    assert api.post(f"/cases/{cid}/confirm").status_code == 200
    listed = {c["id"]: c for c in api.get("/cases").json()}
    s = listed[cid]["summary"]
    assert s["status_label"] == "확정" and s["code"] == "SAMPLE-A" and s["next_action"]
    assert s == api.get(f"/cases/{cid}").json()["case"]["summary"]


# ---- 철회 --------------------------------------------------------------------------------


def test_retract_via_api_and_409_when_confirmed(api):
    cid = api.create_case()["case"]["id"]
    to_film_oil_question(api, cid)
    turn = api.reply(cid, "material", kind="retract")
    assert not [f for f in turn["ui"]["board"]["facts"] if f["key"] == "material"]
    turn = api.reply(cid, "material", "PP")  # 다시 진술하면 유효
    assert any(f["key"] == "material" for f in turn["ui"]["board"]["facts"])

    api.submit_document(cid, {"oil_content_pct": 2}, b"oil 2%")
    assert api.post(f"/cases/{cid}/confirm").status_code == 200
    r = api.post(
        f"/cases/{cid}/diagnosis/messages",
        json={"quick_reply": {"key": "material", "kind": "retract"}},
    )
    assert r.status_code == 409 and r.json()["detail"]["case_status"] == "CODE_CONFIRMED"


# ---- OpenAPI -----------------------------------------------------------------------------


def test_committed_openapi_matches_fresh_export():
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_openapi.py"), "--check"],
        capture_output=True,
        cwd=ROOT,
    )
    assert out.returncode == 0, (
        "docs/api/openapi.json이 오래됐습니다: scripts/export_openapi.py 실행"
    )


def test_openapi_has_new_endpoints_and_error_schema():
    spec = json.loads((ROOT / "docs" / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert {"/catalog/facts", "/companies/profile-options"} <= set(spec["paths"])
    schemas = spec["components"]["schemas"]
    assert "ErrorResponse" in schemas
    assert "conversation" in schemas["CaseDetail"]["properties"]
    assert "summary" in schemas["CaseOut"]["properties"]


def test_assist_is_kept_in_conversation(api):
    """보충 설명(assist)은 턴 응답과 대화 기록 모두에 남아 새로고침해도 다시 그린다."""
    from app.agent.golden import normalize_extract

    cid = api.create_case(memo="PP 필름 자투리")["case"]["id"]
    api.llm.push(
        "extract", normalize_extract({"user_question": "왜 물어봐요?", "question_kind": "why"})
    )
    t = api.post(f"/cases/{cid}/diagnosis/messages", json={"text": "왜 물어봐요?"}).json()
    assert t["assist"]["intent"] == "why" and t["assist"]["text"]
    conv = api.get(f"/cases/{cid}").json()["conversation"]
    last = [m for m in conv if m["role"] == "assistant"][-1]
    assert last["assist"]["text"] == t["assist"]["text"]
    assert all(m.get("assist") is None for m in conv[:-1])
