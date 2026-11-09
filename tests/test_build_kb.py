"""규칙 빌드(tools/build_kb.py).

data/real/이 knowledge/로 만든 결과와 같은지, 생성 규칙에 원본 추적 필드가 있는지 본다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_kb  # noqa: E402


def test_generated_data_matches_knowledge():
    """data/real/을 손으로 고쳤거나 knowledge/를 고치고 다시 빌드하지 않았으면 실패한다."""
    assert build_kb.check(build_kb.KNOWLEDGE, build_kb.OUT) == []


def test_every_rule_points_to_its_source_rule(real_kb):
    rules = [r for t in real_kb.tables for r in t.rules]
    assert rules and all(r.source_rule for r in rules)
    oil = [r for r in rules if r.source_rule == "S3-6-OIL-5PCT"]
    assert len({r.rule_id.split(":")[0] for r in oil}) == 87  # 원본 1개 → 소재 테이블 87개
    assert {(b.source_id, b.location) for b in oil[0].basis} >= {("DEC-A1", "별표 1 제6호")}


def test_every_basis_has_a_location(real_kb):
    rules = [r for t in real_kb.tables for r in t.rules]
    missing = [(r.rule_id, b.ref) for r in rules for b in r.basis if not b.location]
    assert missing == []
