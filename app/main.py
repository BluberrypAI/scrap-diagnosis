"""FastAPI 앱 팩토리. 실행: `uv run uvicorn app.main:app --port 8030`."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import anyio.to_thread
from fastapi import Depends, FastAPI
from sqlalchemy import Engine

from app.agent.llm_client import LLMClient
from app.api.deps import _UNSET, INTERNAL_PREFIX, AppContainer, require_service_auth
from app.api.errors import install_error_handlers
from app.api.routes import (
    case_router,
    company_data_router,
    dev_router,
    internal_list_router,
    root_list_router,
)
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
        # 동기 핸들러(def)를 돌리는 스레드 수. 동시에 진행할 수 있는 턴 수의 상한이다.
        anyio.to_thread.current_default_thread_limiter().total_tokens = (
            container.settings.thread_limit
        )
        container.warmup()  # 규칙 로드·DB 준비를 첫 요청 전에
        yield

    app = FastAPI(
        title="waste-diagnosis",
        version="0.4.0",
        description="폐기물 코드 판정 엔진과 문진 에이전트 (M4 API)",
        lifespan=lifespan,
    )
    app.state.container = container
    install_error_handlers(app)
    # 루트 경로: 참조 화면·개발용(X-Company-Id만). prod에서는 company 의존성이 404로 막는다.
    app.include_router(dev_router)
    app.include_router(root_list_router)
    app.include_router(case_router)
    # /internal/v1: scrap-server용. 같은 핸들러를 서비스 토큰 인증 아래에 한 번 더 올린다.
    internal_deps = [Depends(require_service_auth)]
    for r in (internal_list_router, case_router, company_data_router):
        app.include_router(r, prefix=INTERNAL_PREFIX, tags=["internal"], dependencies=internal_deps)

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
