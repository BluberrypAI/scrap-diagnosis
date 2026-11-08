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


def make_engine(url: str) -> Engine:
    u = make_url(url)
    kwargs: dict = {}
    if u.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
        if u.database in (None, "", ":memory:"):
            kwargs["poolclass"] = StaticPool  # 메모리 DB를 연결 사이에 공유
        else:
            Path(u.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
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
