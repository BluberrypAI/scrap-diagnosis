import os

# app.main을 import할 때 만드는 기본 앱이 작업 폴더에 DB 파일을 만들지 않게 한다
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ENGINE_SERVICE_TOKEN", "")

import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.persistence.db import normalize_url  # noqa: E402

TOKEN = "test-token"
# 설정하면 PostgreSQL에서 테스트마다 새 데이터베이스를 만든다(CI). 없으면 SQLite 파일
PG_URL = os.environ.get("TEST_DATABASE_URL")
_created: list[str] = []


def _database_url(tmp_path) -> str:
    if not PG_URL:
        return f"sqlite:///{tmp_path / 'engine.db'}"
    base = normalize_url(PG_URL)
    name = f"t_{uuid.uuid4().hex[:12]}"
    with create_engine(base, isolation_level="AUTOCOMMIT").connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    _created.append(name)
    return base.rsplit("/", 1)[0] + f"/{name}"


def pytest_sessionfinish(session, exitstatus):
    if not _created:
        return
    with create_engine(normalize_url(PG_URL), isolation_level="AUTOCOMMIT").connect() as conn:
        for name in _created:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def make_client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        _env_file=None,
        database_url=_database_url(tmp_path),
        engine_service_token=overrides.pop("token", TOKEN),
        **overrides,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.fixture
def client(tmp_path):
    with make_client(tmp_path) as c:
        yield c


def headers(company: str = "co-1") -> dict:
    return {"Authorization": f"Bearer {TOKEN}", "X-Company-Id": company}
