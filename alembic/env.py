"""Alembic 환경. 대상 메타데이터는 app.persistence.models.Base.

DB URL 우선순위: `-x url=...` > alembic.ini의 sqlalchemy.url(코드에서 설정한 경우)
> Settings.database_url
"""

from logging.config import fileConfig

from alembic import context

from app.config import get_settings
from app.persistence.db import make_engine
from app.persistence.models import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    x = context.get_x_argument(as_dictionary=True)
    return x.get("url") or config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        engine = make_engine(_url())
        with engine.connect() as connection:
            _run(connection)
        engine.dispose()
    else:
        _run(connectable)


def _run(connection) -> None:  # noqa: ANN001
    # SQLite batch 변경은 테이블을 새로 만들고 옛 테이블을 지운다. 외래 키 검사가 켜져 있으면
    # 참조하는 행이 있을 때 DROP이 실패하므로 마이그레이션 동안 끈다.
    # (이 PRAGMA는 트랜잭션 밖에서만 바뀐다)
    sqlite = connection.dialect.name == "sqlite" and not connection.in_transaction()
    if sqlite:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
    try:
        _migrate(connection)
    finally:
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def _migrate(connection) -> None:  # noqa: ANN001
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite ALTER 제약 대응
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
