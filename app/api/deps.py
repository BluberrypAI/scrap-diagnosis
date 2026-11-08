"""앱 상태(KB·LLM·DB)와 FastAPI 의존성.

KB·LLM·DB 엔진은 앱마다 한 번 만든다(처음 쓸 때 또는 시작 시). 테스트는 create_app 인자나
`app.dependency_overrides`로 SAMPLE KB·FakeLLMClient·임시 DB를 넣는다.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.agent.llm_client import LLMClient, make_client
from app.api.errors import api_error
from app.config import Settings, get_settings
from app.persistence.db import create_all, make_engine, make_sessionmaker
from app.persistence.models import Company, new_id
from app.rules.loader import load_kb
from app.rules.model import KnowledgeBase

_UNSET = object()
# 판정에 쓰이지 않는 하위 폴더(회귀 비교·시나리오)는 지문에서 뺀다.
KB_EXCLUDE_DIRS = frozenset({"regression", "scenarios"})


@dataclass(frozen=True)
class KBInfo:
    kb_dir: str
    version: str  # 규칙 데이터 파일 해시(재현용)
    table_versions: dict[str, str]


def kb_fingerprint(kb_dir: Path | None, kb: KnowledgeBase) -> str:
    """규칙 데이터 파일 전체의 sha256. 디렉터리가 없으면 테이블 id·버전으로 만든다."""
    h = hashlib.sha256()
    if kb_dir is not None and Path(kb_dir).is_dir():
        root = Path(kb_dir)
        files = [
            p
            for p in sorted(root.rglob("*.yaml"))
            if p.relative_to(root).parts[0] not in KB_EXCLUDE_DIRS
        ]
        for p in files:
            h.update(p.relative_to(root).as_posix().encode())
            h.update(b"\0")
            h.update(p.read_bytes())
    else:
        for t in kb.tables:
            h.update(f"{t.table_id}@{t.version}\n".encode())
    return h.hexdigest()[:16]


class AppContainer:
    def __init__(
        self,
        settings: Settings,
        *,
        kb: KnowledgeBase | None = None,
        kb_dir: Path | None = None,
        extractor_llm: LLMClient | None | object = _UNSET,
        responder_llm: LLMClient | None | object = _UNSET,
        engine: Engine | None = None,
        today: Callable[[], date] | None = None,
    ):
        # today: 법 기준일(as_of)을 고정할 때만(테스트). 주지 않으면 대화 시작 시각의 서울 날짜.
        self.settings = settings
        self._kb = kb
        self.kb_dir = Path(kb_dir) if kb_dir is not None else Path(settings.kb_dir)
        self._extractor_llm = extractor_llm
        self._responder_llm = responder_llm
        self._engine = engine
        self.today = today

    @cached_property
    def kb(self) -> KnowledgeBase:
        return self._kb if self._kb is not None else load_kb(self.kb_dir)

    @cached_property
    def kb_info(self) -> KBInfo:
        kb = self.kb
        return KBInfo(
            kb_dir=self.kb_dir.as_posix(),
            version=kb_fingerprint(self.kb_dir, kb),
            table_versions={t.table_id: t.version for t in kb.tables},
        )

    @cached_property
    def _default_llm(self) -> LLMClient | None:
        return make_client(self.settings)

    @property
    def extractor_llm(self) -> LLMClient | None:
        if self._extractor_llm is _UNSET:
            return self._default_llm
        return self._extractor_llm  # type: ignore[return-value]

    @property
    def responder_llm(self) -> LLMClient | None:
        if self._responder_llm is _UNSET:
            return self._default_llm
        return self._responder_llm  # type: ignore[return-value]

    @cached_property
    def engine(self) -> Engine:
        engine = self._engine or make_engine(self.settings.database_url)
        if self.settings.db_create_all:
            create_all(engine)
        return engine

    @cached_property
    def sessionmaker(self) -> sessionmaker[Session]:
        return make_sessionmaker(self.engine)

    def warmup(self) -> None:
        _ = self.kb_info, self.sessionmaker


# ---- 의존성 ------------------------------------------------------------------------------


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


ContainerDep = Annotated[AppContainer, Depends(get_container)]


def get_db(c: ContainerDep) -> Iterator[Session]:
    with c.sessionmaker() as db:
        yield db


def get_kb(c: ContainerDep) -> KnowledgeBase:
    return c.kb


def get_kb_info(c: ContainerDep) -> KBInfo:
    return c.kb_info


@dataclass
class LLMs:
    extractor: LLMClient | None
    responder: LLMClient | None


def get_llms(c: ContainerDep) -> LLMs:
    return LLMs(extractor=c.extractor_llm, responder=c.responder_llm)


def get_today(c: ContainerDep) -> date | None:
    """고정한 법 기준일(테스트용). None이면 서비스가 대화 시작 시각의 Asia/Seoul 날짜를 쓴다."""
    return c.today() if c.today is not None else None


def get_settings_dep(request: Request) -> Settings:
    c = getattr(request.app.state, "container", None)
    return c.settings if c is not None else get_settings()


DbDep = Annotated[Session, Depends(get_db)]


INTERNAL_PREFIX = "/internal/v1"


def is_internal(request: Request) -> bool:
    return request.url.path.startswith(INTERNAL_PREFIX + "/")


def require_service_auth(
    request: Request,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """/internal/v1 서비스 인증: `Authorization: Bearer <ENGINE_SERVICE_TOKEN>`.

    - 토큰을 설정했으면 dev·prod 모두 요구한다(상수 시간 비교).
    - 토큰이 없고 prod면 모든 내부 호출을 거절한다(설정 누락으로 열리지 않게).
    - 토큰이 없고 dev면 통과한다(로컬 개발 편의).
    """
    expected = settings.engine_service_token
    if not expected:
        if settings.app_env == "prod":
            raise api_error(
                401, "서비스 토큰이 설정되지 않아 내부 API를 쓸 수 없습니다", "AUTH_REQUIRED"
            )
        return
    scheme, _, given = (authorization or "").partition(" ")
    ok = scheme.lower() == "bearer" and hmac.compare_digest(
        given.strip().encode(), expected.encode()
    )
    if not ok:
        raise api_error(
            401,
            "서비스 토큰이 없거나 올바르지 않습니다",
            "AUTH_REQUIRED",
        )


def require_dev_endpoint(settings: SettingsDep) -> None:
    """개발용 엔드포인트(기업 생성·수정): prod에서는 없는 것처럼 404."""
    if settings.app_env == "prod":
        raise api_error(404, "사용할 수 없는 경로입니다", "ENDPOINT_DISABLED")


def _provision_company(db: Session, external_id: str) -> Company:
    """서버 기업 ID를 처음 보면 최소 내부 레코드를 만든다(동시 첫 호출은 유일 제약으로 합친다)."""
    company = db.scalars(select(Company).where(Company.external_id == external_id)).first()
    if company is not None:
        return company
    company = Company(id=new_id(), name=f"기업 {external_id}", external_id=external_id, profile={})
    db.add(company)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        company = db.scalars(select(Company).where(Company.external_id == external_id)).one()
    return company


def current_company(
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    x_company_id: Annotated[str | None, Header()] = None,
) -> Company:
    """기업 격리.

    - `/internal/v1`: 서비스 토큰이 확인된 요청에서만 `X-Company-Id`(서버 기업 ID)를 믿는다.
      처음 보는 ID는 자동 생성한다.
    - 루트 경로(참조 화면·개발용): `X-Company-Id`는 개발용 기업(POST /companies) id.
      prod에서는 헤더만으로 접근할 수 없으므로 막는다.
    """
    if is_internal(request):
        require_service_auth(request, settings, request.headers.get("authorization"))
        if not x_company_id:
            raise api_error(400, "X-Company-Id 헤더가 필요합니다", "COMPANY_REQUIRED")
        return _provision_company(db, x_company_id)
    if settings.app_env == "prod":
        raise api_error(404, "사용할 수 없는 경로입니다", "ENDPOINT_DISABLED")
    if not x_company_id:
        raise api_error(401, "X-Company-Id 헤더가 필요합니다", "COMPANY_REQUIRED")
    company = db.get(Company, x_company_id)
    if company is None:
        raise api_error(401, "알 수 없는 기업입니다", "COMPANY_REQUIRED")
    return company


CompanyDep = Annotated[Company, Depends(current_company)]
KBDep = Annotated[KnowledgeBase, Depends(get_kb)]
KBInfoDep = Annotated[KBInfo, Depends(get_kb_info)]
LLMsDep = Annotated[LLMs, Depends(get_llms)]
TodayDep = Annotated[date | None, Depends(get_today)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
