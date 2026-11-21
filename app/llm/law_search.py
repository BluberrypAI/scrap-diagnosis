"""적재한 법령 조문 단위의 BM25 검색. 질의응답 agent의 search_law 도구가 쓴다.

형태소 분석기 없이 한국어를 다루기 위한 토큰화
- 조문 번호(제2조, 제1호, 제17조의2)와 별표 번호(별표4의3)는 통째로 한 토큰
- 영문·숫자 묶음(51-03-01, R-3-3, mg)은 통째로 한 토큰
- 한글 어절은 끝의 조사·어미를 하나 떼고(남는 글자가 2자 이상일 때만) 2글자씩 자른다.
  1글자 어절은 그대로
- 의문사로 시작하는 어절(뭐·왜·어떻게 …)은 버린다

조문 구조에서 읽을 수 있는 말을 색인에만 덧붙인다(조문 원문은 그대로).
- 정의 조항('1. "폐기물"이란 …') → 정의
- 시행규칙 별표 4 항목(51-03-01 …) → 분류번호 세부분류
- 시행규칙 별표 4의3 항목 → 재활용 가능 유형

검색어 토큰 중 조문에 있는 것의 IDF 합이 전체 IDF 합의 MIN_COVERAGE 미만이면 결과에서 뺀다.
조문에 없는 토큰도 IDF 최댓값으로 전체 합에 넣으므로, 핵심어가 적재 범위 밖이면 0건이 된다.
값은 knowledge/law/search_eval.yaml dev로 정했다(tools/eval_law_search.py).
"""

from __future__ import annotations

import math
import re
from collections import Counter

K1 = 1.2
B = 0.75
MIN_COVERAGE = 0.3

_DEFINITION = re.compile(r'^\d+(?:의\d+)?\.\s*"[^"]+"(?:이)?란')
_CODE = re.compile(r"^\d\d-\d\d")

_ARTICLE = r"제\d+(?:조|항|호|목)(?:의\d+)?|별표\s*\d+(?:의\d+)?"
_TOKEN = re.compile(rf"{_ARTICLE}|[0-9a-z]+(?:[-./][0-9a-z]+)*|[가-힣]+")
_QUESTION = re.compile(r"^(?:뭐|뭔|왜|어떻게|어떤|어디|무엇|무슨|언제|얼마)")
_ENDINGS = sorted(
    (
        "이에요 예요 에요 인가요 이나요 되나요 하나요 할까요 있나요 있어요 나요 돼요 해요 "
        "이라는 이란 이면 으로 에서 이랑 하고 랑 란 과 와 은 는 이 가 을 를 의 도 에 로 요"
    ).split(),
    key=len,
    reverse=True,
)


def _strip(word: str) -> str:
    for e in _ENDINGS:
        if word.endswith(e) and len(word) - len(e) >= 2:
            return word[: -len(e)]
    return word


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN.findall((text or "").lower()):
        if re.fullmatch(_ARTICLE, tok):
            out.append(re.sub(r"\s+", "", tok))
        elif not re.fullmatch(r"[가-힣]+", tok):
            out.append(tok)
        elif _QUESTION.match(tok):
            continue
        else:
            w = _strip(tok)
            out.extend([w] if len(w) == 1 else [w[i : i + 2] for i in range(len(w) - 1)])
    return out


def structure_tags(unit: dict) -> str:
    tags = []
    if _DEFINITION.match(unit["text"]):
        tags.append("정의")
    if "/별표4/" in unit["id"] and _CODE.match(unit["text"]):
        tags.append("분류번호 세부분류")
    if "/별표4의3/" in unit["id"] and _CODE.match(unit["text"]):
        tags.append("재활용 가능 유형")
    return " ".join(tags)


class LawIndex:
    def __init__(self, units: list[dict]) -> None:
        self.units = units
        self.tfs = [Counter(tokenize(f"{u['ref']} {structure_tags(u)} {u['text']}")) for u in units]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = sum(self.lens) / len(self.lens) if self.lens else 0.0
        n = len(units)
        df = Counter(t for tf in self.tfs for t in tf)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self.idf_unseen = math.log(1 + (n + 0.5) / 0.5)

    def search(self, query: str, k: int = 3) -> list[dict]:
        terms = set(tokenize(query))
        if not terms:
            return []
        total = sum(self.idf.get(t, self.idf_unseen) for t in terms)
        scored = []
        for i, tf in enumerate(self.tfs):
            hit = [t for t in terms if t in tf]
            if not hit or sum(self.idf[t] for t in hit) / total < MIN_COVERAGE:
                continue
            norm = K1 * (1 - B + B * self.lens[i] / self.avg)
            score = sum(self.idf[t] * tf[t] * (K1 + 1) / (tf[t] + norm) for t in hit)
            scored.append((score, i))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [self.units[i] for _, i in scored[:k]]
