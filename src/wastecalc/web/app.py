"""웹 화면(FastAPI). 문답은 엔진을 직접 불러 즉시 응답하고, LLM은 필요할 때만 쓴다.

실행: python -m wastecalc.web
  http://127.0.0.1:8000/       SCRAP 화면(팀 디자인 web/scrap/SCRAP.html). 문진(#/wastes/<id>/survey)만 엔진에 연결
  http://127.0.0.1:8000/test   꾸미지 않은 시험 화면
"""
from __future__ import annotations

import base64
import os
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from .. import llm
from ..candidates import code_candidates
from ..compact import compact, question_groups
from ..engine import InputError, evaluate, parse_answer, parse_answers, upgrade_legacy, value_text
from ..kb import ROOT, load_kb
from ..render import render_text
from ..session_state import load_session, revise_answers, save_session

KB = load_kb()
app = FastAPI(title="wastecalc 시험 화면")
STATIC = Path(__file__).parent / "static"
SCRAP = Path(__file__).parent / "scrap"
# SCRAP 디자인(Figma Make 내보내기)은 고치지 않고, 보낼 때 두 곳만 바꾼다.
# 1) 문진 경로면 React 앱을 그리지 않는다  2) 엔진 문진 화면(survey.js)을 붙인다
SCRAP_ROOT_MARK = "v.createRoot(document.getElementById(`root`)).render("
SCRAP_INJECT = (
    r'<script>window.__ENGINE_SURVEY=/^\/wastes\/[^/]+\/survey$/.test(window.__route().path);</script>' "\n"
    '<link rel="stylesheet" href="/scrap-engine/survey.css">\n'
    '<script src="/scrap-engine/survey.js" defer></script>\n')
SESSIONS: dict[str, dict[str, Any]] = {}
SESSION_DB = Path(os.getenv("WASTECALC_STATE_DB", str(ROOT / ".wastecalc" / "sessions.sqlite3")))
SESSION_LOCK = threading.RLock()


class StartReq(BaseModel):
    answers: dict = {}
    strict: bool = False
    as_of: str | None = None
    waste_id: str | None = None
    include_reporting: bool = False


class AnswerReq(BaseModel):
    fact: str
    value: Any = None  # None이면 답을 지움


class AnswersReq(BaseModel):
    answers: dict  # 묶음 질문의 답을 한 번에(사실마다 따로 엔진에 들어감)


class TextReq(BaseModel):
    text: str


class MapReq(BaseModel):
    fact: str
    text: str


class HelpReq(BaseModel):
    fact: str
    question: str | None = None
    why: str | None = None


def _session(sid: str) -> dict:
    s = SESSIONS.get(sid)
    if s is None:
        try:
            s = load_session(SESSION_DB, sid)
        except (OSError, sqlite3.Error, ValueError):
            raise HTTPException(503, "저장한 문진을 읽지 못했습니다. 잠시 후 다시 시도하세요.")
    if s is None:
        raise HTTPException(404, "없는 세션입니다. 처음부터 다시 시작하세요.")
    if s.get("rule_db_version") != KB.version:
        raise HTTPException(409, "저장 이후 규칙이 바뀌었습니다. 기존 문진을 덮어쓰지 않고 새 문진에서 다시 확인해야 합니다.")
    SESSIONS[sid] = s
    return s


def _view(sid: str, state: dict | None = None) -> dict:
    s = state if state is not None else _session(sid)
    r = evaluate(s["answers"], strict=s["strict"], kb=KB, as_of=s["as_of"], include_reporting=s.get("include_reporting", False))
    kb = KB.at(r["as_of"])
    answers = parse_answers(kb, s["answers"])
    answered = [{"fact": f, "label": kb.facts[f].get("label", f), "question": kb.facts[f]["question"],
                 "value": s["answers"][f], "value_text": value_text(kb, f, a)} for f, a in answers.items()]
    # 후보 수 변화: 지금까지 답한 순서대로(되돌리기 기록 + 현재)
    trail = []
    for snapshot in s["history"] + [{"answers": s["answers"]}]:
        past = snapshot["answers"]
        pr = r if past is s["answers"] else evaluate(past, strict=s["strict"], kb=KB, as_of=s["as_of"], include_reporting=s.get("include_reporting", False))
        trail.append(len(code_candidates(KB.at(pr["as_of"]), past, pr)))
    reviews = [{"fact": f, "label": kb.facts[f].get("label", f), "value": value,
                "value_text": value_text(kb, f, parse_answer(kb, f, value))}
               for f, value in s.get("needs_review", {}).items()]
    return {"session_id": sid, "result": compact(r, kb, s["answers"]), "answered": answered,
            "can_undo": bool(s["history"]), "candidate_trail": trail, "needs_review": reviews,
            "waste_id": s.get("waste_id"), "saved": True}


def _commit(sid: str, state: dict) -> dict:
    view = _view(sid, state)
    try:
        save_session(SESSION_DB, sid, state)
    except (OSError, sqlite3.Error):
        raise HTTPException(503, "문진을 저장하지 못했습니다. 입력을 유지한 채 다시 시도하세요.")
    SESSIONS[sid] = state
    return view


def scrap_html() -> str:
    s = (SCRAP / "SCRAP.html").read_text(encoding="utf-8")
    if s.count(SCRAP_ROOT_MARK) != 1 or "</head>" not in s:
        raise RuntimeError("SCRAP.html 구조가 달라져 엔진 문진 화면을 붙일 수 없습니다(app.py의 표식 확인).")
    s = s.replace(SCRAP_ROOT_MARK, "window.__ENGINE_SURVEY||" + SCRAP_ROOT_MARK, 1)
    return s.replace("</head>", SCRAP_INJECT + "</head>", 1)


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse(scrap_html())


@app.get("/test")
def test_page() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/scrap-engine/berry.png")
def berry() -> Response:
    """디자인 파일에 들어 있는 에이전트 '베리' 그림."""
    m = re.search(r"y=`data:image/png;base64,([A-Za-z0-9+/=]+)`", (SCRAP / "SCRAP.html").read_text(encoding="utf-8"))
    if not m:
        raise HTTPException(404)
    return Response(base64.b64decode(m.group(1)), media_type="image/png")


@app.get("/scrap-engine/{name}")
def scrap_asset(name: str) -> FileResponse:
    if name not in {"survey.js", "survey.css"}:
        raise HTTPException(404)
    return FileResponse(SCRAP / name)


@app.get("/api/status")
def api_status() -> dict:
    return {"llm": llm.status(), "as_of": KB.as_of, "rule_db_version": KB.version,
            "site_facts": [f for f in question_groups().get("site_facts", []) if f in KB.facts]}


@app.post("/api/extract")
def api_extract(req: TextReq) -> dict:
    """자유 설명 → 제안 사실(적용 전). 사용자가 확인한 것만 /api/session으로 넘긴다."""
    try:
        items = llm.extract_facts(KB, req.text)
    except llm.LLMUnavailable as e:
        raise HTTPException(400, str(e))
    out = []
    for it in items:
        f = KB.facts[it["fact"]]
        a = parse_answer(KB, it["fact"], it["value"])
        out.append({**it, "label": f.get("label", it["fact"]), "value_text": value_text(KB, it["fact"], a)})
    return {"proposed": out}


@app.post("/api/session")
def api_start(req: StartReq) -> dict:
    try:
        parse_answers(KB, req.answers)
        as_of = KB.at(req.as_of).as_of
    except (InputError, ValueError) as e:
        raise HTTPException(400, str(e))
    sid = uuid.uuid4().hex
    with SESSION_LOCK:
        return _commit(sid, {"answers": upgrade_legacy(dict(req.answers)), "strict": req.strict, "history": [],
                             "as_of": as_of, "rule_db_version": KB.version, "waste_id": req.waste_id, "needs_review": {},
                             "include_reporting": req.include_reporting})


@app.get("/api/session/{sid}")
def api_resume(sid: str) -> dict:
    with SESSION_LOCK:
        return _view(sid)


@app.post("/api/session/{sid}/answer")
def api_answer(sid: str, req: AnswerReq) -> dict:
    return _apply(sid, {req.fact: req.value})


@app.post("/api/session/{sid}/answers")
def api_answers(sid: str, req: AnswersReq) -> dict:
    if not req.answers:
        raise HTTPException(400, "답이 없습니다.")
    return _apply(sid, req.answers)


def _apply(sid: str, patch: dict) -> dict:
    with SESSION_LOCK:
        s = _session(sid)
        try:
            # 답을 지울 때도 사실 ID와 입력 가능 여부를 검사한다.
            for fact in patch:
                if fact not in KB.facts or KB.facts[fact].get("derived_from"):
                    raise InputError(f"수정할 수 없는 사실입니다: {fact}")
            new, invalidated = revise_answers(KB, s["answers"], patch)
        except InputError as e:
            raise HTTPException(400, str(e))
        reviews = {**s.get("needs_review", {}), **invalidated}
        for fact in patch:
            reviews.pop(fact, None)
        if new == s["answers"] and reviews == s.get("needs_review", {}):
            return _view(sid)
        history = s["history"] + [{"answers": s["answers"], "needs_review": s.get("needs_review", {})}]
        return _commit(sid, {**s, "answers": new, "needs_review": reviews, "history": history})


@app.post("/api/session/{sid}/undo")
def api_undo(sid: str) -> dict:
    with SESSION_LOCK:
        s = _session(sid)
        if not s["history"]:
            return _view(sid)
        previous = s["history"][-1]
        return _commit(sid, {**s, **previous, "history": s["history"][:-1]})


@app.get("/api/session/{sid}/record")
def api_record(sid: str) -> dict:
    """판정 기록(이후 단계용 고정 형식, schemas/assessment_record.schema.json)."""
    from ..record import build_record

    with SESSION_LOCK:
        s = _session(sid)
        r = evaluate(s["answers"], strict=s["strict"], kb=KB, as_of=s["as_of"],
                     include_reporting=s.get("include_reporting", False))
        return build_record(KB.at(r["as_of"]), s["answers"], r)


@app.get("/api/session/{sid}/explain")
def api_explain(sid: str) -> dict:
    s = _session(sid)
    r = evaluate(s["answers"], strict=s["strict"], kb=KB, as_of=s["as_of"], include_reporting=s.get("include_reporting", False))
    return {"text": render_text(r, glossary=KB.glossary)}


@app.get("/api/fact/{fid}")
def api_fact(fid: str) -> dict:
    """답한 사실을 고칠 때 보기 목록."""
    f = KB.facts.get(fid)
    if f is None or f.get("derived_from"):
        raise HTTPException(404, "고칠 수 없는 사실입니다.")
    from ..compact import _choices

    return {"fact": fid, "question": f["question"], "choices": _choices(KB, fid, None),
            "unit": f.get("unit") if f["type"] == "number" else None}


@app.post("/api/map")
def api_map(req: MapReq) -> dict:
    if req.fact not in KB.facts:
        raise HTTPException(404, "없는 사실입니다.")
    try:
        m = llm.map_answer(KB, req.fact, req.text)
    except llm.LLMUnavailable as e:
        raise HTTPException(400, str(e))
    a = parse_answer(KB, req.fact, m["value"])
    return {**m, "value_text": value_text(KB, req.fact, a)}


@app.post("/api/help")
def api_help(req: HelpReq) -> dict:
    if req.fact not in KB.facts:
        raise HTTPException(404, "없는 사실입니다.")
    try:
        return {"text": llm.explain_question(KB, req.fact, req.why, req.question)}
    except llm.LLMUnavailable as e:
        raise HTTPException(400, str(e))



# ================================================================ scrap-web 문진 화면용 API
# 화면(scrap-web src/pages/survey)이 읽는 모양으로 응답한다(src/wastecalc/scrap_view.py).
# - 상태 없는 판정: POST /api/classification/evaluate  — 서버(scrap-server)가 답·화면 상태를 DB에 저장하고 부를 때
# - 세션(로컬 시연·개발용): /api/classification/sessions…  — 엔진이 자체 SQLite에 저장
# 화면은 고른 보기의 answers를 그대로 돌려보낸다. answers 안의 "__ui"는 화면 상태(묶음 선택 등)이며 엔진 사실이 아니다.

class ClassEvalReq(BaseModel):
    answers: dict = {}
    ui: dict = {}
    as_of: str | None = None
    strict: bool = True
    trail: list[int] = []


class ClassStartReq(BaseModel):
    waste_id: str | None = None
    answers: dict = {}
    as_of: str | None = None


class ClassAnswerReq(BaseModel):
    answers: dict


def _class_view(sid: str, s: dict) -> dict:
    from ..scrap_view import build_view

    trail = []
    for snap in s["history"]:
        pr = evaluate(snap["answers"], strict=True, kb=KB, as_of=s["as_of"])
        trail.append(len(code_candidates(KB.at(pr["as_of"]), snap["answers"], pr)))
    view = build_view(KB, s["answers"], s.get("ui") or {}, strict=True, as_of=s["as_of"], trail=trail)
    return {"session_id": sid, "waste_id": s.get("waste_id"), "can_undo": bool(s["history"]) or bool(s.get("ui")),
            "needs_review": list((s.get("needs_review") or {}).keys()), **view}


def _class_persist(sid: str, state: dict) -> None:
    try:
        save_session(SESSION_DB, sid, state)
    except (OSError, sqlite3.Error):
        raise HTTPException(503, "문진을 저장하지 못했습니다. 다시 시도하세요.")
    SESSIONS[sid] = state


@app.post("/api/classification/evaluate")
def class_evaluate(req: ClassEvalReq) -> dict:
    """상태 없는 판정: 답(엔진 사실)과 화면 상태를 받아 화면 응답을 돌려준다. 저장은 호출한 쪽(서버)이 한다."""
    from ..scrap_view import build_view

    try:
        parse_answers(KB, req.answers)
        return build_view(KB, req.answers, req.ui, strict=req.strict, as_of=req.as_of, trail=req.trail)
    except (InputError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/classification/sessions")
def class_start(req: ClassStartReq) -> dict:
    try:
        parse_answers(KB, req.answers)
        as_of = KB.at(req.as_of).as_of
    except (InputError, ValueError) as e:
        raise HTTPException(400, str(e))
    sid = uuid.uuid4().hex
    state = {"answers": upgrade_legacy(dict(req.answers)), "strict": True, "history": [], "as_of": as_of,
             "rule_db_version": KB.version, "waste_id": req.waste_id, "needs_review": {}, "ui": {},
             "include_reporting": False, "kind": "classification"}
    with SESSION_LOCK:
        _class_persist(sid, state)
        return _class_view(sid, state)


@app.get("/api/classification/sessions/{sid}")
def class_get(sid: str) -> dict:
    with SESSION_LOCK:
        return _class_view(sid, _session(sid))


@app.post("/api/classification/sessions/{sid}/answer")
def class_answer(sid: str, req: ClassAnswerReq) -> dict:
    """고른 보기의 answers를 그대로 받는다(엔진 사실 + '__ui' 화면 상태)."""
    from ..scrap_view import merge_ui, split_ui

    with SESSION_LOCK:
        s = _session(sid)
        facts, ui_patch = split_ui(req.answers)
        try:
            for fact in facts:
                if fact not in KB.facts or KB.facts[fact].get("derived_from"):
                    raise InputError(f"수정할 수 없는 사실입니다: {fact}")
            new, invalidated = revise_answers(KB, s["answers"], facts) if facts else (s["answers"], {})
        except InputError as e:
            raise HTTPException(400, str(e))
        reviews = {**(s.get("needs_review") or {}), **invalidated}
        for fact in facts:
            reviews.pop(fact, None)
        snapshot = {"answers": s["answers"], "needs_review": s.get("needs_review") or {}, "ui": s.get("ui") or {}}
        state = {**s, "answers": new, "needs_review": reviews, "ui": merge_ui(s.get("ui") or {}, ui_patch),
                 "history": s["history"] + ([snapshot] if facts else s["history"][:0])}
        if not facts:  # 화면 상태만 바뀜(묶음 선택 등): 되돌리기는 ui를 먼저 비운다
            state["history"] = s["history"]
        _class_persist(sid, state)
        return _class_view(sid, state)


@app.post("/api/classification/sessions/{sid}/undo")
def class_undo(sid: str) -> dict:
    with SESSION_LOCK:
        s = _session(sid)
        ui = dict(s.get("ui") or {})
        if ui.get("report_exceed") or ui.get("group"):
            ui.pop("report_exceed", None)
            ui.pop("group", None)  # 묶음 선택 화면으로 돌아감
            state = {**s, "ui": ui}
        elif s["history"]:
            prev = s["history"][-1]
            state = {**s, "answers": prev["answers"], "needs_review": prev.get("needs_review") or {},
                     "ui": prev.get("ui") or {}, "history": s["history"][:-1]}
        else:
            return _class_view(sid, s)
        _class_persist(sid, state)
        return _class_view(sid, state)


@app.get("/api/classification/sessions/{sid}/record")
def class_record(sid: str) -> dict:
    """판정 기록(이후 단계·서버 저장용, schemas/assessment_record.schema.json)."""
    from ..record import build_record

    with SESSION_LOCK:
        s = _session(sid)
        r = evaluate(s["answers"], strict=True, kb=KB, as_of=s["as_of"])
        rec = build_record(KB.at(r["as_of"]), s["answers"], r)
        if (s.get("ui") or {}).get("range"):
            rec["range_answers"] = s["ui"]["range"]  # 숫자 대신 구간으로 답한 사실(대표값으로 판정)
        return rec


@app.post("/api/classification/extract")
def class_extract(req: TextReq) -> dict:
    """자유 설명 → 이해 확인 화면의 [[항목, 값]]과 시작할 때 넣을 answers(사용자가 확인한 뒤)."""
    from ..scrap_view import cues

    try:
        items = llm.extract_facts(KB, req.text)
    except llm.LLMUnavailable as e:
        raise HTTPException(400, str(e))
    proposed = []
    for it in items:
        a = parse_answer(KB, it["fact"], it["value"])
        proposed.append({**it, "label": KB.facts[it["fact"]].get("label", it["fact"]),
                         "value_text": value_text(KB, it["fact"], a)})
    return {"cues": cues(KB, proposed), "answers": {p["fact"]: p["value"] for p in proposed}, "proposed": proposed}


# ---------------- 상태 없는 답 적용·판정 기록(서버가 상태를 DB에 저장할 때)
class ClassApplyReq(BaseModel):
    state: dict = {}        # {"answers": {...}, "ui": {...}, "needs_review": {...}} — 서버가 저장해 둔 그대로
    patch: dict             # 화면이 보낸 보기의 answers(엔진 사실 + "__ui")
    as_of: str | None = None
    trail: list[int] = []


class ClassStateReq(BaseModel):
    state: dict = {}
    as_of: str | None = None


@app.post("/api/classification/apply")
def class_apply(req: ClassApplyReq) -> dict:
    """답을 적용한 새 상태와 화면 응답. 앞 답을 고치면 영향받는 뒤 답을 빼고 needs_review로 돌려준다.
    서버는 돌려받은 state를 저장하고, '이전'은 저장해 둔 직전 state로 되돌리면 된다."""
    from ..scrap_view import build_view, merge_ui, split_ui

    st = req.state or {}
    answers = upgrade_legacy(dict(st.get("answers") or {}))
    facts, ui_patch = split_ui(req.patch)
    try:
        for fact in facts:
            if fact not in KB.facts or KB.facts[fact].get("derived_from"):
                raise InputError(f"수정할 수 없는 사실입니다: {fact}")
        new, invalidated = revise_answers(KB, answers, facts) if facts else (answers, {})
        reviews = {**(st.get("needs_review") or {}), **invalidated}
        for fact in facts:
            reviews.pop(fact, None)
        ui = merge_ui(st.get("ui") or {}, ui_patch)
        view = build_view(KB, new, ui, strict=True, as_of=req.as_of, trail=req.trail)
    except (InputError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"state": {"answers": new, "ui": ui, "needs_review": reviews}, "changed_facts": bool(facts),
            "view": view}


@app.post("/api/classification/record")
def class_record_stateless(req: ClassStateReq) -> dict:
    """상태 없는 판정 기록(서버가 결과를 저장할 때)."""
    from ..record import build_record

    answers = (req.state or {}).get("answers") or {}
    try:
        r = evaluate(answers, strict=True, kb=KB, as_of=req.as_of)
    except (InputError, ValueError) as e:
        raise HTTPException(400, str(e))
    rec = build_record(KB.at(r["as_of"]), answers, r)
    if ((req.state or {}).get("ui") or {}).get("range"):
        rec["range_answers"] = req.state["ui"]["range"]
    return rec
