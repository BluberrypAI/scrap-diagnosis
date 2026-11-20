"""시험성적서 항목명 사전: 사실 키 ↔ 성적서 항목 표기. 법 판단은 담지 않는다.

설계: docs/design/test-report-table-extraction.md 5절. 샘플 성적서를 보며 표기를 보완한다.
(지금은 코드에 두고, 표기가 안정되면 knowledge/로 옮겨 빌드 대상으로 할지 정한다.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Group = Literal["leach", "content"]


@dataclass(frozen=True)
class TestItem:
    key: str
    label: str
    names: tuple[str, ...]  # 소문자·공백 없음. 2글자 이하는 낱말 단위로만 맞춘다
    group: Group | None  # 용출/함량. pH는 None
    unit: str | None  # 카탈로그 단위

    __test__ = False  # pytest가 테스트 클래스로 모으지 않게


TEST_ITEMS: tuple[TestItem, ...] = (
    TestItem("leach_pb", "납 용출", ("납", "pb"), "leach", "mg/L"),
    TestItem("leach_cu", "구리 용출", ("구리", "cu"), "leach", "mg/L"),
    TestItem("leach_as", "비소 용출", ("비소", "as"), "leach", "mg/L"),
    TestItem("leach_hg", "수은 용출", ("수은", "hg"), "leach", "mg/L"),
    TestItem("leach_cd", "카드뮴 용출", ("카드뮴", "cd"), "leach", "mg/L"),
    TestItem(
        "leach_cr6",
        "6가크롬 용출",
        ("6가크롬", "육가크롬", "크롬6가", "cr6+", "cr(vi)", "cr6"),
        "leach",
        "mg/L",
    ),
    TestItem("leach_cn", "시안 용출", ("시안", "시안화합물", "cn"), "leach", "mg/L"),
    TestItem("leach_op", "유기인 용출", ("유기인", "유기인화합물"), "leach", "mg/L"),
    TestItem(
        "leach_pce",
        "테트라클로로에틸렌 용출",
        ("테트라클로로에틸렌", "퍼클로로에틸렌", "pce"),
        "leach",
        "mg/L",
    ),
    TestItem("leach_tce", "트리클로로에틸렌 용출", ("트리클로로에틸렌", "tce"), "leach", "mg/L"),
    TestItem(
        "pcb_leach_mg_l",
        "PCB 용출",
        ("pcb", "pcbs", "폴리클로리네이티드비페닐", "폴리염화비페닐"),
        "leach",
        "mg/L",
    ),
    TestItem(
        "pcb_mg_l",
        "PCB 함량(액상)",
        ("pcb", "pcbs", "폴리클로리네이티드비페닐", "폴리염화비페닐"),
        "content",
        "mg/L",
    ),
    TestItem(
        "oil_content_pct",
        "기름성분",
        ("기름성분", "기름", "유분", "노말헥산추출물질", "n-헥산추출물질", "노말헥산추출물"),
        "content",
        "%",
    ),
    TestItem(
        "sludge_water_pct",
        "수분 함량",
        ("수분", "함수율", "수분함량", "함수량", "수분함유량"),
        "content",
        "%",
    ),
    # 오니 유기성·무기성 구분(시행규칙 별표 5: 고형물 중 유기성물질 40% 이상 = 유기성)
    TestItem(
        "sludge_organic_pct",
        "유기물 함량",
        ("유기물함량", "유기물", "유기성물질", "유기물질"),
        "content",
        "%",
    ),
    TestItem("ph", "pH", ("ph", "수소이온농도"), None, None),
)

BY_KEY = {t.key: t for t in TEST_ITEMS}

_TOKEN_SPLIT = re.compile(r"[\s()\[\]{}·,/:;]+")
LEACH_WORDS = ("용출",)
CONTENT_WORDS = ("함량", "함유량", "함유")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_SPLIT.split(text.lower()) if t}


def _name_matches(name: str, compact: str, tokens: set[str]) -> bool:
    if len(name) <= 2:
        return name in tokens or any(
            t.startswith(name) and _only_suffix(t[len(name) :]) for t in tokens
        )
    return name in compact


def _only_suffix(rest: str) -> bool:
    # "납및그화합물"처럼 붙여 쓴 경우: 짧은 이름 뒤에 '및'·'화합물'·'용출'·'함량'만 오면 같은 항목
    return rest == "" or rest.startswith(("및", "화합물", "용출", "함량"))


def match_items(text: str) -> list[TestItem]:
    """항목 칸 글자에 맞는 사전 항목들. 같은 이름(PCB)은 용출·함량 둘 다 돌려준다."""
    if not text or not text.strip():
        return []
    compact = _compact(text)
    tokens = _tokens(text)
    return [t for t in TEST_ITEMS if any(_name_matches(n, compact, tokens) for n in t.names)]


def group_hint(text: str) -> Group | None:
    """글자에 '용출'·'함량'이 있으면 그 묶음."""
    c = _compact(text or "")
    leach = any(w in c for w in LEACH_WORDS)
    content = any(w in c for w in CONTENT_WORDS)
    if leach and not content:
        return "leach"
    if content and not leach:
        return "content"
    return None
