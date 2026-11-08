"""코드 없는 결론 확정, 경로추천 AI 인계 객체(diagnosis-handoff-v1), 시각 기록.

계약: docs/handoff-contract.md
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta

import pytest
import yaml
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.agent.guard import validate_response
from app.agent.orchestrator import DiagnosisSession
from app.agent.responder import build_payload
from app.agent.router import Branch
from app.agent.templates import OUTCOME_TEXT
from app.domain.handoff import ACTIONS, CONTRACT, OUTCOMES, REQUIRED_GUIDANCE
from app.main import create_app
from app.rules.loader import RuleDataError, build_kb, load_kb
from tests.api_support import Api, build_app, fake_llm, make_settings
from tests.conftest import AS_OF, DATA, REAL
from tests.test_api import assert_turn_contract, finish_with_document
from tests.test_api_persistence import ROOT_INI

# 계약 표(docs/handoff-contract.md): result_type/outcome → route_guidance.action
CONTRACT_ACTIONS = {
    ("WASTE_CODE", None): "RECOMMEND_ROUTE",
    ("NO_CODE", "NOT_WASTE"): "NO_ROUTE_NEEDED",
    ("NO_CODE", "CIRCULAR_RESOURCE"): "NO_ROUTE_NEEDED",
    ("NO_CODE", "EXCLUDED"): "REFER_OTHER_LAW",
    ("NO_CODE", "HOUSEHOLD"): "REFER_MUNICIPALITY",
    ("NO_CODE", "INTERPRETATION_NEEDED"): "REFER_AUTHORITY",
    ("NO_CODE", "CODE_NEEDS_TEST"): "NEEDS_TEST",
    ("NO_CODE", "NO_GENERAL_CODE"): "MANUAL_CLASSIFICATION",
    ("NO_CODE", "NO_MIXTURE_RULE"): "MANUAL_CLASSIFICATION",
}
HANDOFF_KEYS = {
    "contract",
    "case_id",
    "verdict_version",
    "result_type",
    "waste_code",
    "waste_name",
    "category",
    "outcome",
    "route_guidance",
    "facts",
    "evidence",
    "basis",
    "review",
    "timestamps",
    "kb",
}
# 실제 KB: 아직 공정에서 쓰는 PP → 폐기물 아님(코드 없는 결론)
NOT_WASTE_FACTS = {
    "emission_facility": True,
    "material": "pp",
    "material_fate": "still_used",
    "circular_resource_recognized": False,
}


def _seoul(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    assert dt.utcoffset() == timedelta(hours=9), ts  # Asia/Seoul
    return dt


# ---- 안내 데이터 파일 --------------------------------------------------------------------


@pytest.mark.parametrize("kb_name", ["kb", "real_kb"])
def test_guidance_file_matches_contract_table(request, kb_name):
    kb = request.getfixturevalue(kb_name)
    assert set(kb.guidance) == set(REQUIRED_GUIDANCE) == set(CONTRACT_ACTIONS)
    for key, g in kb.guidance.items():
        assert g.action == CONTRACT_ACTIONS[key], key
        assert g.summary.strip() and all(isinstance(n, str) for n in g.notes)
    # 실제 규칙에 쓰인 모든 outcome에 안내가 있다
    used = {r.then.outcome for t in kb.tables for r in t.rules if r.then.code is None}
    assert used <= set(OUTCOMES)


def test_sample_and_real_guidance_tables_are_the_same():
    def table(d):
        return yaml.safe_load((d / "outcome_guidance.yaml").read_text(encoding="utf-8"))

    assert table(DATA) == table(REAL)


def _kb_copy(tmp_path, edit):  # noqa: ANN001, ANN202
    d = tmp_path / "kb"
    shutil.copytree(DATA, d)
    path = d / "outcome_guidance.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    edit(raw)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return d


def test_missing_outcome_entry_fails_loudly(tmp_path):
    def drop(raw):  # noqa: ANN001
        raw["guidance"] = [g for g in raw["guidance"] if g["outcome"] != "NOT_WASTE"]

    d = _kb_copy(tmp_path, drop)
    with pytest.raises(RuleDataError, match="NOT_WASTE"):
        load_kb(d)
    # 서버도 시작할 때 KB를 읽으므로 바로 실패한다
    app = create_app(make_settings(tmp_path / "x.db"), kb_dir=d, extractor_llm=None)
    with pytest.raises(RuleDataError), TestClient(app):
        pass


def test_missing_guidance_file_fails(tmp_path):
    d = tmp_path / "kb"
    shutil.copytree(DATA, d)
    (d / "outcome_guidance.yaml").unlink()
    with pytest.raises(RuleDataError, match="outcome_guidance"):
        load_kb(d)


@pytest.mark.parametrize(
    "edit",
    [
        lambda raw: raw["guidance"][1].update(action="SHIP_IT"),
        lambda raw: raw["guidance"][1].update(outcome="SOMETHING_NEW"),
        lambda raw: raw["guidance"][0].update(outcome="NOT_WASTE"),  # WASTE_CODE는 outcome null
        lambda raw: raw["guidance"][1].update(summary=""),
        lambda raw: raw["guidance"][1].update(extra=1),
        lambda raw: raw["guidance"].append(dict(raw["guidance"][1])),  # 중복
    ],
)
def test_invalid_guidance_entries_rejected(tmp_path, edit):
    with pytest.raises(RuleDataError):
        load_kb(_kb_copy(tmp_path, edit))


def test_rule_outcome_without_guidance_fails():
    guidance = yaml.safe_load((DATA / "outcome_guidance.yaml").read_text(encoding="utf-8"))
    catalog = [{"key": "a", "type": "bool", "question_hint": "a"}]
    table = {
        "table_id": "t",
        "version": "1",
        "hit_policy": "PRIORITY",
        "rules": [
            {
                "rule_id": "R1",
                "priority": 1,
                "when": {"fact": "a", "op": "eq", "value": True},
                "then": {"outcome": "BRAND_NEW_OUTCOME"},
            }
        ],
    }
    with pytest.raises(RuleDataError, match="BRAND_NEW_OUTCOME"):
        build_kb(catalog, [table], guidance=guidance)
    assert set(ACTIONS) >= {g["action"] for g in guidance["guidance"]}


# ---- 라우터·응답 -------------------------------------------------------------------------


def test_code_less_conclusion_is_final_review(real_kb):
    s = DiagnosisSession(real_kb, as_of=AS_OF)
    s.seed(NOT_WASTE_FACTS)
    r = s.start()
    assert r.branch == "FINAL_REVIEW" and r.case_status == "DIAGNOSING"
    v = r.verdict
    assert v.status == "CONFIRMABLE" and v.waste_code is None and v.waste_name is None
    assert v.outcome == "NOT_WASTE" and v.failure_reason is None and v.rationale
    assert r.ui.can_confirm and r.ui.suggested_replies == ["확정", "다시 확인할게요"]
    # 템플릿 문구: 결론 + 확정 후 다음 단계 안내 + 참고 판정
    assert OUTCOME_TEXT["NOT_WASTE"] in r.message
    assert "다음 단계" in r.message and "UNVERIFIED" in r.message

    step = s.last_step
    payload = build_payload(real_kb, step, s.rule_index)
    assert payload["verdict"]["code"] is None and payload["verdict"]["outcome"] == "NOT_WASTE"
    assert payload["verdict"]["conclusion"] == OUTCOME_TEXT["NOT_WASTE"] and payload["next_step"]
    text_ = json.dumps(payload, ensure_ascii=False)
    basis_ids = {b["id"] for b in payload["basis"]}
    assert validate_response(r.message, ["B1"], payload, text_, basis_ids) == []
    # 판정에 없는 번호를 말하면 guard가 막는다
    assert validate_response("분류번호는 51-03-01입니다.", [], payload, text_, basis_ids)


def test_every_outcome_has_conclusion_text():
    assert set(OUTCOME_TEXT) == set(OUTCOMES)


def test_undecided_stays_unsupported(kb):
    s = DiagnosisSession(kb, as_of=AS_OF)
    s.seed({"material": "OTHER"})  # 샘플 KB에 테이블 없음
    r = s.start()
    assert r.branch == "UNSUPPORTED" and r.verdict.failure_reason == "NO_TABLE"
    assert not r.ui.can_confirm and r.verdict.outcome is None
    assert s.last_step.decision.branch == Branch.UNSUPPORTED


# ---- API: 확정·인계 객체 ----------------------------------------------------------------


@pytest.fixture
def api(kb, tmp_path) -> Api:
    llm = fake_llm()
    app = build_app(kb, tmp_path / "api.db", llm)
    a = Api(client=TestClient(app), app=app, llm=llm, db_path=tmp_path / "api.db")
    return a.use(a.company())


@pytest.fixture
def real_api(real_kb, tmp_path) -> Api:
    app = build_app(real_kb, tmp_path / "real.db", fake_llm())
    a = Api(client=TestClient(app), app=app, llm=None, db_path=tmp_path / "real.db")
    return a.use(a.company(profile={"facts": NOT_WASTE_FACTS}))


def assert_handoff_contract(h: dict) -> None:
    assert set(h) == HANDOFF_KEYS
    assert h["contract"] == CONTRACT
    assert h["result_type"] in {"WASTE_CODE", "NO_CODE"}
    assert set(h["route_guidance"]) == {"action", "summary", "notes"}
    assert h["route_guidance"]["action"] in ACTIONS
    for f in h["facts"].values():
        assert set(f) == {"value", "status", "source_type"} and f["value"] is not None
    for e in h["evidence"]:
        assert set(e) == {"fact", "document_id"}
    assert [b["id"] for b in h["basis"]] == [f"B{i}" for i in range(1, len(h["basis"]) + 1)]
    for b in h["basis"]:
        assert set(b) == {"id", "type", "ref", "excerpt"}
    assert h["review"] == "UNVERIFIED"
    assert set(h["timestamps"]) == {"diagnosis_started_at", "confirmed_at", "as_of"}
    started = _seoul(h["timestamps"]["diagnosis_started_at"])
    confirmed = _seoul(h["timestamps"]["confirmed_at"])
    assert started <= confirmed
    date.fromisoformat(h["timestamps"]["as_of"])
    assert set(h["kb"]) == {"kb_version", "table_id", "table_version"} and h["kb"]["kb_version"]


def test_code_less_confirm_via_api(real_api, real_kb):
    body = real_api.create_case(memo=None)
    cid, turn = body["case"]["id"], body["turn"]
    assert_turn_contract(turn, cid)
    assert turn["branch"] == "FINAL_REVIEW" and turn["ui"]["can_confirm"]
    assert turn["verdict"]["waste_code"] is None and turn["verdict"]["outcome"] == "NOT_WASTE"
    assert turn["case_status"] == "DIAGNOSING"

    # 코드 없는 결론에 분류번호를 기대하면 409, 사유로는 통과
    bad = real_api.post(f"/cases/{cid}/confirm", json={"expected_code": "51-03-01"})
    assert bad.status_code == 409
    assert bad.json()["detail"]["server_code"] is None
    assert bad.json()["detail"]["server_outcome"] == "NOT_WASTE"
    r = real_api.post(f"/cases/{cid}/confirm", json={"expected_code": "NOT_WASTE"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["case"]["status"] == "CODE_CONFIRMED"
    v = out["verdict"]
    assert v["result_type"] == "NO_CODE" and v["code"] is None and v["name"] is None
    assert v["outcome"] == "NOT_WASTE" and v["verdict"]["outcome"] == "NOT_WASTE"

    h = out["handoff"]
    assert_handoff_contract(h)
    assert h == v["handoff"]
    assert h["case_id"] == cid and h["verdict_version"] == 1
    assert (h["result_type"], h["waste_code"], h["outcome"]) == ("NO_CODE", None, "NOT_WASTE")
    g = real_kb.guidance_for("NO_CODE", "NOT_WASTE")  # 데이터 파일 값 그대로
    assert h["route_guidance"] == {"action": g.action, "summary": g.summary, "notes": list(g.notes)}
    assert h["route_guidance"]["action"] == "NO_ROUTE_NEEDED"
    assert h["facts"]["material_fate"] == {
        "value": "still_used",
        "status": "CLAIMED",
        "source_type": "PROFILE",
    }
    assert h["evidence"] == [] and h["basis"] and h["kb"]["table_id"] == "pp"
    assert h["timestamps"]["as_of"] == AS_OF.isoformat()

    detail = real_api.get(f"/cases/{cid}").json()
    assert detail["handoff"] == h and detail["current_verdict"]["result_type"] == "NO_CODE"
    trace = real_api.get(f"/cases/{cid}/trace").json()["sessions"][0]["turns"]
    confirm = trace[-1]["payload"]
    assert confirm["result_type"] == "NO_CODE" and confirm["outcome"] == "NOT_WASTE"
    assert confirm["route_action"] == "NO_ROUTE_NEEDED"


def test_waste_code_handoff_has_document_evidence(api):
    cid = api.create_case()["case"]["id"]
    finish_with_document(api, cid)
    doc_id = api.get(f"/cases/{cid}").json()["documents"][0]["id"]
    r = api.post(f"/cases/{cid}/confirm", json={"expected_code": "SAMPLE-A"})
    assert r.status_code == 200, r.text
    h = r.json()["handoff"]
    assert_handoff_contract(h)
    assert h["result_type"] == "WASTE_CODE" and h["waste_code"] == "SAMPLE-A"
    assert h["outcome"] is None and h["route_guidance"]["action"] == "RECOMMEND_ROUTE"
    assert h["evidence"] == [{"fact": "oil_content_pct", "document_id": doc_id}]
    assert h["facts"]["oil_content_pct"]["status"] == "EVIDENCED"
    assert h["facts"]["oil_content_pct"]["source_type"] == "DOCUMENT"
    assert h["facts"]["emission_facility"]["source_type"] == "PROFILE"
    assert h["kb"]["table_id"] == "plastic_waste" and h["kb"]["table_version"] == "2026.11.0"
    assert r.json()["verdict"]["result_type"] == "WASTE_CODE"


def test_undecided_unsupported_confirm_is_409(api):
    cid = api.create_case()["case"]["id"]
    t = api.reply(cid, "material", "OTHER")
    assert t["branch"] == "UNSUPPORTED" and not t["ui"]["can_confirm"]
    r = api.post(f"/cases/{cid}/confirm")
    assert r.status_code == 409
    assert r.json()["detail"]["failure_reason"] == "NO_TABLE"
    assert api.get(f"/cases/{cid}").json()["handoff"] is None


# ---- 시각 --------------------------------------------------------------------------------


def test_timestamps_are_tz_aware_seoul_and_as_of_survives_reopen(kb, tmp_path):
    """as_of는 대화 시작 날짜로 고정되고 reopen해도 바뀌지 않는다(날짜가 바뀐 뒤에도)."""
    today = {"d": date(2026, 11, 8)}
    app = create_app(
        make_settings(tmp_path / "t.db"),
        kb=kb,
        kb_dir=DATA,
        extractor_llm=fake_llm(),
        responder_llm=None,
        today=lambda: today["d"],
    )
    api = Api(client=TestClient(app), app=app, llm=None, db_path=tmp_path / "t.db")
    api.use(api.company())
    case = api.create_case()["case"]
    cid = case["id"]
    started = _seoul(case["diagnosis_started_at"])
    first_activity = _seoul(case["last_activity_at"])
    _seoul(case["created_at"])
    assert case["as_of"] == "2026-11-08"

    finish_with_document(api, cid)
    detail = api.get(f"/cases/{cid}").json()["case"]
    assert _seoul(detail["last_activity_at"]) > first_activity  # 턴마다 갱신
    assert _seoul(detail["diagnosis_started_at"]) == started

    today["d"] = date(2026, 12, 25)  # 다음 달에 확정·reopen
    v1 = api.post(f"/cases/{cid}/confirm").json()
    _seoul(v1["verdict"]["confirmed_at"])
    assert v1["verdict"]["as_of"] == "2026-11-08"
    assert v1["handoff"]["timestamps"]["as_of"] == "2026-11-08"
    assert _seoul(v1["handoff"]["timestamps"]["diagnosis_started_at"]) == started.replace(
        microsecond=0
    )

    r = api.post(f"/cases/{cid}/reopen", json={"reason": "성적서 재발급"}).json()
    old = r["superseded_verdict"]
    assert _seoul(old["reopened_at"]) == _seoul(old["superseded_at"])
    assert old["reopen_reason"] == "성적서 재발급"
    assert r["case"]["as_of"] == "2026-11-08"
    assert _seoul(r["case"]["diagnosis_started_at"]) == started

    v2 = api.post(f"/cases/{cid}/confirm").json()
    assert v2["verdict"]["version"] == 2 and v2["handoff"]["timestamps"]["as_of"] == "2026-11-08"
    assert v2["handoff"]["verdict_version"] == 2
    detail = api.get(f"/cases/{cid}").json()
    assert detail["handoff"] == v2["handoff"]
    assert detail["verdicts"][0]["reopened_at"] and detail["verdicts"][1]["reopened_at"] is None


def test_as_of_defaults_to_seoul_date_of_start(kb, tmp_path):
    app = create_app(
        make_settings(tmp_path / "s.db"),
        kb=kb,
        kb_dir=DATA,
        extractor_llm=fake_llm(),
        responder_llm=None,
    )  # today를 주지 않음 → 대화 시작 시각의 Asia/Seoul 날짜
    api = Api(client=TestClient(app), app=app, llm=None, db_path=tmp_path / "s.db")
    api.use(api.company())
    case = api.create_case()["case"]
    assert case["as_of"] == _seoul(case["diagnosis_started_at"]).date().isoformat()


# ---- 마이그레이션 0002 -------------------------------------------------------------------


def test_migration_0002_backfills_existing_rows(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    cfg = Config(ROOT_INI)
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0001")
    engine = create_engine(url)
    t0, t1 = "2026-11-08 00:10:00+00:00", "2026-11-08 00:20:00+00:00"
    with engine.begin() as c:
        c.execute(text("INSERT INTO companies VALUES ('co', 'c', '{}', :t)"), {"t": t0})
        c.execute(
            text(
                "INSERT INTO waste_cases VALUES "
                "('ca', 'co', NULL, NULL, NULL, NULL, 'CODE_CONFIRMED', :t, :t)"
            ),
            {"t": t0},
        )
        c.execute(
            text(
                "INSERT INTO diagnosis_sessions VALUES "
                "('se', 'ca', '2026-11-08', 'd', 'v', '{}', '{}', 0, 0, 0, :t0, :t1)"
            ),
            {"t0": t0, "t1": t1},
        )
        for i, code in ((1, "SAMPLE-A"), (2, None)):
            c.execute(
                text(
                    "INSERT INTO verdicts (case_id, session_id, version, code, name, category, "
                    "rule_ids, table_id, table_version, kb_version, as_of, facts_snapshot, "
                    "verdict, trace_turn_id, confirmed_at, superseded_at) VALUES "
                    "('ca', 'se', :v, :code, NULL, NULL, '[]', NULL, NULL, 'v', '2026-11-08', "
                    "'{}', '{}', NULL, :t, NULL)"
                ),
                {"v": i, "code": code, "t": t1},
            )
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        s = c.execute(text("SELECT started_at, last_activity_at FROM diagnosis_sessions")).one()
        assert s[0].startswith("2026-11-08 00:10") and s[1].startswith("2026-11-08 00:20")
        rows = c.execute(
            text("SELECT version, result_type, handoff FROM verdicts ORDER BY version")
        ).all()
        assert [(r[0], r[1], r[2]) for r in rows] == [(1, "WASTE_CODE", None), (2, "NO_CODE", None)]
    command.downgrade(cfg, "0001")
    engine.dispose()
