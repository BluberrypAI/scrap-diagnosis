"""서버(scrap-server)가 부르는 내부 API /internal/v1.

인증: Authorization: Bearer <ENGINE_SERVICE_TOKEN>(상수 시간 비교)
+ X-Company-Id(서버가 인증한 기업 ID).
처음 보는 기업 ID는 엔진에 자동으로 만든다. 건은 기업별로 격리된다(다른 기업의 건은 404).
서류 업로드·검수 경로는 v2에서 아직 없다(기름 함량은 질문으로 받는다).
"""

from __future__ import annotations

import hmac
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.api.schemas import CaseCreateIn, ConfirmIn, MessageIn, ReopenIn
from app.config import Settings
from app.engine.kb import KB
from app.interview import catalog as cat
from app.interview.service import CaseService
from app.persistence.models import Company

router = APIRouter(prefix="/internal/v1")

_ID = r"^[A-Za-z0-9_-]{1,64}$"
CaseId = Annotated[str, Path(pattern=_ID)]


def settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def kb_dep(request: Request) -> KB:
    return request.app.state.kb


def db_dep(request: Request) -> Iterator[Session]:
    yield from request.app.state.db.session()


def auth(
    settings: Annotated[Settings, Depends(settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    token = settings.engine_service_token.get_secret_value()
    if not token:
        if settings.app_env == "prod":
            raise ApiError(401, "AUTH_REQUIRED", "엔진 인증 설정이 없습니다")
        return  # 로컬 개발 편의: 토큰을 안 정했으면 통과
    scheme, _, value = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(value.encode(), token.encode()):
        raise ApiError(401, "AUTH_REQUIRED", "인증이 필요합니다")


def service_dep(
    db: Annotated[Session, Depends(db_dep)],
    kb: Annotated[KB, Depends(kb_dep)],
    settings: Annotated[Settings, Depends(settings_dep)],
) -> CaseService:
    return CaseService(db, kb, settings)


Service = Annotated[CaseService, Depends(service_dep)]


def company_dep(
    svc: Service,
    x_company_id: Annotated[str | None, Header(max_length=128)] = None,
) -> Company:
    if not x_company_id:
        raise ApiError(400, "COMPANY_REQUIRED", "X-Company-Id가 필요합니다")
    return svc.company(x_company_id)


CompanyDep = Annotated[Company, Depends(company_dep)]
deps = [Depends(auth)]


@router.post("/cases", status_code=201, dependencies=deps, summary="건 만들기 + 첫 질문")
def create_case(body: CaseCreateIn, svc: Service, company: CompanyDep) -> JSONResponse:
    return JSONResponse(svc.create_case(company, body.model_dump()), status_code=201)


@router.get("/cases", dependencies=deps, summary="기업의 건 목록(최근 갱신순)")
def list_cases(
    svc: Service,
    company: CompanyDep,
    status: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    out = svc.list_cases(company, status, page, size)
    svc.db.commit()  # 처음 보는 기업 행 저장
    return out


@router.get("/cases/{case_id}", dependencies=deps, summary="건 상세")
def get_case(case_id: CaseId, svc: Service, company: CompanyDep) -> dict:
    return svc.detail(company, case_id)


@router.post("/cases/{case_id}/diagnosis/messages", dependencies=deps, summary="문진 답변")
def send_message(case_id: CaseId, body: MessageIn, svc: Service, company: CompanyDep) -> dict:
    return svc.message(company, case_id, body.model_dump(exclude_none=True))


@router.post("/cases/{case_id}/confirm", dependencies=deps, summary="판정 확정 + 인계 객체")
def confirm(
    case_id: CaseId, svc: Service, company: CompanyDep, body: ConfirmIn | None = None
) -> dict:
    return svc.confirm(company, case_id, body.expected_code if body else None)


@router.post("/cases/{case_id}/reopen", dependencies=deps, summary="확정 건 다시 열기")
def reopen(
    case_id: CaseId, svc: Service, company: CompanyDep, body: ReopenIn | None = None
) -> dict:
    return svc.reopen(company, case_id, body.reason if body else None)


@router.post("/cases/{case_id}/rebase", dependencies=deps, summary="바뀐 규칙으로 다시 평가")
def rebase(case_id: CaseId, svc: Service, company: CompanyDep) -> dict:
    return svc.rebase(company, case_id)


@router.get("/cases/{case_id}/trace", dependencies=deps, summary="판정 근거 추적")
def trace(case_id: CaseId, svc: Service, company: CompanyDep) -> dict:
    return svc.trace_out(company, case_id)


@router.get("/catalog/facts", dependencies=deps, summary="사실 카탈로그(라벨·선택지)")
def catalog_facts(kb: Annotated[KB, Depends(kb_dep)]) -> list[dict]:
    out = []
    for path in cat.all_paths(kb.plan.catalog):
        s = cat.spec(kb.plan.catalog, path)
        out.append(
            {
                "key": path,
                "label": s["label"],
                "type": cat.value_type(s),
                "unit": s.get("unit"),
                "values": [
                    {"value": v, "label": label}
                    for v, label in cat.value_map(s).items()
                    if v != "unknown"
                ],
                "parent": None,
            }
        )
    return out


@router.delete("/companies/{external_id}/data", dependencies=deps, summary="기업 데이터 삭제")
def delete_company(external_id: Annotated[str, Path(max_length=128)], svc: Service) -> dict:
    return svc.delete_company(external_id)


@router.get("/companies/{external_id}/data/deletion", dependencies=deps, summary="최근 삭제 이력")
def deletion(external_id: Annotated[str, Path(max_length=128)], svc: Service) -> dict:
    return svc.deletion(external_id)
