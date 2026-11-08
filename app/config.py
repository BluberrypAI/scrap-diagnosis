"""설정. `.env`(git 제외)와 환경변수에서 읽는다. 이름은 기존 엔진(resource_engine)과 같다."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    llm_provider: Literal["azure", "off"] = "off"
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    llm_timeout_seconds: float = 60.0

    kb_dir: Path = ROOT / "data" / "real"
    max_questions: int = 12
    prompt_version: str = "m3.1"

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider == "azure" and all(
            (self.azure_openai_endpoint, self.azure_openai_api_key, self.azure_openai_deployment)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
