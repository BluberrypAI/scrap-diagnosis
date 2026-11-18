"""설정. `.env`(git 제외)와 환경변수에서 읽는다. 이름은 기존 엔진(resource_engine)과 같다."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
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
    # 호출별 추론 강도(추론 모델만). 비우면 모델 기본값.
    # 같은 배포를 쓰므로 프롬프트 캐시는 유지된다.
    # 응답(respond)은 엔진이 정한 내용을 문장으로만 다듬으므로 낮춰도 판정에 영향이 없다.
    # 추출 medium: 2026-11-18 low/medium/high 비교에서 정확도·시간·비용 균형이 가장 좋았다
    extract_reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = "medium"
    respond_reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None

    kb_dir: Path = ROOT / "data" / "real"
    max_questions: int = 40  # 안전장치(app/agent/router.py DEFAULT_MAX_QUESTIONS)
    # m3.2: 소재 분류(material_group) 추출·묶음 긍정 답 규칙. m3.3: 코드 없는 결론의 확정 안내(응답)
    # m3.4: 추출 프롬프트 순서(고정 자료를 앞에, 캐시 적중용). 내용은 같다
    prompt_version: str = "m3.4"

    # M4: API·영속화. 개발은 SQLite(저장소 기준 var/app.db), 운영은 PostgreSQL URL.
    database_url: str = f"sqlite:///{(ROOT / 'var' / 'app.db').as_posix()}"
    db_create_all: bool = True  # 개발 편의: 시작할 때 테이블 생성. 운영은 alembic upgrade head
    # DB 연결 풀(PostgreSQL 등. SQLite 파일 DB에는 적용하지 않음). 동시에 DB를 쓰는 요청 수의 상한.
    # 문진 턴은 AI 응답을 기다리는 동안 연결을 놓으므로 thread_limit보다 작아도 된다.
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: float = 30.0
    # 동기 핸들러(def)를 실행하는 스레드 수(FastAPI/anyio 기본 40).
    # 동시에 진행할 수 있는 턴 수의 상한이다.
    # 부하 측정: docs/perf/sync-vs-async.md (200이면 비동기와 처리량이 거의 같았다)
    thread_limit: int = 40
    # 배포 환경. prod: 서비스 토큰 필수, 개발용 엔드포인트(기업 생성·수정, 루트 경로) 차단
    app_env: Literal["dev", "prod"] = "dev"
    # scrap-server가 /internal/v1을 부를 때 보내는 Bearer 토큰(ENGINE_SERVICE_TOKEN). prod 필수.
    engine_service_token: str | None = None
    max_upload_bytes: int = 10 * 1024 * 1024
    document_text_limit: int = 20000  # 문서 추출 때 LLM에 넘기는 최대 글자 수

    # AI 전송 정책(CORP-008·OPS-010·OPS-003)
    allow_document_llm: bool = False  # 서류 원문을 AI로 보내도 되는지. 기본 차단
    trace_store_prompts: bool = True  # False면 Trace에 가린 프롬프트도 남기지 않고 해시·길이만

    # 보충 설명의 마지막 수단: 준비된 설명 자료가 없을 때만 웹 검색
    # (기본 꺼짐, app/agent/web_search.py)
    web_search_provider: Literal["none", "naver"] = "none"
    naver_client_id: str | None = None
    naver_client_secret: str | None = None

    # 서류 표 인식(docs/design/test-report-table-extraction.md 9절).
    # 원본 쪽 이미지를 Azure Document Intelligence로 보낸다. 엔진과 같은 구독·리전의 리소스만 쓴다.
    document_table_reading: bool = True  # PDF·이미지 업로드 때 시험성적서 표 자동 읽기(후보만)
    allow_document_ocr: bool = False  # 기본 꺼짐: 개발·시험 환경의 과금·전송을 막는다
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
    def ocr_enabled(self) -> bool:
        return self.allow_document_ocr and bool(
            self.azure_docintel_endpoint and self.azure_docintel_api_key
        )

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider == "azure" and all(
            (self.azure_openai_endpoint, self.azure_openai_api_key, self.azure_openai_deployment)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
