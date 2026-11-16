"""오류 응답 형식: `{"detail": {"code": "…", "message": "…", "details": {…}}}`.

- `code`: 기계가 읽는 오류 코드(docs/api/server-engine-contract.md). 서버·화면은 `code`로 분기한다.
- `message`: 사람이 읽는 한국어 문장(기존 화면은 `detail.message`를 보여 준다).
- `details`: 코드별 부가 정보(없으면 빈 객체). 기존 호환용으로 같은 값을 `detail` 아래에도 둔다.
- 요청 형식 검증 오류(422)도 같은 형식(`VALIDATION_ERROR`, `details.errors`)으로 감싼다.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

_DEFAULT_CODES = {
    400: "BAD_REQUEST",
    401: "AUTH_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "FILE_TOO_LARGE",
    415: "UNSUPPORTED_DOCUMENT",
    422: "VALIDATION_ERROR",
}


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """우리 라우트가 내는 모든 오류(401·404·409·413·415·422 등)."""

    detail: ErrorDetail


def default_code(status: int) -> str:
    return _DEFAULT_CODES.get(status, "INTERNAL_ERROR" if status >= 500 else "ERROR")


def error_body(status: int, message: str, code: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"code": code or default_code(status), "message": message, "details": extra, **extra}


def api_error(status: int, message: str, code: str | None = None, **extra: Any) -> HTTPException:
    return HTTPException(status, error_body(status, message, code, **extra))


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "AUTH_REQUIRED·COMPANY_REQUIRED"},
    404: {"model": ErrorResponse, "description": "CASE_NOT_FOUND(다른 기업의 건 포함)"},
    409: {"model": ErrorResponse, "description": "상태 위반·확정 불가·코드 불일치·동시 수정"},
    422: {"model": ErrorResponse, "description": "VALIDATION_ERROR(details.errors)"},
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        body = error_body(422, "요청 값이 올바르지 않습니다", "VALIDATION_ERROR", errors=errors)
        return JSONResponse({"detail": jsonable_encoder(body)}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if not isinstance(
            detail, dict
        ):  # 없는 경로(404)·허용되지 않는 메서드(405) 등 프레임워크 오류
            detail = error_body(exc.status_code, str(detail))
        return JSONResponse(
            {"detail": detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None)
        )
