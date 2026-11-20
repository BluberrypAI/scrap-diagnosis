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

    # 서류(성적서) 업로드·자동 읽기. 원문 파일은 저장하지 않고 해시·크기만 남긴다
    max_upload_bytes: int = 10 * 1024 * 1024
    document_table_reading: bool = True  # PDF·이미지의 시험성적서 표 자동 읽기(검수 대기 후보만)
    # 스캔본 PDF·사진 읽기(Azure Document Intelligence). 기본 꺼짐: 켜고 키를 넣을 때만 과금된다.
    # 켜면 원본 쪽 이미지를 Azure로 보낸다(엔진과 같은 구독·리전 리소스만 쓴다)
    allow_document_ocr: bool = False
    azure_docintel_endpoint: str | None = None
    azure_docintel_api_key: str | None = None
    azure_docintel_model: str = "prebuilt-layout"
    ocr_timeout_seconds: float = 120.0

    @property
    def ocr_enabled(self) -> bool:
        return self.allow_document_ocr and bool(
            self.azure_docintel_endpoint and self.azure_docintel_api_key
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
