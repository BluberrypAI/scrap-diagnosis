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
from ..compact import compact
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


class AnswerReq(BaseModel):
    fact: str
    value: Any = None  # None이면 답을 지움


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
    r = evaluate(s["answers"], strict=s["strict"], kb=KB, as_of=s["as_of"])
    kb = KB.at(r["as_of"])
    answers = parse_answers(kb, s["answers"])
    answered = [{"fact": f, "label": kb.facts[f].get("label", f), "question": kb.facts[f]["question"],
                 "value": s["answers"][f], "value_text": value_text(kb, f, a)} for f, a in answers.items()]
    # 후보 수 변화: 지금까지 답한 순서대로(되돌리기 기록 + 현재)
    trail = []
    for snapshot in s["history"] + [{"answers": s["answers"]}]:
        past = snapshot["answers"]
        pr = r if past is s["answers"] else evaluate(past, strict=s["strict"], kb=KB, as_of=s["as_of"])
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
    return {"llm": llm.status(), "as_of": KB.as_of, "rule_db_version": KB.version}


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
                             "as_of": as_of, "rule_db_version": KB.version, "waste_id": req.waste_id, "needs_review": {}})


@app.get("/api/session/{sid}")
def api_resume(sid: str) -> dict:
    with SESSION_LOCK:
        return _view(sid)


@app.post("/api/session/{sid}/answer")
def api_answer(sid: str, req: AnswerReq) -> dict:
    with SESSION_LOCK:
        s = _session(sid)
        try:
            # 답을 지울 때도 사실 ID와 입력 가능 여부를 검사한다.
            if req.fact not in KB.facts or KB.facts[req.fact].get("derived_from"):
                raise InputError("수정할 수 없는 사실입니다.")
            new, invalidated = revise_answers(KB, s["answers"], {req.fact: req.value})
        except InputError as e:
            raise HTTPException(400, str(e))
        reviews = {**s.get("needs_review", {}), **invalidated}
        reviews.pop(req.fact, None)
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


@app.get("/api/session/{sid}/explain")
def api_explain(sid: str) -> dict:
    s = _session(sid)
    r = evaluate(s["answers"], strict=s["strict"], kb=KB, as_of=s["as_of"])
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
