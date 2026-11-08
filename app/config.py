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
    # m3.2: 소재 분류(material_group) 추출·묶음 긍정 답 규칙. m3.3: 코드 없는 결론의 확정 안내(응답)
    prompt_version: str = "m3.3"

    # M4: API·영속화. 개발은 SQLite(저장소 기준 var/app.db), 운영은 PostgreSQL URL.
    database_url: str = f"sqlite:///{(ROOT / 'var' / 'app.db').as_posix()}"
    db_create_all: bool = True  # 개발 편의: 시작할 때 테이블 생성. 운영은 alembic upgrade head
    max_upload_bytes: int = 10 * 1024 * 1024
    document_text_limit: int = 20000  # 문서 추출 때 LLM에 넘기는 최대 글자 수

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider == "azure" and all(
            (self.azure_openai_endpoint, self.azure_openai_api_key, self.azure_openai_deployment)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
