"""서버(scrap-server)가 부르는 내부 API /internal/v1.

인증: Authorization: Bearer <ENGINE_SERVICE_TOKEN>(상수 시간 비교)
+ X-Company-Id(서버가 인증한 기업 ID).
처음 보는 기업 ID는 엔진에 자동으로 만든다. 건은 기업별로 격리된다(다른 기업의 건은 404).
서류는 업로드 → 검수 대기 후보 → 서버 검수(apply) → EVIDENCED 사실로만 판정에 들어간다.
"""

from __future__ import annotations

import hmac
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Path, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.api.schemas import ApplyIn, CaseCreateIn, ConfirmIn, MessageIn, ReopenIn, RevokeIn
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
    request: Request,
    db: Annotated[Session, Depends(db_dep)],
    kb: Annotated[KB, Depends(kb_dep)],
    settings: Annotated[Settings, Depends(settings_dep)],
) -> CaseService:
    return CaseService(db, kb, settings, getattr(request.app.state, "llm", None))


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


DocId = Annotated[str, Path(pattern=_ID)]


async def _read(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ApiError(413, "FILE_TOO_LARGE", "파일이 너무 큽니다")
    return data


@router.post(
    "/cases/{case_id}/documents",
    status_code=201,
    dependencies=deps,
    summary="서류 업로드(값은 검수 대기 후보로만 저장)",
)
async def upload_document(
    case_id: CaseId,
    request: Request,
    file: Annotated[UploadFile, File()],
    facts: Annotated[str | None, Form()] = None,
) -> JSONResponse:
    settings = request.app.state.settings
    data = await _read(file, settings.max_upload_bytes)
    # DB·표 읽기(Azure 포함)는 동기 작업이라 스레드에서 한다(async 안에서 막지 않음)
    return JSONResponse(
        await run_in_threadpool(
            _with_service,
            request,
            "upload_document",
            case_id,
            filename=file.filename or "document",
            content_type=file.content_type,
            data=data,
            facts=facts,
        ),
        status_code=201,
    )


@router.post(
    "/cases/{case_id}/documents/{doc_id}/versions",
    status_code=201,
    dependencies=deps,
    summary="서류 파일 교체(새 버전, 이전 값은 효력 해제)",
)
async def replace_document(
    case_id: CaseId,
    doc_id: DocId,
    request: Request,
    file: Annotated[UploadFile, File()],
    facts: Annotated[str | None, Form()] = None,
) -> JSONResponse:
    settings = request.app.state.settings
    data = await _read(file, settings.max_upload_bytes)
    return JSONResponse(
        await run_in_threadpool(
            _with_service,
            request,
            "replace_document",
            case_id,
            doc_id,
            filename=file.filename or "document",
            content_type=file.content_type,
            data=data,
            facts=facts,
        ),
        status_code=201,
    )


def _with_service(request: Request, method: str, *args, **kwargs):
    """async 라우트에서 쓰는 동기 서비스 호출: 세션을 열고 인증한 기업으로 부른다."""
    company_id = request.headers.get("x-company-id")
    if not company_id:
        raise ApiError(400, "COMPANY_REQUIRED", "X-Company-Id가 필요합니다")
    app = request.app
    for db in app.state.db.session():
        svc = CaseService(db, app.state.kb, app.state.settings, getattr(app.state, "llm", None))
        svc.azure_client = getattr(app.state, "azure_client", None)  # 시험용 주입(기본 None)
        return getattr(svc, method)(svc.company(company_id), *args, **kwargs)


@router.post(
    "/cases/{case_id}/documents/{doc_id}/values/apply",
    dependencies=deps,
    summary="검수한 서류 값을 판정에 반영",
)
def apply_values(
    case_id: CaseId, doc_id: DocId, body: ApplyIn, svc: Service, company: CompanyDep
) -> dict:
    items = [v.model_dump() for v in body.values]
    return svc.apply_values(company, case_id, doc_id, items)


@router.post(
    "/cases/{case_id}/documents/{doc_id}/revoke", dependencies=deps, summary="서류 효력 해제"
)
def revoke_document(
    case_id: CaseId, doc_id: DocId, svc: Service, company: CompanyDep, body: RevokeIn | None = None
) -> dict:
    body = body or RevokeIn()
    return svc.revoke_document(
        company, case_id, doc_id, reason=body.reason, document_version=body.document_version
    )


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
