"""YAML 로드와 정적 검증.

검증 항목
- 규칙은 카탈로그에 있는 사실 키만 참조한다.
- 연산자와 사실 타입·값 영역이 맞는다 (예: lt는 number만, enum 값은 values 안).
- rule_id는 모든 테이블(포함 조각 포함)에서 유일하다.
- PRIORITY 테이블에서 같은 우선순위에 다른 코드가 있으면 경고한다.
- UNIQUE 테이블에서 정적으로 서로 배타임을 보일 수 없는 규칙 쌍은 경고한다.
- 코드표(codes.yaml)가 있으면 규칙 결과 코드가 코드표에 있어야 한다.
- 상위 분류(parent)가 있는 사실은 모든 값이 상위 분류 값 하나에 대응해야 한다.
- 결론 → 경로추천 안내(outcome_guidance.yaml)는 인계 계약의 모든 행과 규칙에 쓰인 모든 outcome을
  덮어야 한다. 빠진 항목이 있으면 로드가 실패한다(서버 시작 시 바로 드러남).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from app.domain.facts import FactStatus
from app.domain.handoff import ACTIONS, OUTCOMES, REQUIRED_GUIDANCE, RESULT_NO_CODE, RESULT_TYPES
from app.rules.model import (
    LIST_OPS,
    NUMERIC_OPS,
    OPS,
    All,
    AnyOf,
    Basis,
    CodeEntry,
    Cond,
    Expr,
    FactDef,
    KnowledgeBase,
    Not,
    Outcome,
    QuestionGroup,
    RouteGuidance,
    Rule,
    Table,
    iter_conds,
)

_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class RuleDataError(ValueError):
    """규칙 데이터가 스키마나 카탈로그와 맞지 않음."""


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_YAML_LOADER)  # noqa: S506 (SafeLoader 계열)


def _date(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


# ---- 카탈로그 ------------------------------------------------------------------------------


def parse_catalog(raw: list[dict]) -> dict[str, FactDef]:
    if not isinstance(raw, list):
        raise RuleDataError("facts_catalog: 목록이어야 합니다")
    out: dict[str, FactDef] = {}
    for item in raw:
        key = item.get("key")
        if not key:
            raise RuleDataError(f"facts_catalog: key 없음: {item}")
        if key in out:
            raise RuleDataError(f"facts_catalog: 중복 key {key}")
        ftype = item.get("type")
        if ftype not in ("number", "enum", "bool"):
            raise RuleDataError(f"facts_catalog[{key}]: type은 number|enum|bool")
        values = item.get("values")
        value_labels: dict[str, str] = {}
        if ftype == "enum":
            if not values:
                raise RuleDataError(f"facts_catalog[{key}]: enum에는 values가 필요합니다")
            if isinstance(values, dict):
                value_labels = {str(k): str(v) for k, v in values.items()}
                values = list(values.keys())
            values = tuple(str(v) for v in values)
        else:
            values = None
        if item.get("value_labels"):
            value_labels.update({str(k): str(v) for k, v in item["value_labels"].items()})
        prior = {
            str(k).lower() if isinstance(k, bool) else str(k): float(v)
            for k, v in (item.get("prior") or {}).items()
        }
        if sum(prior.values()) > 1.0 + 1e-9:
            raise RuleDataError(f"facts_catalog[{key}]: prior 합이 1을 넘습니다")
        out[key] = FactDef(
            key=key,
            type=ftype,
            question_hint=item.get("question_hint") or item.get("label") or key,
            label=item.get("label"),
            unit=item.get("unit"),
            values=values,
            value_labels=value_labels,
            ask_cost=float(item.get("ask_cost", 1)),
            evidence_cost=(
                float(item["evidence_cost"]) if item.get("evidence_cost") is not None else None
            ),
            evidence_type=item.get("evidence_type"),
            legal_priority=float(item.get("legal_priority", 1)),
            prior=prior,
            help=item.get("help"),
            none_value=item.get("none_value"),
            domain=item.get("domain"),
            ask_last=bool(item.get("ask_last", False)),
            auto_single=bool(item.get("auto_single", False)),
            internal=bool(item.get("internal", False)),
            value_aliases={
                str(k): tuple(str(a) for a in v)
                for k, v in (item.get("value_aliases") or {}).items()
            },
            parent=item.get("parent"),
            value_parent={str(k): str(v) for k, v in (item.get("value_parent") or {}).items()},
            implies={
                str(k).lower() if isinstance(k, bool) else str(k): dict(v or {})
                for k, v in (item.get("implies") or {}).items()
            },
            complement=_complement(key, item.get("complement")),
        )
        if out[key].domain not in (None, "referenced"):
            raise RuleDataError(f"facts_catalog[{key}]: domain은 referenced만 지원합니다")
        if out[key].ask_cost <= 0:
            raise RuleDataError(f"facts_catalog[{key}]: ask_cost는 0보다 커야 합니다")
    for fd in out.values():
        _check_parent(fd, out)
        _check_implies(fd, out)
        _check_complement(fd, out)
    return out


def _complement(key: str, raw: Any) -> tuple[str, float] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or not raw.get("fact") or raw.get("total") is None:
        raise RuleDataError(f"facts_catalog[{key}].complement: {{fact, total}} 형식이어야 합니다")
    return str(raw["fact"]), float(raw["total"])


def _check_complement(fd: FactDef, catalog: dict[str, FactDef]) -> None:
    """보수 관계(complement) 검증: 대상은 카탈로그의 다른 수치 사실이어야 한다."""
    if fd.complement is None:
        return
    tkey = fd.complement[0]
    tfd = catalog.get(tkey)
    if tfd is None or tkey == fd.key or fd.type != "number" or tfd.type != "number":
        raise RuleDataError(
            f"facts_catalog[{fd.key}].complement: 카탈로그의 다른 수치 사실이어야 합니다: {tkey}"
        )


def _check_implies(fd: FactDef, catalog: dict[str, FactDef]) -> None:
    """대리 질문 추정(implies) 검증: 대상은 카탈로그의 다른 사실, 값은 대상 타입에 맞아야 한다."""
    from app.rules.answers import AnswerError, coerce_value  # 순환 import 방지

    where = f"facts_catalog[{fd.key}].implies"
    for answer, targets in fd.implies.items():
        for tkey, tval in targets.items():
            tfd = catalog.get(tkey)
            if tfd is None or tkey == fd.key:
                raise RuleDataError(f"{where}[{answer}]: 카탈로그의 다른 사실이어야 합니다: {tkey}")
            try:
                coerce_value(tfd, tval)
            except (AnswerError, TypeError, ValueError) as exc:
                raise RuleDataError(f"{where}[{answer}].{tkey}: {exc}") from exc


def _check_parent(fd: FactDef, catalog: dict[str, FactDef]) -> None:
    """상위 분류(parent) 검증: 둘 다 enum, 한 단계만, 모든 값이 상위 분류 값 하나에 대응."""
    where = f"facts_catalog[{fd.key}]"
    if fd.parent is None:
        if fd.value_parent:
            raise RuleDataError(f"{where}: value_parent에는 parent가 필요합니다")
        return
    parent = catalog.get(fd.parent)
    if parent is None:
        raise RuleDataError(f"{where}: 카탈로그에 없는 parent '{fd.parent}'")
    if parent.key == fd.key:
        raise RuleDataError(f"{where}: 자기 자신을 parent로 둘 수 없습니다")
    if fd.type != "enum" or parent.type != "enum":
        raise RuleDataError(f"{where}: parent는 enum 사실끼리만 쓸 수 있습니다")
    if parent.parent is not None:
        raise RuleDataError(f"{where}: parent '{parent.key}'에도 parent가 있음(한 단계만 지원)")
    if fd.domain is not None:
        raise RuleDataError(f"{where}: domain이 있는 사실에는 parent를 둘 수 없습니다")
    values = set(fd.values or ())
    unknown = sorted(set(fd.value_parent) - values)
    if unknown:
        raise RuleDataError(f"{where}: value_parent에 값 영역에 없는 값 {unknown}")
    missing = sorted(values - set(fd.value_parent))
    if missing:
        raise RuleDataError(f"{where}: value_parent에 상위 분류가 없는 값 {missing}")
    bad = sorted({v for v in fd.value_parent.values() if v not in (parent.values or ())})
    if bad:
        raise RuleDataError(f"{where}: value_parent의 상위 분류 값이 '{parent.key}'에 없음 {bad}")


# ---- 조건식 ------------------------------------------------------------------------------


def parse_expr(raw: Any, where: str) -> Expr:
    if isinstance(raw, list):  # 목록은 all로 본다
        return All(tuple(parse_expr(x, where) for x in raw))
    if not isinstance(raw, dict):
        raise RuleDataError(f"{where}: 조건식은 dict 또는 list여야 합니다: {raw!r}")
    keys = set(raw)
    if keys & {"all", "any", "not"}:
        if len(keys) != 1:
            raise RuleDataError(f"{where}: all/any/not은 단독으로 써야 합니다: {raw!r}")
        (k,) = keys
        if k == "not":
            return Not(parse_expr(raw["not"], where))
        items = raw[k]
        if not isinstance(items, list) or not items:
            raise RuleDataError(f"{where}: {k}에는 비지 않은 목록이 필요합니다")
        parsed = tuple(parse_expr(x, where) for x in items)
        return All(parsed) if k == "all" else AnyOf(parsed)
    if "fact" not in raw or "op" not in raw:
        raise RuleDataError(f"{where}: 조건에는 fact와 op가 필요합니다: {raw!r}")
    unknown = keys - {"fact", "op", "value", "min_status"}
    if unknown:
        raise RuleDataError(f"{where}: 알 수 없는 조건 키 {sorted(unknown)}")
    op = raw["op"]
    if op not in OPS:
        raise RuleDataError(f"{where}: 지원하지 않는 연산자 {op}")
    try:
        min_status = FactStatus(raw.get("min_status", "CLAIMED"))
    except ValueError as exc:
        raise RuleDataError(f"{where}: min_status 오류 {raw.get('min_status')}") from exc
    if min_status not in (FactStatus.CLAIMED, FactStatus.EVIDENCED):
        raise RuleDataError(f"{where}: min_status는 CLAIMED 또는 EVIDENCED")
    value = raw.get("value")
    if op in LIST_OPS:
        if not isinstance(value, list) or not value:
            raise RuleDataError(f"{where}: {op}에는 비지 않은 목록 값이 필요합니다")
        value = tuple(value)
    elif op == "exists":
        value = None
    elif value is None:
        raise RuleDataError(f"{where}: {op}에는 value가 필요합니다")
    return Cond(fact=raw["fact"], op=op, value=value, min_status=min_status)


def _check_cond(c: Cond, catalog: dict[str, FactDef], where: str) -> None:
    fd = catalog.get(c.fact)
    if fd is None:
        raise RuleDataError(f"{where}: 카탈로그에 없는 사실 키 '{c.fact}'")
    if c.op == "exists":
        return
    vals = c.value if c.op in LIST_OPS else (c.value,)
    if c.op in NUMERIC_OPS and fd.type != "number":
        raise RuleDataError(f"{where}: {c.op}는 number 사실에만 쓸 수 있습니다 ({c.fact})")
    for v in vals:
        if fd.type == "number":
            if isinstance(v, bool) or not isinstance(v, int | float):
                raise RuleDataError(f"{where}: {c.fact}는 숫자 값이어야 합니다: {v!r}")
        elif fd.type == "bool":
            if not isinstance(v, bool):
                raise RuleDataError(f"{where}: {c.fact}는 true/false 값이어야 합니다: {v!r}")
        elif fd.type == "enum":
            if str(v) not in (fd.values or ()):
                raise RuleDataError(f"{where}: {c.fact}의 값 영역에 없는 값 {v!r}")


# ---- 테이블 ------------------------------------------------------------------------------


def _parse_basis(raw: Any, where: str) -> tuple[Basis, ...]:
    out = []
    for b in raw or []:
        if not isinstance(b, dict) or "ref" not in b:
            raise RuleDataError(f"{where}: basis 항목에는 ref가 필요합니다")
        out.append(
            Basis(
                type=b.get("type", "LAW"),
                ref=b["ref"],
                excerpt=b.get("excerpt"),
                source_id=b.get("source_id"),
                location=b.get("location"),
            )
        )
    return tuple(out)


def _parse_rule(raw: dict, origin: str, hit_policy: str) -> Rule:
    rid = raw.get("rule_id")
    if not rid:
        raise RuleDataError(f"{origin}: rule_id 없음")
    where = f"{origin}:{rid}"
    if "when" not in raw or "then" not in raw:
        raise RuleDataError(f"{where}: when과 then이 필요합니다")
    then = raw["then"] or {}
    if not then.get("code") and not then.get("outcome"):
        raise RuleDataError(f"{where}: then에는 code 또는 outcome이 필요합니다")
    if hit_policy == "PRIORITY" and "priority" not in raw:
        raise RuleDataError(f"{where}: PRIORITY 테이블의 규칙에는 priority가 필요합니다")
    return Rule(
        rule_id=rid,
        when=parse_expr(raw["when"], where),
        then=Outcome(
            code=then.get("code"),
            category=then.get("category"),
            name=then.get("name"),
            outcome=then.get("outcome"),
        ),
        priority=int(raw.get("priority", 0)),
        basis=_parse_basis(raw.get("basis"), where),
        review=raw.get("review"),
        effective_from=_date(raw.get("effective_from")),
        effective_to=_date(raw.get("effective_to")),
        origin=origin,
        source_rule=raw.get("source_rule"),
    )


def load_table(path: Path) -> Table:
    return parse_table(_read_yaml(path), path.name, path.parent)


def parse_table(raw: dict, origin: str, base_dir: Path | None = None) -> Table:
    for k in ("table_id", "version", "hit_policy"):
        if k not in raw:
            raise RuleDataError(f"{origin}: {k}가 필요합니다")
    hit = raw["hit_policy"]
    if hit not in ("UNIQUE", "PRIORITY"):
        raise RuleDataError(f"{origin}: hit_policy {hit}는 지원하지 않습니다 (UNIQUE|PRIORITY)")
    rules = [_parse_rule(r, origin, hit) for r in raw.get("rules") or []]
    for inc in raw.get("includes") or []:
        if base_dir is None:
            raise RuleDataError(f"{origin}: includes는 파일에서 읽은 테이블에서만 쓸 수 있습니다")
        inc_path = (base_dir / inc).resolve()
        frag = _read_yaml(inc_path) or {}
        rules.extend(_parse_rule(r, inc_path.name, hit) for r in frag.get("rules") or [])
    if not rules:
        raise RuleDataError(f"{origin}: 규칙이 없습니다")
    applies = raw.get("applies_when")
    return Table(
        table_id=raw["table_id"],
        version=str(raw["version"]),
        hit_policy=hit,
        rules=tuple(rules),
        effective_from=_date(raw.get("effective_from")),
        effective_to=_date(raw.get("effective_to")),
        applies_when=parse_expr(applies, f"{origin}:applies_when") if applies else None,
        title=raw.get("title"),
        origin=origin,
    )


# ---- 정적 검사 ----------------------------------------------------------------------------


def _top_level_domains(expr: Expr) -> dict[str, set]:
    """최상위 all 안의 eq/in 조건으로 사실별 허용 값 집합을 구한다(배타성 정적 검사용)."""
    conds = []
    if isinstance(expr, Cond):
        conds = [expr]
    elif isinstance(expr, All):
        conds = [x for x in expr.items if isinstance(x, Cond)]
    out: dict[str, set] = {}
    for c in conds:
        if c.op == "eq":
            vals = {c.value}
        elif c.op == "in":
            vals = set(c.value)
        else:
            continue
        out[c.fact] = out[c.fact] & vals if c.fact in out else vals
    return out


def _numeric_bounds(expr: Expr) -> dict[str, tuple[float, bool, float, bool]]:
    """최상위 all 안의 부등식으로 사실별 (하한, 하한포함, 상한, 상한포함)을 구한다."""
    conds = []
    if isinstance(expr, Cond):
        conds = [expr]
    elif isinstance(expr, All):
        conds = [x for x in expr.items if isinstance(x, Cond)]
    out: dict[str, tuple[float, bool, float, bool]] = {}
    for c in conds:
        if c.op not in NUMERIC_OPS:
            continue
        lo, lo_inc, hi, hi_inc = out.get(c.fact, (float("-inf"), False, float("inf"), False))
        v = float(c.value)
        if c.op in ("gt", "gte") and (v > lo or (v == lo and c.op == "gt")):
            lo, lo_inc = v, c.op == "gte"
        if c.op in ("lt", "lte") and (v < hi or (v == hi and c.op == "lt")):
            hi, hi_inc = v, c.op == "lte"
        out[c.fact] = (lo, lo_inc, hi, hi_inc)
    return out


def _provably_disjoint(a: Rule, b: Rule) -> bool:
    da, db = _top_level_domains(a.when), _top_level_domains(b.when)
    for k in da.keys() & db.keys():
        if not (da[k] & db[k]):
            return True
    na, nb = _numeric_bounds(a.when), _numeric_bounds(b.when)
    for k in na.keys() & nb.keys():
        lo1, li1, hi1, hi1i = na[k]
        lo2, li2, hi2, hi2i = nb[k]
        if hi1 < lo2 or (hi1 == lo2 and not (hi1i and li2)):
            return True
        if hi2 < lo1 or (hi2 == lo1 and not (hi2i and li1)):
            return True
    return False


def validate(
    kb_catalog: dict[str, FactDef],
    tables: list[Table],
    codes: dict[str, CodeEntry],
    groups: list[QuestionGroup],
) -> list[str]:
    warnings: list[str] = []
    seen: dict[str, str] = {}
    table_ids: set[str] = set()
    for t in tables:
        if t.table_id in table_ids:
            raise RuleDataError(f"table_id 중복: {t.table_id}")
        table_ids.add(t.table_id)
        if t.applies_when is not None:
            for c in iter_conds(t.applies_when):
                _check_cond(c, kb_catalog, f"{t.origin}:applies_when")
        in_table: set[str] = set()
        for r in t.rules:
            # 테이블 안에서는 유일. 여러 테이블이 같은 공통 조각을 포함하는 것은 허용한다.
            if r.rule_id in in_table:
                raise RuleDataError(f"rule_id 중복: {r.rule_id} ({t.table_id})")
            in_table.add(r.rule_id)
            if r.rule_id in seen:
                if seen[r.rule_id] != r.origin:
                    raise RuleDataError(
                        f"rule_id 중복: {r.rule_id} ({seen[r.rule_id]}, {r.origin})"
                    )
                continue  # 공통 조각의 같은 규칙은 이미 검사함
            seen[r.rule_id] = r.origin
            for c in iter_conds(r.when):
                _check_cond(c, kb_catalog, f"{r.origin}:{r.rule_id}")
            if codes and r.then.code and r.then.code not in codes:
                raise RuleDataError(f"{r.origin}:{r.rule_id}: 코드표에 없는 코드 {r.then.code}")
        if t.hit_policy == "PRIORITY":
            rs = list(t.rules)
            for i, a in enumerate(rs):
                for b in rs[i + 1 :]:
                    if (
                        a.priority == b.priority
                        and a.then.key != b.then.key
                        and not _provably_disjoint(a, b)
                    ):
                        warnings.append(
                            f"{t.table_id}: priority {a.priority}의 {a.rule_id}, {b.rule_id}가 "
                            "겹칠 수 있음(서로 다른 코드)"
                        )
        if t.hit_policy == "UNIQUE":
            rs = list(t.rules)
            for i, a in enumerate(rs):
                for b in rs[i + 1 :]:
                    if a.then.key != b.then.key and not _provably_disjoint(a, b):
                        warnings.append(
                            f"{t.table_id}: UNIQUE 규칙 {a.rule_id}, {b.rule_id}가 겹칠 수 있음"
                        )
    for g in groups:
        for k in g.facts:
            fd = kb_catalog.get(k)
            if fd is None:
                raise RuleDataError(f"question_groups[{g.group_id}]: 카탈로그에 없는 키 {k}")
            if fd.none_value is None:
                raise RuleDataError(f"question_groups[{g.group_id}]: {k}에 none_value가 없습니다")
        if len(g.facts) < 2:
            raise RuleDataError(f"question_groups[{g.group_id}]: 사실이 2개 이상이어야 합니다")
    return warnings


# ---- 진입점 ------------------------------------------------------------------------------


def parse_groups(raw: Any) -> list[QuestionGroup]:
    out = []
    for g in (raw or {}).get("groups", []) if isinstance(raw, dict) else raw or []:
        out.append(
            QuestionGroup(
                group_id=g["group_id"],
                title=g["title"],
                facts=tuple(g["facts"]),
                none_label=g.get("none_label", "모두 해당 없음"),
                expand_label=g.get("expand_label", "해당하는 게 있어요 / 잘 모르겠어요"),
                help=g.get("help"),
                ask_cost=float(g.get("ask_cost", 1)),
            )
        )
    return out


def parse_codes(raw: Any) -> dict[str, CodeEntry]:
    out: dict[str, CodeEntry] = {}
    for c in (raw or {}).get("codes", []) if isinstance(raw, dict) else raw or []:
        code = str(c["code"])
        if code in out:
            raise RuleDataError(f"codes: 중복 코드 {code}")
        out[code] = CodeEntry(
            code=code,
            name=c["name"],
            category=c.get("category"),
            effective_from=_date(c.get("effective_from")),
            effective_to=_date(c.get("effective_to")),
            note=c.get("note"),
        )
    return out


GUIDANCE_FILE = "outcome_guidance.yaml"
_GUIDANCE_KEYS = frozenset({"result_type", "outcome", "action", "summary", "notes"})


def parse_outcome_guidance(raw: Any) -> dict[tuple[str, str | None], RouteGuidance]:
    """결론 종류 → 경로추천 안내 표(docs/handoff-contract.md). 형식·값을 검증한다."""
    items = raw.get("guidance") if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not items:
        raise RuleDataError(f"{GUIDANCE_FILE}: guidance 목록이 필요합니다")
    out: dict[tuple[str, str | None], RouteGuidance] = {}
    for i, g in enumerate(items):
        where = f"{GUIDANCE_FILE}[{i}]"
        if not isinstance(g, dict):
            raise RuleDataError(f"{where}: 항목은 매핑이어야 합니다")
        extra = set(g) - _GUIDANCE_KEYS
        if extra:
            raise RuleDataError(f"{where}: 모르는 키 {sorted(extra)}")
        rt, outcome, action = g.get("result_type"), g.get("outcome"), g.get("action")
        if rt not in RESULT_TYPES:
            raise RuleDataError(f"{where}: result_type은 {RESULT_TYPES} 중 하나여야 합니다: {rt}")
        if rt == RESULT_NO_CODE:
            if outcome not in OUTCOMES:
                raise RuleDataError(f"{where}: 계약에 없는 outcome {outcome!r}")
        elif outcome is not None:
            raise RuleDataError(f"{where}: {rt}의 outcome은 null이어야 합니다")
        if action not in ACTIONS:
            raise RuleDataError(f"{where}: 계약에 없는 action {action!r}")
        summary = g.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise RuleDataError(f"{where}: summary(한국어 한 줄)가 필요합니다")
        notes = g.get("notes") or []
        if not isinstance(notes, list) or not all(isinstance(n, str) and n for n in notes):
            raise RuleDataError(f"{where}: notes는 문자열 목록이어야 합니다")
        key = (rt, outcome)
        if key in out:
            raise RuleDataError(f"{where}: 중복 항목 {key}")
        out[key] = RouteGuidance(
            result_type=rt, outcome=outcome, action=action, summary=summary, notes=tuple(notes)
        )
    return out


def validate_guidance(
    guidance: dict[tuple[str, str | None], RouteGuidance], tables: list[Table]
) -> None:
    """계약 표의 모든 행과 규칙에 쓰인 모든 outcome에 안내가 있어야 한다."""
    missing = [k for k in REQUIRED_GUIDANCE if k not in guidance]
    for t in tables:
        for r in t.rules:
            if r.then.code is None:
                key = (RESULT_NO_CODE, r.then.outcome)
                if key not in guidance and key not in missing:
                    missing.append(key)
    if missing:
        raise RuleDataError(f"{GUIDANCE_FILE}: 안내 항목이 없습니다: {missing}")


def build_kb(
    catalog: list[dict],
    tables: list[dict],
    groups: Any = None,
    codes: Any = None,
    guidance: Any = None,
) -> KnowledgeBase:
    """메모리의 dict로 지식 베이스를 만든다(테스트·변환 도구용). guidance를 주면 검증한다."""
    cat = parse_catalog(catalog)
    grp = parse_groups(groups) if groups else []
    cds = parse_codes(codes) if codes else {}
    tbls = [parse_table(t, f"<{t.get('table_id', 'table')}>") for t in tables]
    warnings = validate(cat, tbls, cds, grp)
    gd = parse_outcome_guidance(guidance) if guidance is not None else {}
    if guidance is not None:
        validate_guidance(gd, tbls)
    return KnowledgeBase(
        catalog=cat,
        tables=tuple(tbls),
        groups=tuple(grp),
        codes=cds,
        warnings=tuple(warnings),
        guidance=gd,
    )


def load_kb(data_dir: Path | str, rules_dir: str = "rules/tables") -> KnowledgeBase:
    data_dir = Path(data_dir)
    catalog = parse_catalog(_read_yaml(data_dir / "facts_catalog.yaml"))
    groups_path = data_dir / "question_groups.yaml"
    groups = parse_groups(_read_yaml(groups_path)) if groups_path.exists() else []
    codes_path = data_dir / "codes.yaml"
    codes = parse_codes(_read_yaml(codes_path)) if codes_path.exists() else {}
    tdir = data_dir / rules_dir
    tables = [load_table(p) for p in sorted(tdir.glob("*.yaml"))]
    if not tables:
        raise RuleDataError(f"{tdir}: 규칙 테이블이 없습니다")
    warnings = validate(catalog, tables, codes, groups)
    guidance_path = data_dir / GUIDANCE_FILE
    if not guidance_path.exists():
        raise RuleDataError(f"{guidance_path}: 결론 → 경로추천 안내 파일이 없습니다")
    guidance = parse_outcome_guidance(_read_yaml(guidance_path))
    validate_guidance(guidance, tables)
    return KnowledgeBase(
        catalog=catalog,
        tables=tuple(tables),
        groups=tuple(groups),
        codes=codes,
        warnings=tuple(warnings),
        guidance=guidance,
    )
