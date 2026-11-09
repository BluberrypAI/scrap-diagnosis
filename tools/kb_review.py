"""규칙 검토 단위·내용 해시·검토 기록(knowledge/reviews.yaml).

build_kb.py와 review_kit.py가 함께 쓴다.

검토 단위
- 법 규칙: 원본 규칙 ID 그대로(예: S3-6-OIL-5PCT). knowledge/law_rules/*.yaml
- 소재: `material:<소재 id>`(예: material:pp). knowledge/materials.yaml
- 번호 대응표: `code_map`. knowledge/code_map.yaml 전체

내용 해시는 단위의 내용(원본의 `review` 필드는 뺌)으로 만든다. 검토한 뒤 내용이 바뀌면 해시가 달라져
그 검토는 효력이 없어진다(상태 STALE, 생성 규칙에는 UNVERIFIED).
생성 규칙 하나는 여러 단위에 기대므로(예: 지정폐기물 규칙 = 법 규칙 + 소재 + 번호 대응표)
기대는 단위가 모두 VERIFIED일 때만 VERIFIED다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

STATUSES = ("VERIFIED", "NEEDS_CHANGE", "REJECTED")
STATUS_LABEL = {
    "VERIFIED": "맞음",
    "NEEDS_CHANGE": "고쳐야 함",
    "REJECTED": "틀림",
    "UNVERIFIED": "검토 전",
    "STALE": "검토 후 바뀜(다시 검토)",
}
# CSV에 한국어로 적어도 받는다
STATUS_ALIASES = {
    "맞음": "VERIFIED",
    "고쳐야 함": "NEEDS_CHANGE",
    "고쳐야함": "NEEDS_CHANGE",
    "틀림": "REJECTED",
    **{s: s for s in STATUSES},
}
CODE_MAP_UNIT = "code_map"
MATERIAL_PREFIX = "material:"


def content_hash(obj: Any) -> str:
    """단위 내용의 해시(앞 12자리). 키 순서·들여쓰기와 무관하다."""
    if isinstance(obj, dict):
        obj = {k: v for k, v in obj.items() if k != "review"}
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class Unit:
    unit: str  # 검토 단위 ID
    kind: str  # LAW_RULE | MATERIAL | CODE_MAP
    title: str
    content: Any
    hash: str


def units_from(src: Path) -> dict[str, Unit]:
    """knowledge/에서 검토 단위를 모두 읽는다."""

    def read(p: Path) -> Any:
        with p.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    out: dict[str, Unit] = {}
    for name in ("scope_and_business.yaml", "designated.yaml"):
        for r in read(src / "law_rules" / name)["rules"]:
            title = r.get("item") or r.get("plain") or r["id"]
            out[r["id"]] = Unit(r["id"], "LAW_RULE", title, r, content_hash(r))
    for mid, m in read(src / "materials.yaml")["materials"].items():
        uid = f"{MATERIAL_PREFIX}{mid}"
        out[uid] = Unit(uid, "MATERIAL", m.get("label", mid), m, content_hash(m))
    cm = read(src / "code_map.yaml")
    out[CODE_MAP_UNIT] = Unit(
        CODE_MAP_UNIT, "CODE_MAP", "법 규칙 → 별표 4 번호 범위 대응표", cm, content_hash(cm)
    )
    return out


def load_reviews(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return list(data.get("reviews") or [])


def latest_reviews(records: list[dict]) -> dict[str, dict]:
    """단위별 마지막 기록(파일 순서 기준). 여러 사람이 검토하면 기록이 여러 줄이다."""
    out: dict[str, dict] = {}
    for rec in records:
        out[rec["unit"]] = rec
    return out


def unit_status(u: Unit, latest: dict[str, dict]) -> str:
    rec = latest.get(u.unit)
    if rec is None:
        return "UNVERIFIED"
    if rec.get("content_hash") != u.hash:
        return "STALE"
    return rec["status"]


class ReviewIndex:
    """빌드 중 생성 규칙의 review 값을 정한다."""

    def __init__(self, src: Path):
        self.units = units_from(src)
        self.latest = latest_reviews(load_reviews(src / "reviews.yaml"))
        unknown = sorted(set(self.latest) - set(self.units))
        if unknown:
            raise SystemExit(f"reviews.yaml에 없는 검토 단위: {unknown}")

    def status(self, unit: str) -> str:
        return unit_status(self.units[unit], self.latest)

    def review_of(self, deps: list[str]) -> str:
        """생성 규칙의 review: 기대는 단위가 모두 VERIFIED면 VERIFIED, 아니면 UNVERIFIED."""
        for d in deps:
            if d not in self.units:
                raise SystemExit(f"검토 단위가 없음: {d}")
        ok = bool(deps) and all(self.status(d) == "VERIFIED" for d in deps)
        return "VERIFIED" if ok else "UNVERIFIED"


def dump_reviews(path: Path, records: list[dict]) -> None:
    header = (
        "# 규칙 검토 기록. 검토 결과는 review_kit.py import로 넣는다(손으로 고치지 않는다).\n"
        "# unit: 검토 단위(법 규칙 ID, material:<소재>, code_map)\n"
        "# content_hash: 검토할 때의 내용 해시\n"
        "# status: VERIFIED(맞음) | NEEDS_CHANGE(고쳐야 함) | REJECTED(틀림)\n"
        "# 내용이 바뀌면 해시가 달라져 그 검토는 효력을 잃는다. 기록은 지우지 않고 아래에 더한다.\n"
    )
    body = yaml.safe_dump({"reviews": records}, allow_unicode=True, sort_keys=False, width=110)
    path.write_text(header + body, encoding="utf-8", newline="\n")
