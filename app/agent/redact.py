"""AI 전송 전 식별 정보 가리기 (CORP-008, OPS-010).

사업자·법인·주민번호, 전화·휴대폰, 이메일, 상세주소를 토큰([사업자번호] 등)으로 바꾼다.
폐기물 분류번호(51-03-01)·수치(5%, 10 mg/L, pH 2)·날짜는 식별 정보가 아니므로 그대로 둔다.

fail-closed: 가리기 중 오류가 나거나, 가린 뒤에도 식별 패턴이 남아 있으면 `RedactionError`.
호출하는 쪽은 이때 LLM을 부르지 않는다.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from pydantic import BaseModel


class RedactionError(RuntimeError):
    """가리기 실패 또는 가린 뒤에도 식별 정보 잔존. 이 경우 AI로 보내지 않는다."""


_UNIT = r"(?:%|퍼센트|mg|kg|g|L|ℓ|ml|mL|개|톤|ppm|도|℃|m3|㎥|리터)"

# (토큰, 패턴). 순서가 중요하다: 긴 번호 → 짧은 번호 → 전화 → 주소.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("[주민번호]", re.compile(r"(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)")),
    ("[법인번호]", re.compile(r"(?<!\d)\d{6}-\d{7}(?!\d)")),
    ("[사업자번호]", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{5}(?!\d)")),
    # 하이픈 없는 10자리는 '사업자(등록)번호' 문맥일 때만(수치 오탐 방지)
    (
        "[사업자번호]",
        re.compile(r"(?<=사업자번호)[\s:：]*\d{10}(?!\d)|(?<=사업자등록번호)[\s:：]*\d{10}(?!\d)"),
    ),
    ("[이메일]", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")),
    (
        "[전화번호]",
        re.compile(
            r"(?<![\d-])(?:\+82[-.\s]?)?"
            r"(?:0?10|0?1[16-9]|0?2|0?[3-6][1-5]|0?70|0?80|0?50\d?)"
            r"[-.\s]?\d{3,4}[-.\s]?\d{4}(?![\d-])"
        ),
    ),
    # 도로명주소: [시·구] 도로명 + 건물번호 (+ 동·호·층). 수치 단위가 뒤따르면 주소가 아니다.
    (
        "[주소]",
        re.compile(
            r"(?:[가-힣]{2,}(?:특별시|광역시|특별자치시|특별자치도|도|시)\s?)?"
            r"(?:[가-힣]{1,}(?:시|군|구)\s?)*"
            r"[가-힣A-Za-z0-9]{2,}(?:대로|번길|로|길)\s?\d{1,4}(?:-\d{1,4})?"
            rf"(?!\d|\s?{_UNIT})"
            r"(?:\s?\(?[가-힣0-9]{0,12}(?:동|호|층)\)?|\s?\d{1,4}(?:동|호|층)){0,3}"
        ),
    ),
    # 지번주소: ○○동 123-45(번지)
    ("[주소]", re.compile(r"[가-힣]{1,10}(?:동|리|가)\s?\d{1,5}-\d{1,4}(?:번지)?(?!\d)")),
    ("[주소]", re.compile(r"(?<!\d)\d{1,5}번지(?:\s?\d{1,4}(?:동|호|층))?")),
    ("[주소]", re.compile(r"(?<!\d)\d{1,4}동\s?\d{1,4}호")),
]

# 가린 뒤 남으면 안 되는 패턴(위 패턴보다 느슨하게). 폐기물 코드(2-2-2)와 겹치지 않는다.
_STRICT: list[tuple[str, re.Pattern[str]]] = [
    ("이메일", re.compile(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}")),
    ("사업자번호", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{5}(?!\d)")),
    ("법인·주민번호", re.compile(r"(?<!\d)\d{6}-\d{7}(?!\d)")),
    ("전화번호", re.compile(r"(?<![\d-])\+82|(?<![\d-])\d{2,4}-\d{3,4}-\d{4}(?![\d-])")),
    ("휴대폰", re.compile(r"(?<!\d)01[016-9]\d{7,8}(?!\d)")),
]


class RedactResult(BaseModel):
    text: str
    counts: dict[str, int] = {}

    @property
    def changed(self) -> bool:
        return bool(self.counts)


def find_identifiers(text: str) -> list[str]:
    """가린 결과에 남은 식별 패턴 이름 목록(엄격 검사)."""
    return [name for name, p in _STRICT if p.search(text or "")]


def redact(text: str) -> RedactResult:
    """식별 정보를 토큰으로 바꾼다. 가린 뒤에도 남으면 RedactionError."""
    try:
        out = text or ""
        counts: dict[str, int] = {}
        for token, pat in _PATTERNS:
            out, n = pat.subn(token, out)
            if n:
                counts[token] = counts.get(token, 0) + n
    except Exception as exc:  # noqa: BLE001 — 어떤 오류든 fail-closed
        raise RedactionError(f"가리기 실패: {type(exc).__name__}") from exc
    left = find_identifiers(out)
    if left:
        raise RedactionError("가린 뒤에도 식별 정보가 남음: " + ", ".join(left))
    return RedactResult(text=out, counts=counts)


def redact_obj(obj: Any, counts: dict[str, int] | None = None) -> Any:
    """dict/list 안의 모든 문자열(키 제외)을 가린다. counts에 누적."""
    if isinstance(obj, str):
        r = redact(obj)
        if counts is not None:
            for k, v in r.counts.items():
                counts[k] = counts.get(k, 0) + v
        return r.text
    if isinstance(obj, dict):
        return {k: redact_obj(v, counts) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v, counts) for v in obj]
    return obj


def sha256_text(s: str | None) -> str | None:
    return None if s is None else hashlib.sha256(s.encode("utf-8")).hexdigest()


def scrub_call(call, original_user: str, *, store_prompts: bool):
    """Trace에 남길 LLMCall 복사본. 원문 대신 (가린 프롬프트 +) 원문 해시.

    store_prompts=False면 프롬프트·응답 본문도 비우고 해시와 길이만 남긴다.
    """
    upd: dict[str, Any] = {
        "user_sha256": sha256_text(original_user),
        "user_len": len(original_user),
        "raw_sha256": sha256_text(call.raw),
        "raw_len": len(call.raw) if call.raw is not None else None,
    }
    if not store_prompts:
        upd.update(user="", raw=None, parsed=None, system="")
    return call.model_copy(update=upd)
