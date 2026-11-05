"""답 수정 시의 재확인 정책과 로컬 문진 저장. 법적 판정은 engine에 둔다."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .engine import LEGACY_FATE, UNKNOWN, parse_answers, upgrade_legacy
from .kb import KB


def revise_answers(kb: KB, old: dict, patch: dict) -> tuple[dict, dict]:
    """기존 답의 전제 변경 시 후속 값을 판정에서 빼고 원래 값을 재확인용으로 돌려준다."""
    old = upgrade_legacy(old)
    patch = dict(patch)
    before = parse_answers(kb, old)
    if any(f in patch for f in LEGACY_FATE):
        if "material_fate" in patch:
            patch = upgrade_legacy(patch)
        else:
            fate = before.get("material_fate")
            value = fate.values[0] if fate is not None and fate.kind == "VALUE" else UNKNOWN
            legacy = {"no_longer_needed": UNKNOWN if value == UNKNOWN else value != "still_used",
                      "direct_reinput": value == "same_process_reinput",
                      "continuous_feedstock": value == "continuous_feedstock"}
            legacy.update({f: v for f, v in patch.items() if f in LEGACY_FATE})
            patch = {**{f: v for f, v in patch.items() if f not in LEGACY_FATE}, **upgrade_legacy(legacy)}
    trial = {**old, **patch}
    trial = {k: v for k, v in trial.items() if v is not None}
    parsed = parse_answers(kb, trial)  # 잘못된 변경은 이전 답을 손대기 전에 거부
    def identity(a):
        return (a.kind, a.values) if a is not None else None

    changed = {f for f in patch if identity(before.get(f)) != identity(parsed.get(f))}
    # AND 조건의 나열 순서는 사실 간 의존성이 아니다. 독립 관찰 사실은 유지한다.
    independent = {"waste_kind", "physical_state", "designated_residue", "oil_presence",
                   "pcb_possible", "toxic_chemical_discard"}
    kind_details = {c.fact for r in kb.rules_for("S3") if any(c.fact == "waste_kind" for c in r.when)
                    for c in r.when} - independent
    # 소재를 바꾸면 폐기물 종류와 소재가 정하던 사실이 함께 바뀌므로, 그 종류에 딸린 세부 답과 상태를 다시 확인한다.
    material_questions = set(kb.s4_map.get("general_material_questions", {}).values())
    dependencies = {"material": kind_details | material_questions | {"general_group", "physical_state", "waste_kind"},
                    "waste_kind": kind_details | {"general_group"},
                    "physical_state": {f for f, conf in kb.facts.items() if conf.get("cost") == "TEST"},
                    "pcb_possible": {"pcb_mg_l", "pcb_leach_mg_l"},
                    "oil_presence": {"oil_content_pct"}, "designated_residue": {"residue_kind"},
                    "residue_kind": {"oil_content_pct", "ph"}}
    affected = set()
    reporting_dependent = {f for f in kb.facts if f.startswith("reporting_")} - {"reporting_shared", "reporting_intermediate"}
    for f in changed:
        # 이미 확인한 전제를 고쳤을 때만 측정값·세부 사실을 재확인한다.
        if f in before:
            affected.update(dependencies.get(f, set()))
            if not f.startswith("reporting_"):
                affected.update(reporting_dependent)
        if f.startswith("reporting_"):
            continue
        # 처음 답한 사실은 전제를 바꾼 것이 아니다. 미리 넣은 분류번호(예: 기존 신고서 번호)를 지우지 않는다.
        # 새 답과 그 번호가 맞지 않으면 엔진이 CODE_MISMATCH로 알린다.
        if f in before and f not in {"code", "no_specific_code_applies"}:
            affected.update({"code", "no_specific_code_applies"})
        elif f == "code":
            affected.add("no_specific_code_applies")
    affected.difference_update(patch)  # 이번 배치에서 명시적으로 확인한 답은 유지
    invalidated = {f: trial.pop(f) for f in sorted(affected) if f in trial}
    return trial, invalidated


def _connection(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL)")
    except Exception:
        conn.close()
        raise
    return conn


def save_session(path: Path, sid: str, state: dict) -> None:
    conn = _connection(path)
    try:
        with conn:
            conn.execute("INSERT INTO sessions(id,state) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
                         (sid, json.dumps(state, ensure_ascii=False)))
    finally:
        conn.close()


def load_session(path: Path, sid: str) -> dict | None:
    if not path.exists():
        return None
    conn = _connection(path)
    try:
        row = conn.execute("SELECT state FROM sessions WHERE id=?", (sid,)).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()
