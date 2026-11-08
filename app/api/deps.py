"""앱 상태(KB·LLM·DB)와 FastAPI 의존성.

KB·LLM·DB 엔진은 앱마다 한 번 만든다(처음 쓸 때 또는 시작 시). 테스트는 create_app 인자나
`app.dependency_overrides`로 SAMPLE KB·FakeLLMClient·임시 DB를 넣는다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.agent.llm_client import LLMClient, make_client
from app.api.errors import api_error
from app.config import Settings, get_settings
from app.persistence.db import create_all, make_engine, make_sessionmaker
from app.persistence.models import Company
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


def current_company(
    db: DbDep,
    x_company_id: Annotated[str | None, Header()] = None,
) -> Company:
    """임시 기업 격리: X-Company-Id 헤더.

    TODO(auth): 로그인 토큰에서 사용자·기업을 꺼내고, 세부 권한(계정별 역할)을 적용한다.
    """
    if not x_company_id:
        raise api_error(401, "X-Company-Id 헤더가 필요합니다")
    company = db.get(Company, x_company_id)
    if company is None:
        raise api_error(401, "알 수 없는 기업입니다")
    return company


CompanyDep = Annotated[Company, Depends(current_company)]
KBDep = Annotated[KnowledgeBase, Depends(get_kb)]
KBInfoDep = Annotated[KBInfo, Depends(get_kb_info)]
LLMsDep = Annotated[LLMs, Depends(get_llms)]
TodayDep = Annotated[date | None, Depends(get_today)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
