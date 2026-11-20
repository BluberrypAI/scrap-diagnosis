"""환경 설정. 값은 환경변수(.env)에서 읽는다. 비밀값은 로그에 쓰지 않는다."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
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

    # LLM(말 이해·질의응답 agent·질문 문장). 판정은 하지 않는다. off면 버튼 답만 받는다
    llm_provider: Literal["azure", "off"] = "off"
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    llm_timeout_seconds: float = 20.0
    # 호출별 추론 강도(추론 모델만). 비우면 모델 기본값
    extract_reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = "medium"
    respond_reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None
    assist_max_tool_calls: int = 3  # 질의응답 agent의 도구 호출 상한
    trace_store_prompts: bool = False  # Trace에 가린 프롬프트 원문을 남길지(기본은 해시·길이만)
    prompt_version: str = "v2.1"

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

    @field_validator("extract_reasoning_effort", "respond_reasoning_effort", mode="before")
    @classmethod
    def _blank_effort(cls, v: object) -> object:
        # .env에서 빈 값(EXTRACT_REASONING_EFFORT=)이면 모델 기본값을 쓴다
        return None if v == "" else v

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider == "azure" and all(
            (self.azure_openai_endpoint, self.azure_openai_api_key, self.azure_openai_deployment)
        )

    @property
    def ocr_enabled(self) -> bool:
        return self.allow_document_ocr and bool(
            self.azure_docintel_endpoint and self.azure_docintel_api_key
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
