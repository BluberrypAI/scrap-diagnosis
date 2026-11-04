"""LLM 어댑터 (선택 사항). 판정은 하지 않는다 — 말 → 사실 값 변환과 쉬운 설명만.

설정(환경변수 또는 re_mcp/.env):
  LLM_PROVIDER=azure          # azure | openai | (비우면 LLM 기능 꺼짐)
  AZURE_OPENAI_ENDPOINT=https://<리소스>.openai.azure.com
  AZURE_OPENAI_API_KEY=...
  AZURE_OPENAI_DEPLOYMENT=<배포 이름>
  AZURE_OPENAI_API_VERSION=2024-10-21
  OPENAI_API_KEY=...          # LLM_PROVIDER=openai 일 때
  OPENAI_MODEL=<모델 이름>
  OPENAI_BASE_URL=...         # (선택) OpenAI 호환 서버
안전장치: LLM이 낸 값은 엔진의 입력 검사를 통과해야 하고, 사실 추출은 근거 구절이 사용자 글에 실제로 있어야 받는다.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .engine import InputError, parse_answer
from .kb import KB, ROOT

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # dotenv 없으면 환경변수만 사용
    pass

SKIP_FACTS = {"code", "general_group", "no_specific_code_applies"}  # 번호는 화면에서 직접 고른다


class LLMUnavailable(RuntimeError):
    pass


def provider() -> str | None:
    p = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    return p or None


def status() -> dict:
    p = provider()
    if p == "azure":
        ok = all(os.getenv(k) for k in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT"))
        return {"enabled": ok, "provider": "azure", "model": os.getenv("AZURE_OPENAI_DEPLOYMENT")}
    if p == "openai":
        ok = bool(os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL"))
        return {"enabled": ok, "provider": "openai", "model": os.getenv("OPENAI_MODEL")}
    return {"enabled": False, "provider": None, "model": None}


def _client():
    st = status()
    if not st["enabled"]:
        raise LLMUnavailable("LLM 설정이 없습니다(.env의 LLM_PROVIDER 등). 객관식으로는 계속 쓸 수 있습니다.")
    if st["provider"] == "azure":
        from openai import AzureOpenAI

        return AzureOpenAI(azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                           api_key=os.environ["AZURE_OPENAI_API_KEY"],
                           api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")), st["model"]
    from openai import OpenAI

    return OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=os.getenv("OPENAI_BASE_URL") or None), st["model"]


def _chat_json(system: str, user: str) -> dict:
    client, model = _client()
    resp = client.chat.completions.create(
        model=model, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    try:
        return json.loads(resp.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return {}


def _chat_text(system: str, user: str) -> str:
    client, model = _client()
    resp = client.chat.completions.create(
        model=model, temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return (resp.choices[0].message.content or "").strip()


def _fact_catalog(kb: KB) -> list[dict]:
    out = []
    for fid, f in kb.facts.items():
        if f.get("derived_from") or fid in SKIP_FACTS:
            continue
        item = {"id": fid, "question": f["question"], "type": f["type"]}
        if f["type"] == "enum":
            item["values"] = f["values"]
        if f.get("unit") is not None:
            item["unit"] = f["unit"]
        out.append(item)
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


EXTRACT_SYSTEM = """너는 폐기물 담당자의 설명에서 '사실'만 뽑는 도우미다. 판정(폐기물 여부, 지정폐기물, 분류번호)은 하지 않는다.
규칙:
- 설명에 분명히 적힌 사실만 뽑는다. 짐작·상식으로 채우지 않는다. 애매하면 뽑지 않는다.
- 값은 반드시 주어진 사실 목록의 형식과 허용 값(enum의 키)만 쓴다. bool은 true/false, 숫자는 숫자.
- 각 사실마다 근거가 된 설명 속 구절을 그대로(복사해서) evidence에 적는다.
출력 JSON: {"facts": {"사실id": 값}, "evidence": {"사실id": "설명 속 구절"}}"""


def extract_facts(kb: KB, text: str) -> list[dict]:
    """자유 설명 → 제안 사실 목록(아직 적용 안 함). 근거 구절이 원문에 없거나 값이 허용 밖이면 버린다."""
    data = _chat_json(EXTRACT_SYSTEM, json.dumps({"사실 목록": _fact_catalog(kb), "설명": text}, ensure_ascii=False))
    facts, evidence = data.get("facts") or {}, data.get("evidence") or {}
    out = []
    for fid, val in facts.items():
        if fid not in kb.facts or fid in SKIP_FACTS or kb.facts[fid].get("derived_from"):
            continue
        ev = evidence.get(fid) or ""
        if not ev or _norm(ev) not in _norm(text):
            continue  # 근거 구절이 사용자 글에 없으면(지어낸 사실) 받지 않는다
        try:
            parse_answer(kb, fid, val)
        except InputError:
            continue
        out.append({"fact": fid, "value": val, "evidence": ev})
    return out


MAP_SYSTEM = """너는 사용자의 자유 답변을 정해진 질문의 값 하나로 바꾸는 도우미다. 판정은 하지 않는다.
- 허용 값 중 하나만 고른다(enum은 키, bool은 true/false, 숫자는 숫자). 확실하지 않으면 "UNKNOWN".
- 사용자가 말하지 않은 내용을 덧붙이지 않는다.
출력 JSON: {"value": 값, "reason": "왜 이 값인지 한 문장"}"""


def map_answer(kb: KB, fid: str, text: str) -> dict:
    f = kb.facts[fid]
    spec = {"question": f["question"], "type": f["type"], "values": f.get("values"), "unit": f.get("unit")}
    data = _chat_json(MAP_SYSTEM, json.dumps({"질문": spec, "사용자 답": text}, ensure_ascii=False))
    val: Any = data.get("value", "UNKNOWN")
    try:
        parse_answer(kb, fid, val)
    except InputError:
        val = "UNKNOWN"
    return {"value": val, "reason": data.get("reason", "")}


HELP_SYSTEM = """너는 폐기물 법 용어를 쉬운 말로 풀어 주는 도우미다.
- 질문의 뜻과 어떻게 확인하는지만 설명한다. 이 사용자의 폐기물이 무엇인지 판정하지 않는다.
- 주어진 자료(질문, 이유, 용어 풀이, 확인 방법)에 없는 숫자·기준·조문을 말하지 않는다.
- 3~5문장, 한국어."""


def explain_question(kb: KB, fid: str, why: str | None, user_q: str | None) -> str:
    f = kb.facts[fid]
    material = {
        "질문": f["question"], "왜 묻나": why,
        "확인 방법": [h["text"] for h in f.get("how_to_check", [])],
        "보기": f.get("values"),
        "용어 풀이": {t: d for t, d in kb.glossary.items() if t in (f["question"] + str(f.get("values", "")))},
        "사용자 물음": user_q or "이 질문이 무슨 뜻인가요?",
    }
    return _chat_text(HELP_SYSTEM, json.dumps(material, ensure_ascii=False))
