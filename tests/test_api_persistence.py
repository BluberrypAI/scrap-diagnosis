"""세션 저장·복원(DiagnosisSession ↔ DB 행)과 Alembic 마이그레이션."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.agent.orchestrator import DiagnosisSession, QuickReply
from app.persistence.models import Base, DiagnosisSessionRecord
from app.persistence.repository import SessionRepository
from tests.api_support import PROFILE, Api, build_app, fake_llm
from tests.conftest import AS_OF

ROOT_INI = str(Path(__file__).resolve().parents[1] / "alembic.ini")

# (quick_reply dict | text) 순서. LLM 없이도 선택지 라벨 텍스트는 직전 질문 기준으로 받는다.
SCRIPT: list[dict | str] = [
    {"key": "material", "value": "PP"},
    {"key": "form", "value": "FILM"},
    "모두 해당 없음",  # 묶음 질문 라벨 → last_question이 복원돼야 받는다
    "5% 미만",  # 유분 구간 라벨
    {"key": "__evidence__", "value": "refused"},
]


def _comparable(t: dict) -> dict:
    t = json.loads(json.dumps(t))
    t.pop("turn_id")
    # 판정 보드의 기록 시각은 실행마다 다르다(나머지는 같아야 한다)
    for f in (t["ui"].get("board") or {}).get("facts", []):
        f.pop("recorded_at", None)
    return t


def _in_memory(kb) -> list[dict]:
    s = DiagnosisSession(kb, case_id="c", session_id="s", as_of=AS_OF)
    s.seed({k: v for k, v in PROFILE["facts"].items() if k in kb.catalog})
    out = [s.start().model_dump(mode="json")]
    for step in SCRIPT:
        if isinstance(step, dict):
            r = s.handle(quick_reply=QuickReply(**step))
        else:
            r = s.handle(text=step)
        out.append(r.model_dump(mode="json"))
    return out


def _strip_ids(t: dict) -> dict:
    t = _comparable(t)
    t.pop("case_id")
    t.pop("session_id")
    return t


def test_orchestrator_state_roundtrip(kb):
    """to_state → JSON → from_state 뒤에도 같은 입력에 같은 응답을 낸다."""
    a = DiagnosisSession(kb, case_id="c", as_of=AS_OF)
    a.seed({"material": "PP"})
    a.start()
    a.handle(quick_reply=QuickReply(key="form", value="FILM"))
    state = json.loads(json.dumps(a.to_state(), ensure_ascii=False))
    b = DiagnosisSession.from_state(kb, state)
    assert b.store.history == a.store.history
    assert b.state == a.state and b.last_question == a.last_question
    assert b.messages == a.messages and len(b.traces) == len(a.traces)
    ra = a.handle(text="모두 해당 없음")
    rb = b.handle(text="모두 해당 없음")
    assert _comparable(ra.model_dump()) == _comparable(rb.model_dump())
    assert a.peek().decision == b.peek().decision
    assert len(a.store.history) == len(b.store.history)  # peek은 사실을 바꾸지 않는다


def test_session_survives_reload_and_matches_in_memory(kb, tmp_path):
    """요청마다 DB 행에서 세션을 다시 만든다. 앱을 새로 띄워도 이어서 같은 결과를 낸다."""
    db_path = tmp_path / "reload.db"
    expected = _in_memory(kb)

    def new_api() -> Api:
        app = build_app(kb, db_path, extractor=None)  # LLM 없음: 라벨 일치만 받는다
        return Api(client=TestClient(app), app=app, llm=None, db_path=db_path)

    api = new_api()
    api.use(api.company())
    created = api.create_case()
    cid = created["case"]["id"]
    got = [created["turn"]]
    for i, step in enumerate(SCRIPT):
        if i == 2:  # 중간에 앱(컨테이너·엔진)을 통째로 다시 만든다
            headers = api.headers
            api = new_api()
            api.headers = headers
        if isinstance(step, dict):
            got.append(api.reply(cid, step["key"], step.get("value"), step.get("kind", "value")))
        else:
            got.append(api.say(cid, step))

    assert [_strip_ids(t) for t in got] == [_strip_ids(t) for t in expected]
    assert got[-1]["branch"] == "UNSUPPORTED" and got[-1]["case_status"] == "NEEDS_INFO"
    trace = api.get(f"/cases/{cid}/trace").json()["sessions"][0]
    assert [t["seq"] for t in trace["turns"]] == list(range(len(SCRIPT) + 1))


def test_alembic_migration_matches_models(tmp_path):
    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    cfg = Config(ROOT_INI)
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], diff
    assert set(inspect(engine).get_table_names()) >= set(Base.metadata.tables)
    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()


def test_api_works_on_migrated_db(kb, tmp_path):
    """create_all 없이 alembic으로 만든 스키마에서도 API가 돈다."""
    db_path = tmp_path / "migrated.db"
    cfg = Config(ROOT_INI)
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(cfg, "head")
    app = build_app(kb, db_path, fake_llm())
    app.state.container.settings.db_create_all = False
    api = Api(client=TestClient(app), app=app, llm=None, db_path=db_path)
    api.use(api.company())
    cid = api.create_case()["case"]["id"]
    assert api.reply(cid, "material", "PP")["branch"] == "ASK_FACT"


def test_concurrent_turns_on_same_session_conflict(kb, tmp_path):
    """같은 세션을 두 요청이 동시에 이어 쓰면 뒤의 것은 실패한다(낙관적 잠금 → API 409)."""
    db_path = tmp_path / "race.db"
    app = build_app(kb, db_path, extractor=None)
    api = Api(client=TestClient(app), app=app, llm=None, db_path=db_path)
    api.use(api.company())
    sid = api.create_case()["case"]["session_id"]
    maker = app.state.container.sessionmaker
    with maker() as db1, maker() as db2:
        l1 = SessionRepository(db1, kb).load(db1.get(DiagnosisSessionRecord, sid))
        l2 = SessionRepository(db2, kb).load(db2.get(DiagnosisSessionRecord, sid))
        for db, ls, v in ((db1, l1, "PP"), (db2, l2, "PE")):
            ls.session.handle(quick_reply=QuickReply(key="material", value=v))
            SessionRepository(db, kb).save(ls)
        db1.commit()
        with pytest.raises((StaleDataError, IntegrityError)):
            db2.commit()
