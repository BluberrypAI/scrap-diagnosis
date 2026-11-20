"""DB 연결. SQLite(개발·테스트)와 PostgreSQL(운영)을 같은 코드로 쓴다."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.persistence.models import Base


def normalize_url(url: str) -> str:
    # 배포 환경이 postgresql://로 주면 psycopg(v3) 드라이버를 쓴다
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def make_engine(settings: Settings) -> Engine:
    url = normalize_url(settings.database_url)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
    )


class Database:
    def __init__(self, settings: Settings) -> None:
        self.engine = make_engine(settings)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        if settings.db_create_all:
            Base.metadata.create_all(self.engine)

    def session(self) -> Iterator[Session]:
        with self.sessions() as s:
            yield s
