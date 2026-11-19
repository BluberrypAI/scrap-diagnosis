"""받침에 맞는 조사 고르기. 템플릿이 '을(를)'처럼 괄호 조사를 쓰지 않게 한다.

괄호로 끝나는 말은 괄호 앞 낱말을 기준으로 한다("설치허가증(신고증명서)" → "설치허가증"을 본다).
숫자와 영문은 읽는 소리로 판단한다(1 → 일, M → 엠).
"""

from __future__ import annotations

_HANGUL_FIRST, _HANGUL_LAST = 0xAC00, 0xD7A3
_RIEUL = 8  # 종성 인덱스 ㄹ

# 숫자 끝소리: 받침 없음 None, ㄹ받침 "ㄹ", 그 밖의 받침 "x"
_DIGIT = {"0": "x", "1": "ㄹ", "2": None, "3": "x", "4": None, "5": None, "6": "x", "7": "ㄹ",
          "8": "ㄹ", "9": None}  # fmt: skip
# 영문 끝소리(알파벳 이름으로 읽을 때): L 엘, R 알 → ㄹ / M 엠, N 엔 → 받침
_LATIN = {"l": "ㄹ", "r": "ㄹ", "m": "x", "n": "x"}

_PAIRS = {
    "을": ("을", "를"),
    "를": ("을", "를"),
    "은": ("은", "는"),
    "는": ("은", "는"),
    "이": ("이", "가"),
    "가": ("이", "가"),
    "과": ("과", "와"),
    "와": ("과", "와"),
    "으로": ("으로", "로"),
    "로": ("으로", "로"),
}


def _strip_tail(word: str) -> str:
    """끝의 공백·문장부호·괄호 묶음을 걷어 낸다."""
    s = word.rstrip()
    while s:
        if s[-1] == ")":
            depth, i = 0, len(s) - 1
            while i >= 0:
                if s[i] == ")":
                    depth += 1
                elif s[i] == "(":
                    depth -= 1
                    if depth == 0:
                        break
                i -= 1
            if i <= 0:  # 짝이 없거나 전체가 괄호면 괄호만 뗀다
                s = s[:-1].rstrip()
                continue
            s = s[:i].rstrip()
        elif s[-1] in " .,·'\"」』]}":
            s = s[:-1].rstrip()
        else:
            break
    return s


def _final(word: str) -> str | None:
    """끝소리. 받침 없음 None, ㄹ받침 'ㄹ', 그 밖의 받침 'x'. 판단할 수 없으면 None."""
    s = _strip_tail(word)
    if not s:
        return None
    ch = s[-1]
    code = ord(ch)
    if _HANGUL_FIRST <= code <= _HANGUL_LAST:
        jong = (code - _HANGUL_FIRST) % 28
        if jong == 0:
            return None
        return "ㄹ" if jong == _RIEUL else "x"
    if ch.isdigit():
        return _DIGIT[ch]
    if ch == "%":  # 퍼센트
        return None
    return _LATIN.get(ch.lower())


def josa(word: str, particle: str) -> str:
    """`word` 뒤에 붙일 조사. particle은 을/를, 은/는, 이/가, 과/와, 으로/로 중 아무 쪽이나 준다."""
    with_final, without = _PAIRS[particle]
    end = _final(word)
    if with_final == "으로":
        return "으로" if end == "x" else "로"
    return with_final if end else without


def attach(word: str, particle: str) -> str:
    """`word`에 맞는 조사를 붙인 문자열."""
    return f"{word}{josa(word, particle)}"
