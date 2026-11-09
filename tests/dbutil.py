"""테스트용 DB 주소. 기본은 임시 SQLite 파일, `TEST_DATABASE_URL`을 주면 PostgreSQL.

PostgreSQL로 돌리기(docker-compose.yml의 db 서비스):
    docker compose up -d db
    TEST_DATABASE_URL=postgresql+psycopg://wd:wd@localhost:55432/postgres uv run pytest

같은 경로(db_path)는 같은 DB를 가리킨다(앱 재시작 테스트). 테스트마다 새 DB를 만들고 끝나면 지운다.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

TEST_PG = os.environ.get("TEST_DATABASE_URL") or None
_PREFIX = "wdt_"
_created: set[str] = set()


def _admin():  # noqa: ANN202
    return create_engine(TEST_PG, isolation_level="AUTOCOMMIT")


def db_url(path: Path) -> str:
    """SQLite 파일 경로 대신 쓸 DB URL."""
    if TEST_PG is None:
        return f"sqlite:///{path.as_posix()}"
    name = _PREFIX + hashlib.sha1(str(path).encode()).hexdigest()[:20]
    if name not in _created:
        eng = _admin()
        with eng.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            c.execute(text(f'CREATE DATABASE "{name}"'))
        eng.dispose()
        _created.add(name)
    return make_url(TEST_PG).set(database=name).render_as_string(hide_password=False)


def drop_all() -> None:
    """이번 실행에서 만든 테스트 DB를 모두 지운다."""
    if TEST_PG is None or not _created:
        return
    eng = _admin()
    with eng.connect() as c:
        for name in sorted(_created):
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    eng.dispose()
    _created.clear()
