"""환경 설정. 값은 환경변수(.env)에서 읽는다. 비밀값은 로그에 쓰지 않는다."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["dev", "prod"] = "dev"
    engine_service_token: SecretStr = SecretStr("")
    database_url: str = "sqlite:///./diagnosis.db"
    db_create_all: bool = True
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    max_questions: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
