"""HTTP 라우터 (md 11절). 비즈니스 로직은 service.py에 있다."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.api.deps import (
    CompanyDep,
    DbDep,
    KBDep,
    KBInfoDep,
    LLMsDep,
    SettingsDep,
    TodayDep,
)
from app.api.documents import UnsupportedDocument
from app.api.errors import ERROR_RESPONSES, ErrorResponse, api_error
from app.api.profile import ProfileOptions, profile_options
from app.api.schemas import (
    CaseCreate,
    CaseCreated,
    CaseDetail,
    CaseOut,
    CatalogFact,
    CatalogValue,
    CompanyCreate,
    CompanyOut,
    CompanyProfileUpdate,
    ConfirmIn,
    ConfirmOut,
    DocumentOut,
    DocumentTurn,
    MessageIn,
    ReopenIn,
    ReopenOut,
    TraceOut,
    TraceRowOut,
    TraceSessionOut,
    VerdictOut,
)
from app.api.service import CaseService, ServiceError
from app.domain.case import CaseStatus
from app.domain.verdict import TurnResponse
from app.persistence.models import Company, WasteCase, new_id

router = APIRouter(responses=ERROR_RESPONSES)
STALE_MESSAGE = "다른 요청이 같은 문진을 먼저 갱신했습니다. 다시 시도하세요"


def get_service(
    db: DbDep,
    kb: KBDep,
    kb_info: KBInfoDep,
    llms: LLMsDep,
    settings: SettingsDep,
    today: TodayDep,
    company: CompanyDep,
) -> CaseService:
    """요청 하나 = DB 트랜잭션 하나. 커밋하지 않고 끝나면 세션을 닫으면서 되돌린다."""
    return CaseService(db, kb, kb_info, llms, settings, today, company)


ServiceDep = Annotated[CaseService, Depends(get_service)]


def _commit(svc: CaseService) -> None:
    try:
        svc.db.commit()
    except (StaleDataError, IntegrityError) as exc:
        # 같은 세션에 동시 요청: revision(낙관적 잠금) 또는 (session_id, seq) 유일 제약 충돌
        svc.db.rollback()
        raise api_error(409, STALE_MESSAGE) from exc


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
        }
    )


def _run(svc: CaseService, fn, *args, **kwargs):  # noqa: ANN001, ANN202
    try:
        return fn(*args, **kwargs)
    except ServiceError as exc:
        svc.db.rollback()
        raise api_error(exc.status, exc.message, **exc.extra) from exc
    except UnsupportedDocument as exc:
        svc.db.rollback()
        raise api_error(415, str(exc)) from exc
    except (StaleDataError, IntegrityError) as exc:
        svc.db.rollback()
        raise api_error(409, STALE_MESSAGE) from exc


# ---- 기업 (개발용 최소 API) --------------------------------------------------------------


@router.post("/companies", response_model=CompanyOut, status_code=201, tags=["companies"])
def create_company(body: CompanyCreate, db: DbDep) -> Company:
    # TODO(auth): 가입·로그인 흐름에서 만든다. 지금은 개발용으로 열어 둔다.
    company = Company(id=new_id(), name=body.name, profile=body.profile.stored())
    db.add(company)
    db.commit()
    return company


@router.get("/companies/profile-options", response_model=ProfileOptions, tags=["companies"])
def get_profile_options() -> ProfileOptions:
    """기업 정보 화면의 선택지(배출시설 종류). 인증 없이 부른다."""
    return profile_options()


@router.get("/companies/me", response_model=CompanyOut, tags=["companies"])
def get_my_company(company: CompanyDep) -> Company:
    return company


@router.put("/companies/me/profile", response_model=CompanyOut, tags=["companies"])
def update_profile(body: CompanyProfileUpdate, company: CompanyDep, db: DbDep) -> Company:
    company.profile = body.profile.stored()  # 이후 새로 만드는 건부터 적용
    db.commit()
    return company


# ---- 카탈로그 ----------------------------------------------------------------------------


@router.get("/catalog/facts", response_model=list[CatalogFact], tags=["catalog"])
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


@router.post("/cases", response_model=CaseCreated, status_code=201, tags=["cases"])
def create_case(body: CaseCreate, svc: ServiceDep) -> CaseCreated:
    case, turn = _run(
        svc,
        svc.create_case,
        memo=body.memo,
        quantity=body.quantity,
        unit=body.unit,
        period=body.period,
    )
    _commit(svc)
    return CaseCreated(case=_case_out(svc, case), turn=turn)


@router.get("/cases", response_model=list[CaseOut], tags=["cases"])
def list_cases(
    svc: ServiceDep, status: Annotated[CaseStatus | None, Query()] = None
) -> list[CaseOut]:
    return [_case_out(svc, c) for c in svc.list_cases(status)]


@router.get("/cases/{case_id}", response_model=CaseDetail, tags=["cases"])
def get_case(case_id: str, svc: ServiceDep) -> CaseDetail:
    case = _run(svc, svc.get_case, case_id)
    current = svc.repo.current_verdict(case.id)
    return CaseDetail(
        case=_case_out(svc, case),
        current_verdict=VerdictOut.model_validate(current) if current else None,
        verdicts=[VerdictOut.model_validate(v) for v in svc.repo.verdicts(case.id)],
        latest_turn=svc.latest_turn(case),
        documents=[DocumentOut.model_validate(d) for d in svc.documents(case)],
        handoff=current.handoff if current else None,
        conversation=svc.conversation(case),
    )


# ---- 문진 --------------------------------------------------------------------------------


@router.post("/cases/{case_id}/diagnosis/messages", response_model=TurnResponse, tags=["diagnosis"])
def post_message(case_id: str, body: MessageIn, svc: ServiceDep) -> TurnResponse:
    case = _run(svc, svc.get_case, case_id)
    resp = _run(svc, svc.message, case, text=body.text, quick_reply=body.quick_reply)
    _commit(svc)
    return resp


@router.post(
    "/cases/{case_id}/documents",
    response_model=DocumentTurn,
    status_code=201,
    tags=["diagnosis"],
    responses={
        413: {"model": ErrorResponse, "description": "파일이 너무 큼"},
        415: {"model": ErrorResponse, "description": "지원하지 않는 파일 형식"},
        422: {"description": "facts(JSON) 값 오류: detail.message + detail.problems"},
    },
)
def upload_document(
    case_id: str,
    svc: ServiceDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    facts: Annotated[str | None, Form()] = None,
) -> DocumentTurn:
    # 일반 def로 둔다: 아래 서비스는 동기 DB·AI 호출이라 async def 안에서 부르면
    # 그동안 서버의 다른 모든 요청이 멈춘다. def는 FastAPI가 스레드에서 실행한다.
    data = file.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise api_error(413, f"파일이 너무 큽니다(최대 {settings.max_upload_bytes} bytes)")
    case = _run(svc, svc.get_case, case_id)
    doc, turn = _run(
        svc,
        svc.upload_document,
        case,
        filename=file.filename or "document",
        content_type=file.content_type,
        data=data,
        manual_facts=facts,
    )
    _commit(svc)
    return DocumentTurn(document=DocumentOut.model_validate(doc), turn=turn)


@router.post("/cases/{case_id}/confirm", response_model=ConfirmOut, tags=["diagnosis"])
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


@router.post("/cases/{case_id}/reopen", response_model=ReopenOut, tags=["diagnosis"])
def reopen(case_id: str, svc: ServiceDep, body: ReopenIn | None = None) -> ReopenOut:
    case = _run(svc, svc.get_case, case_id)
    old, turn = _run(svc, svc.reopen, case, body.reason if body else None)
    _commit(svc)
    return ReopenOut(
        case=_case_out(svc, case),
        superseded_verdict=VerdictOut.model_validate(old) if old else None,
        turn=turn,
    )


@router.get("/cases/{case_id}/trace", response_model=TraceOut, tags=["diagnosis"])
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
