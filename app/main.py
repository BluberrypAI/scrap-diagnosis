"""FastAPI 앱 팩토리. 실행: `uv run uvicorn app.main:app --port 8030`."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import Engine

from app.agent.llm_client import LLMClient
from app.api.deps import _UNSET, AppContainer
from app.api.routes import router
from app.config import Settings, get_settings
from app.rules.model import KnowledgeBase


def create_app(
    settings: Settings | None = None,
    *,
    kb: KnowledgeBase | None = None,
    kb_dir: Path | None = None,
    extractor_llm: LLMClient | None | object = _UNSET,
    responder_llm: LLMClient | None | object = _UNSET,
    engine: Engine | None = None,
    today: Callable[[], date] | None = None,
) -> FastAPI:
    """KB·LLM·DB는 앱마다 한 번 만든다. 인자를 주지 않으면 settings에서 만든다."""
    container = AppContainer(
        settings or get_settings(),
        kb=kb,
        kb_dir=kb_dir,
        extractor_llm=extractor_llm,
        responder_llm=responder_llm,
        engine=engine,
        today=today,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        container.warmup()  # 규칙 로드·DB 준비를 첫 요청 전에
        yield

    app = FastAPI(
        title="waste-diagnosis",
        version="0.4.0",
        description="폐기물 코드 판정 엔진과 문진 에이전트 (M4 API)",
        lifespan=lifespan,
    )
    app.state.container = container
    app.include_router(router)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        info = container.kb_info
        return {
            "status": "ok",
            "kb_dir": info.kb_dir,
            "kb_version": info.version,
            "tables": len(info.table_versions),
            "llm": container.extractor_llm is not None,
        }

    return app


app = create_app()
