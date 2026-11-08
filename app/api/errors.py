"""오류 응답 형식: `{"detail": {"message": "…", …}}` (docs/ui/ui-contract.md 6절).

화면은 `detail.message`를 보여 준다. 요청 형식 검증 오류(422)는 FastAPI 기본 형식
(`{"detail": [{"loc": …, "msg": …}]}`)을 그대로 둔다.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str


class ErrorResponse(BaseModel):
    """우리 라우트가 내는 오류(401·404·409·413·415·422(문서 사실) 등)."""

    detail: ErrorDetail


def api_error(status: int, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status, {"message": message, **extra})


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "X-Company-Id 헤더가 없거나 모르는 기업"},
    404: {"model": ErrorResponse, "description": "건이 없거나 다른 기업의 건"},
    409: {"model": ErrorResponse, "description": "상태 위반·확정 불가·동시 수정"},
}
