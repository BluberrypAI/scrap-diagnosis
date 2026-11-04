"""규칙 표(rules/*.yaml)를 읽어 검증된 지식베이스로 만든다."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = ROOT / "rules"

COST_RANK = {"USER": 0, "DOCUMENT": 1, "TEST": 2}
OPS = {"eq", "ne", "in", "not_in", "gte", "gt", "lte", "lt"}
NUMERIC_OPS = {"gte", "gt", "lte", "lt"}


@dataclass(frozen=True)
class Condition:
    fact: str
    op: str
    value: Any


@dataclass
class Rule:
    id: str
    stage: str
    concludes: str
    when: list[Condition]
    source: str
    location: str
    quote: str
    review: str
    complement_of: list[str] | None = None
    supporting: list[dict] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)  # 이 규칙이 기대는, 아직 확인하지 못한 근거
    item: str | None = None  # 결론의 세부 품목(예: 폐산, 폐유)


@dataclass
class KB:
    facts: dict[str, dict]
    stages: dict[str, dict]
    rules: list[Rule]
    sources: dict[str, dict]
    version: str
    annex4: dict = field(default_factory=dict)   # 별표 4 번호 표
    s4_map: dict = field(default_factory=dict)   # 앞 단계 → 별표 4 대응표
    annex43: dict = field(default_factory=dict)  # 별표 4의3 재활용 가능 유형 표
    r_codes: dict = field(default_factory=dict)  # 별표 4의2 R코드 정의
    s5_rules: dict = field(default_factory=dict)  # 재활용 금지·제한

    def rules_for(self, stage: str) -> list[Rule]:
        return [r for r in self.rules if r.stage == stage]


def _load_yaml(name: str, rules_dir: Path) -> Any:
    with open(rules_dir / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_kb(rules_dir: Path = RULES_DIR) -> KB:
    facts = _load_yaml("facts.yaml", rules_dir)
    rules_doc = _load_yaml("rules.yaml", rules_dir)
    sources = _load_yaml("sources.yaml", rules_dir)
    extra_files = sorted(rules_dir.glob("rules_*.yaml"))
    raw_rules = list(rules_doc["rules"])
    for p in extra_files:
        raw_rules += _load_yaml(p.name, rules_dir)["rules"]
    digest = hashlib.sha256()
    annex4 = _load_yaml("annex4_codes.yaml", rules_dir)
    s4_map = _load_yaml("s4_map.yaml", rules_dir)
    annex43 = _load_yaml("annex43.yaml", rules_dir)
    r_codes = _load_yaml("r_codes.yaml", rules_dir)
    s5_rules = _load_yaml("s5_rules.yaml", rules_dir)
    _fill_values(facts, annex4, s4_map)
    for name in ["facts.yaml", "rules.yaml", "sources.yaml", "annex4_codes.yaml", "s4_map.yaml", "annex43.yaml",
                 "r_codes.yaml", "s5_rules.yaml"] + [p.name for p in extra_files]:
        digest.update((rules_dir / name).read_bytes())

    rules = []
    for raw in raw_rules:
        comp = raw.get("complement_of")
        rules.append(
            Rule(
                id=raw["id"],
                stage=raw["stage"],
                concludes=raw["concludes"],
                when=[Condition(c["fact"], c["op"], c["value"]) for c in raw.get("when", [])],
                source=raw["source"],
                location=raw["location"],
                quote=raw["quote"],
                review=raw.get("review", "UNVERIFIED"),
                complement_of=[comp] if isinstance(comp, str) else comp,
                supporting=raw.get("supporting", []),
                gaps=raw.get("gaps", []),
                item=raw.get("item"),
            )
        )
    kb = KB(facts=facts, stages=rules_doc["stages"], rules=rules, sources=sources,
            version="rules-" + digest.hexdigest()[:12], annex4=annex4, s4_map=s4_map,
            annex43=annex43, r_codes=r_codes, s5_rules=s5_rules)
    validate_kb(kb)
    return kb


def general_units(annex4: dict) -> dict[str, str]:
    """사업장일반폐기물의 선택 단위: 중분류(51-xx) 또는 중분류 없이 홀로 있는 번호(51-16-00 등)."""
    names = {g["id"]: g["name"] for g in annex4["groups"] if g["section"] == "GENERAL"}
    units: dict[str, str] = {}
    for c in annex4["codes"]:
        if c["section"] != "GENERAL":
            continue
        prefix = c["id"][:5]
        units.setdefault(prefix, names.get(prefix) or c["name"])
    return units


def _fill_values(facts: dict, annex4: dict, s4_map: dict) -> None:
    excluded = set(s4_map.get("excluded_codes", []))
    for f in facts.values():
        src = f.get("values_from")
        if src == "annex4_general_groups":
            f["values"] = {k: f"{k} {v}" for k, v in general_units(annex4).items()}
        elif src == "annex4_codes":
            f["values"] = {c["id"]: f"{c['id']} {c['name']}" for c in annex4["codes"]
                           if c["section"] in {"DESIGNATED", "GENERAL"} and c["id"] not in excluded}


def validate_kb(kb: KB) -> None:
    """규칙 표의 형식 오류를 시작할 때 잡는다."""
    errors: list[str] = []
    ids = [r.id for r in kb.rules]
    if len(ids) != len(set(ids)):
        errors.append("중복된 규칙 id")
    for fid, f in kb.facts.items():
        if f.get("type") not in {"bool", "enum", "number"}:
            errors.append(f"{fid}: type 오류")
        if f.get("cost") not in COST_RANK:
            errors.append(f"{fid}: cost 오류")
        if f.get("derived_from") and f["derived_from"] not in kb.stages:
            errors.append(f"{fid}: derived_from 단계 없음")
        if f.get("type") == "enum" and not f.get("values"):
            errors.append(f"{fid}: enum 값 없음")
    for r in kb.rules:
        stage = kb.stages.get(r.stage)
        if stage is None:
            errors.append(f"{r.id}: 없는 단계 {r.stage}")
            continue
        if r.concludes not in stage.get("candidates", {}):
            errors.append(f"{r.id}: 단계에 없는 결론 {r.concludes}")
        if r.source not in kb.sources:
            errors.append(f"{r.id}: 없는 출처 {r.source}")
        if r.complement_of:
            if r.when:
                errors.append(f"{r.id}: complement 규칙은 when을 가질 수 없음")
            for t in r.complement_of:
                if t not in stage["candidates"]:
                    errors.append(f"{r.id}: complement 대상 없음 {t}")
        elif not r.when:
            errors.append(f"{r.id}: 조건 없음")
        for c in r.when:
            f = kb.facts.get(c.fact)
            if f is None:
                errors.append(f"{r.id}: 없는 사실 {c.fact}")
                continue
            if c.op not in OPS:
                errors.append(f"{r.id}: 연산자 오류 {c.op}")
            if f["type"] == "number" and c.op not in NUMERIC_OPS | {"eq", "ne"}:
                errors.append(f"{r.id}: 숫자 사실에 맞지 않는 연산자")
            if f["type"] != "number" and c.op in NUMERIC_OPS:
                errors.append(f"{r.id}: 숫자가 아닌 사실에 비교 연산자")
            if f["type"] == "enum":
                vals = c.value if c.op in {"in", "not_in"} else [c.value]
                for v in vals:
                    if v not in f["values"]:
                        errors.append(f"{r.id}: {c.fact}에 없는 값 {v}")
    for sid, stage in kb.stages.items():
        for c in stage.get("candidates", {}).values():
            for o in c.get("overrides", []):
                if o not in stage["candidates"]:
                    errors.append(f"{sid}: overrides 대상 없음 {o}")
            nxt = c.get("next")
            if nxt and nxt not in kb.stages:
                errors.append(f"{sid}: 없는 다음 단계 {nxt}")
        for fid in stage.get("question_order", []):
            if fid not in kb.facts:
                errors.append(f"{sid}: question_order에 없는 사실 {fid}")
    if errors:
        raise ValueError("규칙 표 오류:\n" + "\n".join(errors))
