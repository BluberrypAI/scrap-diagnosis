"""HTTP 라우터 (md 11절). 비즈니스 로직은 service.py에 있다."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
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
from app.api.schemas import (
    CaseCreate,
    CaseCreated,
    CaseDetail,
    CaseOut,
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

router = APIRouter()
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
        raise HTTPException(409, STALE_MESSAGE) from exc


def _case_out(svc: CaseService, case: WasteCase) -> CaseOut:
    return CaseOut.model_validate(
        {
            "id": case.id,
            "company_id": case.company_id,
            "memo": case.memo,
            "quantity": case.quantity,
            "unit": case.unit,
            "period": case.period,
            "status": case.status,
            "session_id": svc.session_id_of(case),
            "created_at": case.created_at,
            "updated_at": case.updated_at,
        }
    )


def _run(svc: CaseService, fn, *args, **kwargs):  # noqa: ANN001, ANN202
    try:
        return fn(*args, **kwargs)
    except ServiceError as exc:
        svc.db.rollback()
        raise HTTPException(exc.status, {"message": exc.message, **exc.extra}) from exc
    except UnsupportedDocument as exc:
        svc.db.rollback()
        raise HTTPException(415, str(exc)) from exc
    except (StaleDataError, IntegrityError) as exc:
        svc.db.rollback()
        raise HTTPException(409, STALE_MESSAGE) from exc


# ---- 기업 (개발용 최소 API) --------------------------------------------------------------


@router.post("/companies", response_model=CompanyOut, status_code=201, tags=["companies"])
def create_company(body: CompanyCreate, db: DbDep) -> Company:
    # TODO(auth): 가입·로그인 흐름에서 만든다. 지금은 개발용으로 열어 둔다.
    company = Company(id=new_id(), name=body.name, profile=body.profile)
    db.add(company)
    db.commit()
    return company


@router.get("/companies/me", response_model=CompanyOut, tags=["companies"])
def get_my_company(company: CompanyDep) -> Company:
    return company


@router.put("/companies/me/profile", response_model=CompanyOut, tags=["companies"])
def update_profile(body: CompanyProfileUpdate, company: CompanyDep, db: DbDep) -> Company:
    company.profile = body.profile  # 이후 새로 만드는 건부터 적용
    db.commit()
    return company


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
    )


# ---- 문진 --------------------------------------------------------------------------------


@router.post("/cases/{case_id}/diagnosis/messages", response_model=TurnResponse, tags=["diagnosis"])
def post_message(case_id: str, body: MessageIn, svc: ServiceDep) -> TurnResponse:
    case = _run(svc, svc.get_case, case_id)
    resp = _run(svc, svc.message, case, text=body.text, quick_reply=body.quick_reply)
    _commit(svc)
    return resp


@router.post(
    "/cases/{case_id}/documents", response_model=DocumentTurn, status_code=201, tags=["diagnosis"]
)
async def upload_document(
    case_id: str,
    svc: ServiceDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    facts: Annotated[str | None, Form()] = None,
) -> DocumentTurn:
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"파일이 너무 큽니다(최대 {settings.max_upload_bytes} bytes)")
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
