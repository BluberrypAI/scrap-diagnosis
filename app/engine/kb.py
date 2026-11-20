"""엔진이 읽는 지식 묶음: 판정 규칙·문진 계획·사실 카탈로그·결과 안내·법령 이름.

kb_version은 knowledge/flow/*.yaml과 법령 목록(manifest)의 해시다. 규칙이 바뀌면 값이 바뀌고,
진행 중인 건은 KB_CHANGED로 멈춘 뒤 rebase로 지금 규칙에 맞춘다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.engine.flow import Stage, load_flow
from app.engine.planner import Plan, load_plan

ROOT = Path(__file__).resolve().parents[2]
FLOW_DIR = ROOT / "knowledge" / "flow"
MANIFEST = ROOT / "knowledge" / "law" / "manifest.yaml"


@dataclass(frozen=True)
class KB:
    stages: list[Stage]
    plan: Plan
    outcomes: dict
    law_names: dict[str, str]
    version: str
    as_of_law: dict[str, str]  # 법령 키 → 시행일(YYYYMMDD)


def kb_version(flow_dir: Path = FLOW_DIR, manifest: Path = MANIFEST) -> str:
    h = hashlib.sha256()
    for p in sorted(flow_dir.glob("*.yaml")) + [manifest]:
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


@lru_cache
def load_kb(flow_dir: Path = FLOW_DIR, manifest: Path = MANIFEST) -> KB:
    docs = yaml.safe_load(manifest.read_text(encoding="utf-8"))["documents"]
    outcomes = yaml.safe_load((flow_dir / "outcomes.yaml").read_text(encoding="utf-8"))
    stages = load_flow(flow_dir)
    used = {r.then.get("outcome") for s in stages for r in s.rules if isinstance(r.then, dict)}
    missing = used - set(outcomes["outcomes"])
    if missing:
        raise ValueError(f"outcomes.yaml에 결과 안내가 없음: {sorted(missing)}")
    return KB(
        stages=stages,
        plan=load_plan(flow_dir),
        outcomes=outcomes,
        law_names={d["key"]: d["name"] for d in docs},
        version=kb_version(flow_dir, manifest),
        as_of_law={d["key"]: str(d.get("effective_date") or "") for d in docs},
    )
