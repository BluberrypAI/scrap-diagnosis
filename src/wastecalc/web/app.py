"""시험용 웹 화면(FastAPI). 문답은 엔진을 직접 불러 즉시 응답하고, LLM은 필요할 때만 쓴다.

실행: python -m wastecalc.web   → http://127.0.0.1:8000
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import llm
from ..compact import compact
from ..engine import InputError, evaluate, parse_answer, parse_answers, value_text
from ..kb import load_kb
from ..render import render_text

KB = load_kb()
app = FastAPI(title="wastecalc 시험 화면")
STATIC = Path(__file__).parent / "static"
SESSIONS: dict[str, dict[str, Any]] = {}


class StartReq(BaseModel):
    answers: dict = {}
    strict: bool = False


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
        raise HTTPException(404, "없는 세션입니다. 처음부터 다시 시작하세요.")
    return s


def _view(sid: str) -> dict:
    s = _session(sid)
    r = evaluate(s["answers"], strict=s["strict"], kb=KB)
    kb = KB.at(r["as_of"])
    answers = parse_answers(kb, s["answers"])
    answered = [{"fact": f, "label": kb.facts[f].get("label", f), "question": kb.facts[f]["question"],
                 "value": s["answers"][f], "value_text": value_text(kb, f, a)} for f, a in answers.items()]
    return {"session_id": sid, "result": compact(r, kb), "answered": answered,
            "can_undo": bool(s["history"])}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


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
    except InputError as e:
        raise HTTPException(400, str(e))
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = {"answers": dict(req.answers), "strict": req.strict, "history": []}
    return _view(sid)


@app.post("/api/session/{sid}/answer")
def api_answer(sid: str, req: AnswerReq) -> dict:
    s = _session(sid)
    new = dict(s["answers"])
    if req.value is None:
        new.pop(req.fact, None)  # 답 지우기 → '아직 답 안 함'
    else:
        try:
            parse_answer(KB, req.fact, req.value)
        except InputError as e:
            raise HTTPException(400, str(e))
        new[req.fact] = req.value
    s["history"].append(dict(s["answers"]))
    s["answers"] = new
    return _view(sid)


@app.post("/api/session/{sid}/undo")
def api_undo(sid: str) -> dict:
    s = _session(sid)
    if s["history"]:
        s["answers"] = s["history"].pop()
    return _view(sid)


@app.get("/api/session/{sid}/explain")
def api_explain(sid: str) -> dict:
    s = _session(sid)
    r = evaluate(s["answers"], strict=s["strict"], kb=KB)
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
