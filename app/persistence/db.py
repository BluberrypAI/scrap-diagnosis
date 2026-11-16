"""DB 엔진·세션 팩토리와 불변 Trace 보호."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.persistence.models import Base, TraceRecord


class ImmutableTraceError(RuntimeError):
    """확정 시점에 고정된 Trace를 고치거나 지우려 함."""


def make_engine(
    url: str,
    *,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_timeout: float = 30.0,
) -> Engine:
    """SQLite(개발·테스트)와 PostgreSQL(운영, `postgresql+psycopg://…`)을 받는다.

    PostgreSQL URL이 `postgresql://`이면 psycopg(3) 드라이버로 바꾼다(SQLAlchemy 기본은 psycopg2).
    """
    u = make_url(url)
    kwargs: dict = {}
    if u.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
        if u.database in (None, "", ":memory:"):
            kwargs["poolclass"] = StaticPool  # 메모리 DB를 연결 사이에 공유
        else:
            Path(u.database).parent.mkdir(parents=True, exist_ok=True)
    else:
        if u.get_backend_name() == "postgresql" and u.get_driver_name() in ("", "psycopg2"):
            u = u.set(drivername="postgresql+psycopg")
        kwargs.update(
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_pre_ping=True,  # 끊긴 연결(DB 재시작·유휴 종료)을 쓰기 전에 걸러낸다
        )
    engine = create_engine(u, **kwargs)
    if u.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def create_all(engine: Engine) -> None:
    """개발·테스트용. 운영은 `alembic upgrade head`."""
    Base.metadata.create_all(engine)


@event.listens_for(TraceRecord, "before_update")
def _guard_trace_update(mapper, connection, target: TraceRecord) -> None:  # noqa: ANN001
    state = inspect(target)
    was_immutable = state.attrs.immutable.history.deleted
    if (was_immutable and was_immutable[0]) or (
        target.immutable and not state.attrs.immutable.history.added
    ):
        raise ImmutableTraceError(f"불변 Trace(seq={target.seq})는 고칠 수 없습니다")


@event.listens_for(TraceRecord, "before_delete")
def _guard_trace_delete(mapper, connection, target: TraceRecord) -> None:  # noqa: ANN001
    if target.immutable:
        raise ImmutableTraceError(f"불변 Trace(seq={target.seq})는 지울 수 없습니다")
