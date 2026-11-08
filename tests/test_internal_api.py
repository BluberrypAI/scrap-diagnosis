"""/internal/v1 서비스 인증·기업 격리·오류 형식·페이징 (docs/api/server-engine-contract.md)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.persistence.models import Company
from tests.api_support import Api, build_app, fake_llm, make_settings
from tests.conftest import AS_OF, DATA

TOKEN = "test-service-token"
INT = "/internal/v1"


def make_api(kb, tmp_path, **settings_kw) -> Api:
    base = make_settings(tmp_path / "i.db").model_dump()
    llm = fake_llm()
    app = create_app(
        Settings(**{**base, **settings_kw}),
        kb=kb,
        kb_dir=DATA,
        extractor_llm=llm,
        responder_llm=None,
        today=lambda: AS_OF,
    )
    return Api(client=TestClient(app), app=app, llm=llm, db_path=tmp_path / "i.db")


@pytest.fixture
def srv(kb, tmp_path) -> Api:
    return make_api(kb, tmp_path, engine_service_token=TOKEN)


def hdr(company: str | None = "A", token: str | None = TOKEN) -> dict:
    h = {}
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    if company is not None:
        h["X-Company-Id"] = company
    return h


def new_case(srv: Api, company: str = "A") -> str:
    r = srv.client.post(f"{INT}/cases", headers=hdr(company), json={"memo": "필름", "unit": "t"})
    assert r.status_code == 201, r.text
    return r.json()["case"]["id"]


def test_token_missing_or_wrong_is_401(srv):
    for h in (hdr(token=None), hdr(token="wrong"), {**hdr(), "Authorization": "Basic x"}):
        for url in (f"{INT}/cases", f"{INT}/catalog/facts"):
            r = srv.client.get(url, headers=h)
            assert r.status_code == 401, url
            assert r.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_company_header_required_after_token(srv):
    r = srv.client.get(f"{INT}/cases", headers=hdr(company=None))
    assert r.status_code == 400 and r.json()["detail"]["code"] == "COMPANY_REQUIRED"


def test_company_swap_cannot_see_other_case(srv):
    cid = new_case(srv, "A")
    for method, url in [
        ("get", f"{INT}/cases/{cid}"),
        ("get", f"{INT}/cases/{cid}/trace"),
        ("post", f"{INT}/cases/{cid}/confirm"),
        ("post", f"{INT}/cases/{cid}/reopen"),
    ]:
        r = getattr(srv.client, method)(url, headers=hdr("B"))
        assert r.status_code == 404, url
        assert r.json()["detail"]["code"] == "CASE_NOT_FOUND"
    assert srv.client.get(f"{INT}/cases/{cid}", headers=hdr("A")).status_code == 200
    assert srv.client.get(f"{INT}/cases", headers=hdr("B")).json()["items"] == []


def test_company_auto_provisioned_once(srv):
    new_case(srv, "srv-company-77")
    new_case(srv, "srv-company-77")
    with srv.container().sessionmaker() as db:
        rows = db.scalars(select(Company).where(Company.external_id == "srv-company-77")).all()
    assert len(rows) == 1 and rows[0].profile == {}


def test_internal_error_envelope(srv):
    cid = new_case(srv)
    r = srv.client.post(f"{INT}/cases/{cid}/confirm", headers=hdr())
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "NOT_CONFIRMABLE"
    assert d["details"]["branch"] == d["branch"]  # 호환용 flat 필드도 유지
    r = srv.client.post(f"{INT}/cases/{cid}/diagnosis/messages", headers=hdr(), json={})
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "VALIDATION_ERROR" and d["details"]["errors"]


def test_dev_token_optional_when_unset(kb, tmp_path):
    api = make_api(kb, tmp_path)  # dev, 토큰 미설정
    assert api.client.get(f"{INT}/cases", headers=hdr(token=None)).status_code == 200


def test_prod_requires_token_and_disables_dev_endpoints(kb, tmp_path):
    api = make_api(kb, tmp_path, app_env="prod", engine_service_token=TOKEN)
    assert api.client.post("/companies", json={"name": "x"}).status_code == 404
    r = api.client.get("/cases", headers={"X-Company-Id": "x"})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "ENDPOINT_DISABLED"
    r = api.client.put("/companies/me/profile", headers={"X-Company-Id": "x"}, json={})
    assert r.status_code == 404
    assert api.client.get(f"{INT}/cases", headers=hdr()).status_code == 200
    assert api.client.get(f"{INT}/cases", headers=hdr(token="bad")).status_code == 401
    assert api.client.get("/health").status_code == 200


def test_prod_without_token_rejects_internal(kb, tmp_path):
    api = make_api(kb, tmp_path, app_env="prod")
    r = api.client.get(f"{INT}/cases", headers=hdr(token=None))
    assert r.status_code == 401 and r.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_unknown_route_uses_envelope(srv):
    r = srv.client.get("/nope")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NOT_FOUND" and r.json()["detail"]["message"]


def test_internal_paging(srv):
    ids = [new_case(srv) for _ in range(5)]
    body = srv.client.get(f"{INT}/cases", headers=hdr()).json()
    assert len(body["items"]) == 5
    assert body["pagingInfo"] == {
        "currentPageNumber": 1,
        "pageSize": 20,
        "totalCount": 5,
        "totalPages": 1,
    }
    body = srv.client.get(f"{INT}/cases?page=2&size=2", headers=hdr()).json()
    assert len(body["items"]) == 2
    assert body["pagingInfo"] == {
        "currentPageNumber": 2,
        "pageSize": 2,
        "totalCount": 5,
        "totalPages": 3,
    }
    seen = {
        c["id"]
        for p in (1, 2, 3)
        for c in srv.client.get(f"{INT}/cases?page={p}&size=2", headers=hdr()).json()["items"]
    }
    assert seen == set(ids)
    assert srv.client.get(f"{INT}/cases?page=9&size=2", headers=hdr()).json()["items"] == []
    for q in ("page=0", "size=0", "size=101", "page=x"):
        r = srv.client.get(f"{INT}/cases?{q}", headers=hdr())
        assert r.status_code == 422 and r.json()["detail"]["code"] == "VALIDATION_ERROR", q


def test_root_list_keeps_array_shape_and_optional_paging(kb, tmp_path):
    app = build_app(kb, tmp_path / "r.db", fake_llm())
    a = Api(client=TestClient(app), app=app, llm=None, db_path=tmp_path / "r.db")
    a.use(a.company())
    for _ in range(3):
        a.create_case()
    r = a.get("/cases")
    assert isinstance(r.json(), list) and len(r.json()) == 3
    assert r.headers["X-Total-Count"] == "3"
    r = a.get("/cases?page=2&size=2")
    assert len(r.json()) == 1 and r.headers["X-Total-Count"] == "3"
