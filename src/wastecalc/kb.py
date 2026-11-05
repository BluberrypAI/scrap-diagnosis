"""규칙 표(rules/*.yaml)를 읽어 검증된 지식베이스로 만든다."""
from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from datetime import date
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
    effective_from: str | None = None  # 규칙 자체의 유효 기간(없으면 근거 원문의 기간을 따름)
    effective_to: str | None = None
    abolished: bool = False  # 법 개정으로 의도적으로 없어진 규칙(그 뒤 날짜에 빠져도 '누락'이 아님)
    plain: str | None = None  # 쉬운 설명(법적 효력 없음, 원문이 우선)


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
    as_of: str | None = None  # 이 지식베이스가 적용되는 기준일
    glossary: dict = field(default_factory=dict)  # 용어 풀이
    consult: dict = field(default_factory=dict)  # 해석이 필요할 때 안내할 문의처
    reporting: dict = field(default_factory=dict)
    materials: dict = field(default_factory=dict)  # 소재 카탈로그(rules/materials.yaml) — 법 판단 없음
    unavailable: dict = field(default_factory=dict)  # 기준일에 판정할 수 없는 단계 → 이유
    _base: dict = field(default_factory=dict, repr=False, compare=False)

    def rules_for(self, stage: str) -> list[Rule]:
        return [r for r in self.rules if r.stage == stage]

    def at(self, as_of=None) -> "KB":
        """기준일에 유효한 규칙·표만 담은 지식베이스(같은 원본에서 만든 보기)."""
        d = parse_date(as_of)
        views = self._base["_views"]
        if d.isoformat() not in views:
            views[d.isoformat()] = _view(self._base, d)
        return views[d.isoformat()]


def parse_date(v) -> date:
    if v is None:
        return date.today()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v))
    except ValueError as e:
        raise ValueError(f"기준일은 YYYY-MM-DD 형식이어야 합니다: {v!r}") from e


def window_valid(start, end, d: date) -> bool:
    return ((start is None or date.fromisoformat(str(start)) <= d)
            and (end is None or d <= date.fromisoformat(str(end))))


def source_valid(src: dict, d: date) -> bool:
    """근거 원문이 기준일에 유효한가. effective_on(시작) ~ effective_to(인용 문언이 바뀌기 전날)."""
    return window_valid(src.get("effective_on"), src.get("effective_to"), d)


def rule_valid(rule: "Rule", sources: dict, d: date) -> bool:
    if rule.effective_from or rule.effective_to:
        return window_valid(rule.effective_from, rule.effective_to, d)
    return source_valid(sources[rule.source], d)


def _pick_table(versions: list, sources: dict, d: date):
    valid = [v for v in versions if source_valid(sources[v["source"]], d)]
    if len(valid) == 1:
        return valid[0], None
    if not valid:
        return None, "기준일에 유효한 판이 없음"
    return None, "기준일에 유효한 판이 둘 이상(유효 기간 겹침)"


def _view(base: dict, d: date) -> "KB":
    sources = base["sources"]
    rules = [r for r in base["rules"] if rule_valid(r, sources, d)]
    unavailable: dict = {}
    # 단계 완전성: 어떤 규칙 id도 기준일에 유효한 판이 하나도 없으면(폐지 표시 제외) 그 단계는 판정하지 않는다.
    # 일부 규칙만 빠진 채 판정하면 '나머지 모두 아님' 결론(complement)이 틀릴 수 있다.
    valid_ids = {r.id for r in rules}
    for r in base["rules"]:
        if r.id not in valid_ids and not r.abolished and r.stage not in unavailable:
            unavailable[r.stage] = f"규칙 {r.id}의 근거({r.source})가 기준일에 유효하지 않음"
    annex4, why4 = _pick_table(base["annex4_versions"], sources, d)
    annex43, why43 = _pick_table(base["annex43_versions"], sources, d)
    r_codes, whyr = _pick_table(base["r_codes_versions"], sources, d)
    if why4:
        unavailable.setdefault("S4", f"별표 4 번호표: {why4}")
    if why43 or whyr:
        unavailable.setdefault("S5", f"재활용 유형표: {why43 or whyr}")
    s5 = copy.deepcopy(base["s5_rules"])
    s5["prohibitions"] = [p for p in s5["prohibitions"]
                          if all(source_valid(sources[b["source"]], d) for b in p["basis"])]
    facts = copy.deepcopy(base["facts"])
    empty4 = {"groups": [], "codes": []}
    _fill_values(facts, annex4 or empty4, base["s4_map"], base.get("materials", {}))
    return KB(facts=facts, stages=base["stages"], rules=rules, sources=sources, version=base["version"],
              annex4=annex4 or empty4, s4_map=base["s4_map"], annex43=annex43 or {"rows": []},
              r_codes=r_codes or {"codes": {}, "quotes": {}}, s5_rules=s5,
              as_of=d.isoformat(), unavailable=unavailable, glossary=base.get("glossary", {}), consult=base.get("consult", {}),
              reporting=base.get("reporting", {}), materials=base.get("materials", {}), _base=base)


def _load_yaml(name: str, rules_dir: Path) -> Any:
    with open(rules_dir / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_kb(rules_dir: Path = RULES_DIR, as_of=None) -> KB:
    """규칙 표를 읽는다. 기준일(as_of, 기본 오늘)에 유효한 규칙만 담은 보기를 돌려주며, .at(날짜)로 다른 날짜의 보기를 얻는다."""
    facts = _load_yaml("facts.yaml", rules_dir)
    rules_doc = _load_yaml("rules.yaml", rules_dir)
    sources = _load_yaml("sources.yaml", rules_dir)
    extra_files = sorted(rules_dir.glob("rules_*.yaml"))
    raw_rules = list(rules_doc["rules"])
    for p in extra_files:
        raw_rules += _load_yaml(p.name, rules_dir)["rules"]
    digest = hashlib.sha256()
    # 자동 생성 표는 판별로 여러 파일을 둘 수 있다(annex4_codes*.yaml 등). 파일의 source로 유효 기간을 정한다.
    table_files = {"annex4": sorted(rules_dir.glob("annex4_codes*.yaml")),
                   "annex43": sorted(rules_dir.glob("annex43*.yaml")),
                   "r_codes": sorted(rules_dir.glob("r_codes*.yaml"))}
    versions = {k: [_load_yaml(p.name, rules_dir) for p in files] for k, files in table_files.items()}
    s4_map = _load_yaml("s4_map.yaml", rules_dir)
    s5_rules = _load_yaml("s5_rules.yaml", rules_dir)
    glossary = _load_yaml("glossary.yaml", rules_dir) if (rules_dir / "glossary.yaml").exists() else {}
    consult = _load_yaml("consult.yaml", rules_dir) if (rules_dir / "consult.yaml").exists() else {}
    reporting = _load_yaml("reporting.yaml", rules_dir) if (rules_dir / "reporting.yaml").exists() else {}
    materials = _load_yaml("materials.yaml", rules_dir) if (rules_dir / "materials.yaml").exists() else {}
    names = ["facts.yaml", "rules.yaml", "sources.yaml", "s4_map.yaml", "s5_rules.yaml"]
    if reporting:
        names.append("reporting.yaml")
    if materials:
        names.append("materials.yaml")
    names += [p.name for files in table_files.values() for p in files] + [p.name for p in extra_files]
    for name in names:
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
                effective_from=raw.get("effective_from"),
                effective_to=raw.get("effective_to"),
                abolished=raw.get("abolished", False),
                plain=raw.get("plain"),
            )
        )
    base = {"facts": facts, "stages": rules_doc["stages"], "rules": rules, "sources": sources,
            "version": "rules-" + digest.hexdigest()[:12], "s4_map": s4_map, "s5_rules": s5_rules,
            "annex4_versions": versions["annex4"], "annex43_versions": versions["annex43"],
            "r_codes_versions": versions["r_codes"], "glossary": glossary, "consult": consult, "reporting": reporting, "materials": materials, "_views": {}}
    _validate_versions(base)
    kb = _view(base, parse_date(as_of))
    base["_views"][kb.as_of] = kb
    validate_kb(kb)
    return kb


def _validate_versions(base: dict) -> None:
    errors = []
    for sid, src in base["sources"].items():
        a, b = src.get("effective_on"), src.get("effective_to")
        if a and b and date.fromisoformat(str(b)) < date.fromisoformat(str(a)):
            errors.append(f"{sid}: effective_to가 effective_on보다 앞섬")
    for k in ("annex4_versions", "annex43_versions", "r_codes_versions"):
        for v in base[k]:
            if v.get("source") not in base["sources"]:
                errors.append(f"{k}: 없는 출처 {v.get('source')}")

    def win(r):
        if r.effective_from or r.effective_to:
            return r.effective_from, r.effective_to
        s = base["sources"][r.source]
        return s.get("effective_on"), s.get("effective_to")

    by_id: dict = {}
    for r in base["rules"]:
        by_id.setdefault(r.id, []).append(r)
    for rid, rs in by_id.items():
        spans = sorted((date.fromisoformat(str(f)) if f else date.min, date.fromisoformat(str(t)) if t else date.max)
                       for f, t in map(win, rs))
        for (_, end1), (start2, _) in zip(spans, spans[1:]):
            if start2 <= end1:
                errors.append(f"{rid}: 같은 규칙의 여러 판이 유효 기간이 겹침")
    if errors:
        raise ValueError("판(版) 정보 오류:\n" + "\n".join(errors))


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


def _fill_values(facts: dict, annex4: dict, s4_map: dict, materials: dict | None = None) -> None:
    excluded = set(s4_map.get("excluded_codes", []))
    for f in facts.values():
        src = f.get("values_from")
        if src == "annex4_general_groups":
            f["values"] = {k: f"{k} {v}" for k, v in general_units(annex4).items()}
        elif src == "annex4_codes":
            f["values"] = {c["id"]: f"{c['id']} {c['name']}" for c in annex4["codes"]
                           if c["section"] in {"DESIGNATED", "GENERAL"} and c["id"] not in excluded}
        elif src == "materials" and materials:
            cat, groups = materials.get("materials", {}), materials.get("groups", {})
            f["values"] = {mid: m["label"] for mid, m in cat.items()}
            f["value_groups"] = {}
            for mid, m in cat.items():
                f["value_groups"].setdefault(groups.get(m.get("group"), {}).get("label", m.get("group", "기타")), []).append(mid)
            f["value_hints"] = {mid: ", ".join(m["aliases"]) for mid, m in cat.items() if m.get("aliases")}


def validate_kb(kb: KB) -> None:
    """규칙 표의 형식 오류를 시작할 때 잡는다."""
    errors: list[str] = []
    ids = [r.id for r in kb.rules]
    if len(ids) != len(set(ids)):
        errors.append("기준일에 같은 규칙 id가 둘 이상 유효함")
    for fid, f in kb.facts.items():
        if f.get("type") not in {"bool", "enum", "number"}:
            errors.append(f"{fid}: type 오류")
        if f.get("cost") not in COST_RANK:
            errors.append(f"{fid}: cost 오류")
        if f.get("derived_from") and f["derived_from"] not in kb.stages:
            errors.append(f"{fid}: derived_from 단계 없음")
        if f.get("type") == "enum" and not f.get("values"):
            errors.append(f"{fid}: enum 값 없음")
        if f.get("value_groups"):
            grouped = [v for vs in f["value_groups"].values() for v in vs]
            if sorted(grouped) != sorted(f.get("values", {})):
                errors.append(f"{fid}: value_groups가 값을 정확히 한 번씩 담지 않음")
        for v in f.get("value_hints", {}):
            if v not in f.get("values", {}):
                errors.append(f"{fid}: value_hints에 없는 값 {v}")
    errors += _validate_materials(kb)
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


def material(kb: KB, answers: dict) -> dict | None:
    """답에서 고른 소재의 카탈로그 항목(없거나 '모름'이면 None)."""
    a = answers.get("material")
    if a is None or getattr(a, "kind", None) != "VALUE":
        return None
    m = kb.materials.get("materials", {}).get(a.values[0])
    return {"id": a.values[0], **m} if m else None


def _validate_materials(kb: KB) -> list[str]:
    errors: list[str] = []
    cat = kb.materials.get("materials", {}) if kb.materials else {}
    if not cat:
        return errors
    ids = [c["id"] for c in kb.annex4.get("codes", [])]
    kinds = kb.facts.get("waste_kind", {}).get("values", {})
    for mid, m in cat.items():
        if m.get("group") not in kb.materials.get("groups", {}):
            errors.append(f"소재 {mid}: 없는 묶음 {m.get('group')}")
        if m.get("unlisted"):
            continue
        if m.get("code_needs_test") and m["code_needs_test"] not in kb.materials.get("code_tests", {}):
            errors.append(f"소재 {mid}: 없는 시험 안내 {m['code_needs_test']}")
        if m.get("waste_kind") not in kinds:
            errors.append(f"소재 {mid}: waste_kind 값 오류 {m.get('waste_kind')}")
        for sec, prefixes in (m.get("codes") or {}).items():
            if sec not in {"GENERAL", "DESIGNATED"}:
                errors.append(f"소재 {mid}: 구분 오류 {sec}")
            for p in prefixes:
                if not any(i.startswith(p) for i in ids):
                    errors.append(f"소재 {mid}: 별표 4에 없는 번호 {p}")
        for fid, v in (m.get("presets") or {}).items():
            f = kb.facts.get(fid)
            if f is None:
                errors.append(f"소재 {mid}: 없는 사실 {fid}")
            elif f["type"] == "enum" and v not in f.get("values", {}):
                errors.append(f"소재 {mid}: {fid}에 없는 값 {v}")
            elif f["type"] == "bool" and not isinstance(v, bool):
                errors.append(f"소재 {mid}: {fid}는 예/아니오 값이어야 함")
    return errors
