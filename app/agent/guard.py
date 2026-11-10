"""LLM 출력 검증 (docs/engine/algorithm.md 7절). LLM 결과는 여기를 통과한 것만 엔진에 들어간다.

추출 검증
- 카탈로그에 있는 키만, internal 사실은 직전 질문의 선택지 안에서만
- 값은 카탈로그 타입·값 영역에 맞아야 함(coerce_value)
- quote가 사용자 원문에 실제로 있어야 함(공백 무시)
- 수치는 그 숫자가 quote 안에 있어야 함(지어낸 숫자 차단)
- '모름'(DECLARED_UNKNOWN)은 직전 질문의 사실에만
응답 검증
- 메시지 안의 분류번호는 payload에 있는 번호만
- 메시지 안의 숫자는 payload에 있는 숫자만
- 질문은 한 턴에 하나(물음표 1개 이하)
- 인용 id는 payload의 근거 id만
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from app.domain.facts import Fact, FactStatus
from app.domain.ranges import NumRange
from app.rules.answers import AnswerError, coerce_value
from app.rules.model import KnowledgeBase
from app.rules.selector import QuestionChoice

# 한국어 조사가 바로 붙어도(예: "51-03-01입니다") 잡히도록 \b 대신 숫자 경계를 쓴다.
CODE_PATTERN = re.compile(r"(?<![\d-])\d{2}-\d{2}-\d{2}(?![\d-])|SAMPLE-[A-Z0-9]+(?![A-Z0-9])")
NUMBER_PATTERN = re.compile(r"(?<![\d.,])\d+(?:[.,]\d+)?(?![\d.,])")


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


class ExtractionResult(BaseModel):
    facts: list[Fact] = []
    group_answer: dict | None = None
    user_code_claim: str | None = None
    user_question: str | None = None
    question_kind: str | None = None  # why | term | off_topic (문진 보충 설명, agent/assist.py)
    evidence_refused: bool = False
    rejected: list[dict] = []
    errors: list[str] = []
    attempts: int = 0
    llm_blocked: str | None = None  # AI 전송을 막은 이유(가리기 실패·문서 차단). Trace에 남긴다

    @property
    def empty(self) -> bool:
        return not (
            self.facts
            or self.group_answer
            or self.user_code_claim
            or self.user_question
            or self.evidence_refused
        )


def _digits(x: float) -> list[str]:
    """숫자가 원문에 나타날 수 있는 표기들."""
    out = {f"{x:g}"}
    if float(x).is_integer():
        out.add(str(int(x)))
    return sorted(out)


def _number_in_quote(x: float, quote: str) -> bool:
    q = norm(quote).replace(",", "")
    return any(d in q for d in _digits(x))


def _allowed_keys_for_unknown(q: QuestionChoice | None) -> set[str]:
    if q is None:
        return set()
    return set(q.facts) | {q.key}


def validate_extraction(
    kb: KnowledgeBase,
    raw: dict,
    text: str,
    *,
    last_question: QuestionChoice | None,
    message_id: str,
) -> ExtractionResult:
    res = ExtractionResult()
    ntext = norm(text)
    seen: set[str] = set()
    for item in raw.get("facts") or []:
        key = item.get("key")
        quote = item.get("quote") or ""

        def reject(reason: str, _key=key, _item=item) -> None:
            res.rejected.append({"key": _key, "reason": reason, "item": _item})

        fd = kb.catalog.get(key or "")
        if fd is None:
            reject("카탈로그에 없는 사실 키")
            continue
        if key in seen:
            reject("같은 사실을 두 번 냄")
            continue
        if not quote or norm(quote) not in ntext:
            reject("quote가 사용자 발화에 없음")
            continue
        status = item.get("status")
        if fd.internal and (last_question is None or last_question.key != key):
            reject("직전 질문이 아닌 내부 사실")
            continue
        if status == "DECLARED_UNKNOWN":
            if key not in _allowed_keys_for_unknown(last_question):
                reject("'모름'은 직전 질문의 사실에만 쓸 수 있음")
                continue
            seen.add(key)
            res.facts.append(
                Fact(
                    key=key,
                    value=None,
                    status=FactStatus.DECLARED_UNKNOWN,
                    source_ref=message_id,
                    quote=quote,
                    note=item.get("note"),
                )
            )
            continue
        if status == "UNKNOWN":
            seen.add(key)
            res.facts.append(
                Fact(
                    key=key,
                    value=None,
                    status=FactStatus.UNKNOWN,
                    source_ref=message_id,
                    quote=quote,
                    note=item.get("note"),
                )
            )
            continue
        # CLAIMED: 값이 있어야 한다
        value: Any = None
        if fd.type == "enum":
            value = item.get("value_text")
        elif fd.type == "bool":
            value = item.get("value_bool")
            if value is None and isinstance(item.get("value_text"), str):
                value = item["value_text"]
        else:
            rng = item.get("range")
            if item.get("value_number") is not None:
                value = item["value_number"]
                if not _number_in_quote(float(value), quote):
                    reject("수치가 quote에 없음(지어낸 숫자)")
                    continue
            elif rng and (rng.get("lo") is not None or rng.get("hi") is not None):
                for b in ("lo", "hi"):
                    if rng.get(b) is not None and not _number_in_quote(float(rng[b]), quote):
                        reject("범위 경계값이 quote에 없음")
                        break
                else:
                    value = NumRange(
                        lo=rng.get("lo"),
                        lo_inc=bool(rng.get("lo_inc")) if rng.get("lo") is not None else True,
                        hi=rng.get("hi"),
                        hi_inc=bool(rng.get("hi_inc")) if rng.get("hi") is not None else False,
                    )
                if value is None:
                    continue
        if value is None:
            reject("CLAIMED인데 값이 없음")
            continue
        try:
            value = coerce_value(fd, value)
        except AnswerError as exc:
            reject(str(exc))
            continue
        if fd.internal and last_question is not None:
            allowed = {str(o.value) for o in last_question.value_options if o.kind == "value"}
            if str(value) not in allowed:
                reject("제시한 선택지에 없는 값")
                continue
        seen.add(key)
        res.facts.append(
            Fact(
                key=key,
                value=value,
                status=FactStatus.CLAIMED,
                source_ref=message_id,
                quote=quote,
                note=item.get("note"),
            )
        )

    ga = raw.get("group_answer")
    if ga:
        if (
            last_question is None
            or last_question.unit != "group"
            or (ga.get("group_id") != last_question.key)
        ):
            res.rejected.append(
                {"key": ga.get("group_id"), "reason": "직전 질문이 아닌 묶음", "item": ga}
            )
        elif ga.get("quote") and norm(ga["quote"]) not in ntext:
            res.rejected.append(
                {"key": ga.get("group_id"), "reason": "quote가 발화에 없음", "item": ga}
            )
        else:
            res.group_answer = {"group_id": ga["group_id"], "choice": ga["choice"]}

    claim = raw.get("user_code_claim")
    if claim:
        m = CODE_PATTERN.search(claim)
        if m and norm(m.group(0)) in ntext.replace(" ", ""):
            res.user_code_claim = m.group(0)
        else:
            res.rejected.append(
                {"key": "user_code_claim", "reason": "발화에 없는 번호", "item": claim}
            )
    if raw.get("user_question"):
        res.user_question = str(raw["user_question"])
    kind = raw.get("question_kind")
    if kind in ("why", "term", "off_topic"):
        res.question_kind = kind
        if not res.user_question:  # 질문 문장을 비웠으면 발화 전체를 질문으로 본다
            res.user_question = text.strip()[:200]
    res.evidence_refused = bool(raw.get("evidence_refused"))
    return res


# ---- 응답 검증 -----------------------------------------------------------------------------


def validate_response(
    message: str, cited: list[str], payload: dict, payload_text: str, basis_ids: set[str]
) -> list[str]:
    """응답 문장 검사. 문제 목록을 반환(비었으면 통과)."""
    problems = []
    allowed_codes = set(CODE_PATTERN.findall(payload_text))
    for code in CODE_PATTERN.findall(message):
        if code not in allowed_codes:
            problems.append(f"payload에 없는 분류번호 {code}")
    stripped = CODE_PATTERN.sub(" ", message)
    payload_numbers = {
        n.replace(",", "") for n in NUMBER_PATTERN.findall(CODE_PATTERN.sub(" ", payload_text))
    }
    for n in NUMBER_PATTERN.findall(stripped):
        n2 = n.replace(",", "")
        if n2 not in payload_numbers:
            problems.append(f"payload에 없는 숫자 {n}")
    if message.count("?") > 1:
        problems.append("한 턴에 질문이 둘 이상")
    for c in cited:
        if c not in basis_ids:
            problems.append(f"없는 근거 id {c}")
    if not message.strip():
        problems.append("빈 메시지")
    return problems
