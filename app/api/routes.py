"""HTTP 라우터 (docs/api/api-spec.md). 비즈니스 로직은 service.py에 있다."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.api.deletion import DeletionFailed, delete_company_data, latest_deletion
from app.api.deps import (
    CompanyDep,
    DbDep,
    KBDep,
    KBInfoDep,
    LLMsDep,
    SettingsDep,
    TodayDep,
    is_internal,
    require_dev_endpoint,
)
from app.api.documents import UnsupportedDocument
from app.api.errors import ERROR_RESPONSES, ErrorResponse, api_error
from app.api.profile import ProfileOptions, profile_options
from app.api.schemas import (
    ApplyIn,
    CaseCreate,
    CaseCreated,
    CaseDetail,
    CaseListPage,
    CaseOut,
    CatalogFact,
    CatalogValue,
    CompanyCreate,
    CompanyOut,
    CompanyProfileUpdate,
    ConfirmIn,
    ConfirmOut,
    DeletionOut,
    DocumentOut,
    DocumentTurn,
    DocumentValueOut,
    MessageIn,
    PagingInfo,
    ReopenIn,
    ReopenOut,
    RevokeIn,
    TraceOut,
    TraceRowOut,
    TraceSessionOut,
    VerdictOut,
)
from app.api.service import CaseService, ServiceError
from app.config import Settings
from app.domain.case import CaseStatus
from app.domain.recycling import assess_recycling
from app.domain.verdict import TurnResponse
from app.persistence.models import Company, Document, WasteCase, new_id

# 라우터 구성
# - dev_router: 개발용 기업 API. 루트 경로에만 둔다(prod에서는 404).
# - case_router: 건·문진·카탈로그. 루트(참조 화면)와 `/internal/v1`(scrap-server) 양쪽에 올린다.
# - root_list_router / internal_list_router: 목록만 응답 모양이 달라 따로 둔다.
dev_router = APIRouter(responses=ERROR_RESPONSES)
case_router = APIRouter(responses=ERROR_RESPONSES)
root_list_router = APIRouter(responses=ERROR_RESPONSES)
internal_list_router = APIRouter(responses=ERROR_RESPONSES)
company_data_router = APIRouter(responses=ERROR_RESPONSES)  # /internal/v1 전용(루트에는 없음)
router = dev_router  # 하위 호환 이름
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
STALE_MESSAGE = "다른 요청이 같은 문진을 먼저 갱신했습니다. 다시 시도하세요"


def get_service(
    db: DbDep,
    kb: KBDep,
    kb_info: KBInfoDep,
    llms: LLMsDep,
    settings: SettingsDep,
    today: TodayDep,
    company: CompanyDep,
    request: Request,
) -> CaseService:
    """요청 하나 = DB 트랜잭션 하나. 커밋하지 않고 끝나면 세션을 닫으면서 되돌린다.

    엔진 자체 기업 정보(PROFILE) 시딩은 개발·참조 화면(루트 경로, prod 아님)에서만 한다.
    """
    return CaseService(
        db,
        kb,
        kb_info,
        llms,
        settings,
        today,
        company,
        seed_local_profile=not is_internal(request),
        azure_client=getattr(request.app.state.container, "azure_client", None),
    )


ServiceDep = Annotated[CaseService, Depends(get_service)]


def _commit(svc: CaseService) -> None:
    try:
        svc.db.commit()
    except (StaleDataError, IntegrityError) as exc:
        # 같은 세션에 동시 요청: revision(낙관적 잠금) 또는 (session_id, seq) 유일 제약 충돌
        svc.db.rollback()
        raise api_error(409, STALE_MESSAGE, "CONCURRENT_UPDATE") from exc


def _case_out(svc: CaseService, case: WasteCase) -> CaseOut:
    rec = svc.repo.latest_for_case(case.id)
    return CaseOut.model_validate(
        {
            "id": case.id,
            "company_id": case.company_id,
            "memo": case.memo,
            "quantity": case.quantity,
            "unit": case.unit,
            "period": case.period,
            "status": case.status,
            "session_id": rec.id if rec else None,
            "created_at": case.created_at,
            "updated_at": case.updated_at,
            "diagnosis_started_at": rec.started_at if rec else None,
            "last_activity_at": rec.last_activity_at if rec else None,
            "as_of": rec.as_of if rec else None,
            "summary": svc.summary(case, rec),
            "kb_changed": svc.repo.kb_changed(rec),
        }
    )


def _doc_out(svc: CaseService, doc: Document) -> DocumentOut:
    out = DocumentOut.model_validate(doc)
    out.values = [DocumentValueOut.model_validate(v) for v in svc.document_values(doc)]
    return out


def _run(svc: CaseService, fn, *args, **kwargs):  # noqa: ANN001, ANN202
    try:
        return fn(*args, **kwargs)
    except ServiceError as exc:
        svc.db.rollback()
        raise api_error(exc.status, exc.message, exc.code, **exc.extra) from exc
    except UnsupportedDocument as exc:
        svc.db.rollback()
        raise api_error(415, str(exc), "UNSUPPORTED_DOCUMENT") from exc
    except (StaleDataError, IntegrityError) as exc:
        svc.db.rollback()
        raise api_error(409, STALE_MESSAGE, "CONCURRENT_UPDATE") from exc


# ---- 기업 (개발용 최소 API) --------------------------------------------------------------


@dev_router.post(
    "/companies",
    response_model=CompanyOut,
    status_code=201,
    tags=["companies"],
    dependencies=[Depends(require_dev_endpoint)],
)
def create_company(body: CompanyCreate, db: DbDep) -> Company:
    # TODO(auth): 가입·로그인 흐름에서 만든다. 지금은 개발용으로 열어 둔다.
    company = Company(id=new_id(), name=body.name, profile=body.profile.stored())
    db.add(company)
    db.commit()
    return company


@dev_router.get("/companies/profile-options", response_model=ProfileOptions, tags=["companies"])
def get_profile_options() -> ProfileOptions:
    """기업 정보 화면의 선택지(배출시설 종류). 인증 없이 부른다."""
    return profile_options()


@dev_router.get("/companies/me", response_model=CompanyOut, tags=["companies"])
def get_my_company(company: CompanyDep) -> Company:
    return company


@dev_router.put(
    "/companies/me/profile",
    response_model=CompanyOut,
    tags=["companies"],
    dependencies=[Depends(require_dev_endpoint)],
)
def update_profile(body: CompanyProfileUpdate, company: CompanyDep, db: DbDep) -> Company:
    company.profile = body.profile.stored()  # 이후 새로 만드는 건부터 적용
    db.commit()
    return company


# ---- 카탈로그 ----------------------------------------------------------------------------


@case_router.get("/catalog/facts", response_model=list[CatalogFact], tags=["catalog"])
def get_catalog_facts(kb: KBDep) -> list[CatalogFact]:
    """보드 편집·라벨용 사실 카탈로그 요약(카탈로그 순서). 내부 사실은 뺀다. 인증 없이 부른다."""
    out = []
    for fd in kb.catalog.values():
        if fd.internal:
            continue
        if fd.type == "enum":
            values = [
                CatalogValue(
                    value=v,
                    label=fd.value_labels.get(v, v),
                    parent_value=fd.value_parent.get(v) if fd.parent else None,
                )
                for v in fd.values or ()
            ]
        elif fd.type == "bool":
            values = [
                CatalogValue(value=True, label="예"),
                CatalogValue(value=False, label="아니오"),
            ]
        else:
            values = []
        out.append(
            CatalogFact(
                key=fd.key,
                label=fd.label or fd.question_hint or fd.key,
                type=fd.type,
                unit=fd.unit,
                values=values,
                parent=fd.parent,
            )
        )
    return out


# ---- 건 ----------------------------------------------------------------------------------


@case_router.post("/cases", response_model=CaseCreated, status_code=201, tags=["cases"])
def create_case(body: CaseCreate, svc: ServiceDep) -> CaseCreated:
    case, turn = _run(
        svc,
        svc.create_case,
        memo=body.memo,
        quantity=body.quantity,
        unit=body.unit,
        period=body.period,
        confirmed_facts=body.confirmed_facts,
        company_profile_version=body.company_profile_version,
    )
    _commit(svc)
    return CaseCreated(case=_case_out(svc, case), turn=turn)


@root_list_router.get("/cases", response_model=list[CaseOut], tags=["cases"])
def list_cases(
    svc: ServiceDep,
    response: Response,
    status: Annotated[CaseStatus | None, Query()] = None,
    page: Annotated[int | None, Query(ge=1)] = None,
    size: Annotated[int | None, Query(ge=1, le=MAX_PAGE_SIZE)] = None,
) -> list[CaseOut]:
    """참조 화면용: 기존처럼 배열을 돌려준다. page·size를 주면 그 쪽만 자른다
    (page만 주면 size=20). 전체 건수는 `X-Total-Count` 헤더."""
    if page is not None or size is not None:
        page, size = page or 1, size or DEFAULT_PAGE_SIZE
    cases, total = svc.list_cases(status, page=page, size=size)
    response.headers["X-Total-Count"] = str(total)
    return [_case_out(svc, c) for c in cases]


@internal_list_router.get("/cases", response_model=CaseListPage, tags=["cases"])
def list_cases_paged(
    svc: ServiceDep,
    status: Annotated[CaseStatus | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> CaseListPage:
    """서버용: `{items, pagingInfo}`. 최근 갱신순."""
    cases, total = svc.list_cases(status, page=page, size=size)
    return CaseListPage(
        items=[_case_out(svc, c) for c in cases],
        pagingInfo=PagingInfo(
            currentPageNumber=page,
            pageSize=size,
            totalCount=total,
            totalPages=-(-total // size),
        ),
    )


@case_router.get("/cases/{case_id}", response_model=CaseDetail, tags=["cases"])
def get_case(case_id: str, svc: ServiceDep) -> CaseDetail:
    case = _run(svc, svc.get_case, case_id)
    current = svc.repo.current_verdict(case.id)
    return CaseDetail(
        case=_case_out(svc, case),
        current_verdict=VerdictOut.model_validate(current) if current else None,
        verdicts=[VerdictOut.model_validate(v) for v in svc.repo.verdicts(case.id)],
        latest_turn=svc.latest_turn(case),
        documents=[_doc_out(svc, d) for d in svc.documents(case)],
        handoff=current.handoff if current else None,
        recycling=assess_recycling(svc.kb.recycling, current.handoff).model_dump(mode="json")
        if current and current.handoff
        else None,
        conversation=svc.conversation(case),
    )


# ---- 문진 --------------------------------------------------------------------------------


@case_router.post(
    "/cases/{case_id}/diagnosis/messages", response_model=TurnResponse, tags=["diagnosis"]
)
def post_message(case_id: str, body: MessageIn, svc: ServiceDep) -> TurnResponse:
    case = _run(svc, svc.get_case, case_id)
    resp = _run(
        svc,
        svc.message,
        case,
        text=body.text,
        quick_reply=body.quick_reply,
        confirmed_facts=body.confirmed_facts,
        company_profile_version=body.company_profile_version,
    )
    _commit(svc)
    return resp


DOCUMENT_UPLOAD_RESPONSES: dict[int | str, dict] = {
    413: {"model": ErrorResponse, "description": "파일이 너무 큼"},
    415: {"model": ErrorResponse, "description": "지원하지 않는 파일 형식"},
    422: {"model": ErrorResponse, "description": "facts 값 형식 오류: details.problems"},
}


def _read_upload(file: UploadFile, settings: Settings) -> bytes:
    data = file.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise api_error(413, f"파일이 너무 큽니다(최대 {settings.max_upload_bytes} bytes)")
    return data


@case_router.post(
    "/cases/{case_id}/documents",
    response_model=DocumentTurn,
    status_code=201,
    tags=["diagnosis"],
    responses=DOCUMENT_UPLOAD_RESPONSES,
)
def upload_document(
    case_id: str,
    svc: ServiceDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    facts: Annotated[str | None, Form()] = None,
) -> DocumentTurn:
    """서류 업로드. `facts`(JSON 객체)는 검수 대기 후보(UNVERIFIED)로만 저장한다(판정 불변).

    판정에 쓰려면 검수 뒤 `…/documents/{doc}/values/apply`로 적용한다.
    """
    # 일반 def로 둔다: 아래 서비스는 동기 DB 호출이라 async def 안에서 부르면
    # 그동안 서버의 다른 모든 요청이 멈춘다. def는 FastAPI가 스레드에서 실행한다.
    data = _read_upload(file, settings)
    case = _run(svc, svc.get_case, case_id)
    doc, turn, values = _run(
        svc,
        svc.upload_document,
        case,
        filename=file.filename or "document",
        content_type=file.content_type,
        data=data,
        manual_facts=facts,
    )
    _commit(svc)
    return DocumentTurn(
        document=_doc_out(svc, doc),
        turn=turn,
        values=[DocumentValueOut.model_validate(v) for v in values],
    )


@case_router.post(
    "/cases/{case_id}/documents/{document_id}/versions",
    response_model=DocumentTurn,
    status_code=201,
    tags=["diagnosis"],
    responses=DOCUMENT_UPLOAD_RESPONSES,
)
def replace_document(
    case_id: str,
    document_id: str,
    svc: ServiceDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    facts: Annotated[str | None, Form()] = None,
) -> DocumentTurn:
    """같은 서류의 파일 교체(새 버전). 이전 버전에서 적용된 값은 자동으로 효력이 해제된다."""
    data = _read_upload(file, settings)
    case = _run(svc, svc.get_case, case_id)
    doc, turn, values = _run(
        svc,
        svc.replace_document,
        case,
        document_id,
        filename=file.filename or "document",
        content_type=file.content_type,
        data=data,
        manual_facts=facts,
    )
    _commit(svc)
    return DocumentTurn(
        document=_doc_out(svc, doc),
        turn=turn,
        values=[DocumentValueOut.model_validate(v) for v in values],
    )


@case_router.post(
    "/cases/{case_id}/documents/{document_id}/values/apply",
    response_model=TurnResponse,
    tags=["diagnosis"],
)
def apply_document_values(
    case_id: str, document_id: str, body: ApplyIn, svc: ServiceDep
) -> TurnResponse:
    """검수 완료된 서류 값을 EVIDENCED로 적용하고 다시 평가한다(원문 대조 없음, 형식만 검사)."""
    case = _run(svc, svc.get_case, case_id)
    turn, _ = _run(svc, svc.apply_values, case, document_id, body.values)
    _commit(svc)
    return turn


@case_router.post(
    "/cases/{case_id}/documents/{document_id}/revoke",
    response_model=TurnResponse,
    tags=["diagnosis"],
)
def revoke_document(
    case_id: str, document_id: str, svc: ServiceDep, body: RevokeIn | None = None
) -> TurnResponse:
    """서류(또는 그 버전)에서 온 증빙의 효력을 해제하고 다시 평가한다. 이력은 남는다."""
    case = _run(svc, svc.get_case, case_id)
    turn, _ = _run(
        svc,
        svc.revoke_document,
        case,
        document_id,
        reason=body.reason if body else None,
        version=body.document_version if body else None,
    )
    _commit(svc)
    return turn


@case_router.post("/cases/{case_id}/rebase", response_model=TurnResponse, tags=["diagnosis"])
def rebase(case_id: str, svc: ServiceDep) -> TurnResponse:
    """저장된 규칙 버전이 바뀐 건(KB_CHANGED)을 지금 규칙으로 다시 평가한다. 확정 건은 409."""
    case = _run(svc, svc.get_case, case_id)
    turn = _run(svc, svc.rebase, case)
    _commit(svc)
    return turn


@case_router.post("/cases/{case_id}/confirm", response_model=ConfirmOut, tags=["diagnosis"])
def confirm(case_id: str, svc: ServiceDep, body: ConfirmIn | None = None) -> ConfirmOut:
    case = _run(svc, svc.get_case, case_id)
    verdict, frozen = _run(svc, svc.confirm, case, body.expected_code if body else None)
    _commit(svc)
    return ConfirmOut(
        case=_case_out(svc, case),
        verdict=VerdictOut.model_validate(verdict),
        handoff=verdict.handoff,
        frozen_trace_rows=frozen,
    )


@case_router.post("/cases/{case_id}/reopen", response_model=ReopenOut, tags=["diagnosis"])
def reopen(case_id: str, svc: ServiceDep, body: ReopenIn | None = None) -> ReopenOut:
    case = _run(svc, svc.get_case, case_id)
    old, turn = _run(svc, svc.reopen, case, body.reason if body else None)
    _commit(svc)
    return ReopenOut(
        case=_case_out(svc, case),
        superseded_verdict=VerdictOut.model_validate(old) if old else None,
        turn=turn,
    )


@case_router.get("/cases/{case_id}/trace", response_model=TraceOut, tags=["diagnosis"])
def get_trace(case_id: str, svc: ServiceDep) -> TraceOut:
    case = _run(svc, svc.get_case, case_id)
    sessions = [
        TraceSessionOut(
            session_id=rec.id,
            as_of=rec.as_of,
            kb_dir=rec.kb_dir,
            kb_version=rec.kb_version,
            table_versions=rec.table_versions,
            facts=svc.fact_rows(rec.id),
            turns=[TraceRowOut.model_validate(r) for r in rows],
        )
        for rec, rows in svc.trace_sessions(case)
    ]
    return TraceOut(
        case_id=case.id,
        sessions=sessions,
        verdicts=[VerdictOut.model_validate(v) for v in svc.repo.verdicts(case.id)],
    )


# ---- 기업 데이터 삭제 (CORP-009, /internal/v1 전용) -------------------------------------------


@company_data_router.delete(
    "/companies/{external_id}/data", response_model=DeletionOut, tags=["companies"]
)
def delete_company(external_id: str, db: DbDep) -> DeletionOut:
    """탈퇴한 기업의 데이터 삭제(멱등). 서버 기업 ID는 경로로 받는다(`X-Company-Id` 불필요)."""
    try:
        log = delete_company_data(db, external_id)
    except DeletionFailed as exc:
        raise api_error(
            500,
            "기업 데이터 삭제에 실패했습니다. 다시 시도하세요",
            "DELETION_FAILED",
            attempts=exc.log.attempts,
        ) from exc
    return DeletionOut.model_validate(log, from_attributes=True)


@company_data_router.get(
    "/companies/{external_id}/data/deletion", response_model=DeletionOut, tags=["companies"]
)
def get_company_deletion(external_id: str, db: DbDep) -> DeletionOut:
    """가장 최근 삭제 이력. 없으면 404 DELETION_NOT_FOUND."""
    log = latest_deletion(db, external_id)
    if log is None:
        raise api_error(404, "삭제 이력이 없습니다", "DELETION_NOT_FOUND")
    return DeletionOut.model_validate(log, from_attributes=True)
