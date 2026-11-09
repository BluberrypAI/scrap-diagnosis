"""선택지(버튼) 응답을 사실로 바꾼다. LLM을 거치지 않는 결정적 경로.

- 사실 질문: 값 → CLAIMED, '모름' → DECLARED_UNKNOWN
- 묶음 질문: '모두 해당 없음' → 열린 구성 사실을 none_value(CLAIMED)로, '해당 있음/모름' → 펼침
"""

from __future__ import annotations

import math
from typing import Any

from app.domain.facts import Fact, FactStatus
from app.domain.ranges import NumRange
from app.rules.model import FactDef, KnowledgeBase


class AnswerError(ValueError):
    pass


def coerce_value(fd: FactDef, value: Any) -> Any:
    """카탈로그 타입에 맞게 값을 검증·변환한다. 맞지 않으면 AnswerError."""
    if value is None:
        return None
    if fd.type == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise AnswerError(f"{fd.key}: true/false 값이 필요합니다: {value!r}")
    if fd.type == "enum":
        if str(value) not in (fd.values or ()):
            raise AnswerError(f"{fd.key}: 값 영역에 없는 값 {value!r}")
        return str(value)
    # number
    if isinstance(value, NumRange):
        return value
    if isinstance(value, dict):
        return NumRange(**value)
    if isinstance(value, bool):
        raise AnswerError(f"{fd.key}: 숫자 값이 필요합니다")
    if isinstance(value, int | float):
        return value
    try:
        return float(str(value).replace(",", "").rstrip("%").strip())
    except ValueError as exc:
        raise AnswerError(f"{fd.key}: 숫자 값이 필요합니다: {value!r}") from exc


def check_document_value(kb: KnowledgeBase, key: str, value: Any, unit: str | None = None) -> Any:
    """서류 값의 형식만 거른다(원문 대조는 하지 않는다). 맞으면 카탈로그 타입으로 바꾼 값.

    거르는 것: 카탈로그에 없는 키, 빈 값('-'·공백 포함), 숫자 칸의 글자·무한대·NaN, 선택지 밖 값,
    카탈로그 단위와 다른 단위(엔진은 단위를 환산하지 않는다).
    """
    fd = kb.catalog.get(key)
    if fd is None:
        raise AnswerError(f"카탈로그에 없는 사실 키 {key}")
    if value is None or (isinstance(value, str) and value.strip() in ("", "-")):
        raise AnswerError(f"{key}: 빈 값입니다")
    if fd.type == "number" and isinstance(value, str):
        text = value.replace(",", "").rstrip("%").strip()
        if not text or any(c.isalpha() for c in text):  # '5mg', 'nan', 'inf', '미검출' 등
            raise AnswerError(f"{key}: 숫자 값이 필요합니다: {value!r}")
    try:
        out = coerce_value(fd, value)
    except AnswerError:
        raise
    except (TypeError, ValueError) as exc:  # 범위(dict) 값 형식 오류 등
        raise AnswerError(f"{key}: 값 형식이 올바르지 않습니다: {value!r}") from exc
    if isinstance(out, float) and not math.isfinite(out):
        raise AnswerError(f"{key}: 숫자 값이 필요합니다: {value!r}")
    if unit is not None and unit.strip() and fd.unit and unit.strip() != fd.unit:
        raise AnswerError(f"{key}: 단위가 다릅니다({unit!r}, 기준 {fd.unit!r})")
    return out


def fact_answer(
    kb: KnowledgeBase,
    key: str,
    value: Any,
    *,
    unknown: bool = False,
    source_type: str = "UTTERANCE",
    source_ref: str = "",
    quote: str | None = None,
    status: FactStatus = FactStatus.CLAIMED,
) -> Fact:
    fd = kb.catalog.get(key)
    if fd is None:
        raise AnswerError(f"카탈로그에 없는 사실 키 {key}")
    if unknown:
        return Fact(
            key=key,
            value=None,
            status=FactStatus.DECLARED_UNKNOWN,
            source_type=source_type,
            source_ref=source_ref,
            quote=quote,
        )
    return Fact(
        key=key,
        value=coerce_value(fd, value),
        status=status,
        source_type=source_type,
        source_ref=source_ref,
        quote=quote,
    )


def group_none_answer(
    kb: KnowledgeBase, group_id: str, open_members: list[str], source_ref: str = ""
) -> list[Fact]:
    g = kb.group(group_id)
    if g is None:
        raise AnswerError(f"없는 묶음 질문 {group_id}")
    out = []
    for k in open_members:
        if k not in g.facts:
            raise AnswerError(f"{group_id}에 속하지 않은 사실 {k}")
        out.append(
            Fact(
                key=k,
                value=kb.catalog[k].none_value,
                status=FactStatus.CLAIMED,
                source_type="SCREENING",
                source_ref=source_ref or group_id,
                note=f"묶음 질문 '{g.title}'에 '{g.none_label}'로 답함",
            )
        )
    return out
