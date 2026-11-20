"""엔진 앱 진입점: uvicorn app.main:app --port 8030"""

from __future__ import annotations

from fastapi import FastAPI

from app.api import errors
from app.api.routes import router
from app.config import Settings, get_settings
from app.engine.kb import load_kb
from app.llm.client import make_client
from app.persistence.db import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="scrap-diagnosis", version="2.0.0")
    app.state.settings = settings
    app.state.kb = load_kb()  # 결과 안내가 빠진 규칙이 있으면 여기서 실패한다
    app.state.db = Database(settings)
    app.state.llm = make_client(settings)  # LLM 설정이 없으면 None(버튼 답만)
    errors.install(app)
    app.include_router(router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "kb_version": app.state.kb.version}

    return app


app = create_app()
