"""Alembic 실행 환경. DB 주소는 app.config(DATABASE_URL)에서 읽는다."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.config import get_settings
from app.persistence.db import normalize_url
from app.persistence.models import Base

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)

URL = normalize_url(get_settings().database_url)


def run_offline() -> None:
    context.configure(url=URL, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = create_engine(URL)
    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=Base.metadata,
            render_as_batch=conn.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
