"""DB 연결 풀·스레드 설정(8번). TEST_DATABASE_URL이면 PostgreSQL에서도 같은 검사를 한다."""

from __future__ import annotations

import anyio.to_thread
from fastapi.testclient import TestClient

from app.agent.golden import normalize_extract
from app.agent.llm_client import FakeLLMClient
from app.config import Settings
from app.main import create_app
from app.persistence.db import make_engine
from tests.api_support import Api, build_app
from tests.conftest import DATA
from tests.dbutil import db_url


def test_turn_releases_db_connection_during_llm_call(kb, tmp_path):
    """AI 응답을 기다리는 동안(수 초) DB 연결을 붙잡지 않는다. 풀이 작아도 동시 턴이 막히지 않게."""
    seen: list[int] = []
    holder: dict = {}

    def extract(name: str, system: str, user: str) -> dict:
        seen.append(holder["engine"].pool.checkedout())
        return normalize_extract({})

    app = build_app(kb, tmp_path / "pool.db", FakeLLMClient(default=extract))
    with TestClient(app) as client:
        holder["engine"] = app.state.container.engine
        api = Api(client=client, app=app, llm=None, db_path=tmp_path / "pool.db")
        api.use(api.company())
        cid = api.create_case("PP 스크랩이에요")["case"]["id"]  # 첫 메모 → 추출 호출
        api.say(cid, "고체예요")  # 답변 → 추출 호출
    assert len(seen) >= 2
    assert seen == [0] * len(seen), seen


def test_thread_limit_setting_applies(tmp_path):
    settings = Settings(
        database_url=db_url(tmp_path / "t.db"), llm_provider="off", kb_dir=DATA, thread_limit=77
    )
    app = create_app(settings, kb_dir=DATA, extractor_llm=None, responder_llm=None)
    with TestClient(app) as client:
        tokens = client.portal.call(
            lambda: anyio.to_thread.current_default_thread_limiter().total_tokens
        )
    assert tokens == 77


def test_postgres_url_uses_psycopg_driver():
    eng = make_engine("postgresql://u:p@localhost:5432/db", pool_size=3, max_overflow=4)
    assert eng.driver == "psycopg"
    assert eng.pool.size() == 3
    eng.dispose()
