"""규칙 원본(knowledge/) → 엔진용 규칙 데이터(data/real/) 빌드.

    uv run python tools/build_kb.py          # knowledge/로 data/real/을 다시 만든다
    uv run python tools/build_kb.py --check  # data/real/이 knowledge/ 빌드 결과와 같은지(CI)
    uv run python tools/build_kb.py --legacy-regression ../resource_engine
                                             # 기존 엔진 판정표로 회귀 기준을 다시 가져온다

원본은 기존 엔진(resource_engine `2f1355a`)의 rules/에서 옮겨 왔다(knowledge/README.md).
원본의 법 규칙 단계 흐름(S0→S3)을 우선순위 대역으로 펴서 소재마다 테이블 하나로 만든다.
  SCOPE_S0 1100 / SCOPE_S1 1000 : 순환자원·폐기물 아님·법 적용 제외 (코드 없는 결론)
  DESIGNATED 500                : 법령 근거 지정폐기물 규칙 → 별표 4 지정 코드
  HOUSEHOLD 400                 : 사업장 조건이 모두 거짓 → 생활폐기물 (코드 없는 결론)
  INTERPRET 300                 : 해석 필요 규칙과 법령이 아닌 근거(질의회신·해설)의 규칙
  GENERAL 100                   : 지정폐기물이 아닐 때의 일반 코드
상위 대역이 미확인이면 하위 대역은 확정되지 않으므로 원본 단계 순서가 그대로 재현된다.
원본은 읽기만 한다. data/real/의 생성물은 손으로 고치지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml
from kb_review import CODE_MAP_UNIT, DEF_PREFIX, MATERIAL_PREFIX, ReviewIndex

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
OUT = ROOT / "data" / "real"
LEGACY_REV = "2f1355a"  # 원본을 옮겨 온 기존 엔진 커밋(이력 기록용)

# 원본 파일(knowledge/ 기준 경로). 이 파일들의 내용으로 규칙 버전을 만든다.
SOURCE_FILES = (
    "facts.yaml",
    "fact_settings.yaml",
    "law_rules/scope_and_business.yaml",
    "law_rules/designated.yaml",
    "materials.yaml",
    "annex4_codes.yaml",
    "code_map.yaml",
    "sources.yaml",
    "outcome_guidance.yaml",
    "reviews.yaml",
    "definitions.yaml",
    "glossary.yaml",
    "skills/interviewer.md",
    "question_guide.yaml",
)
# 빌드가 쓰는 파일(data/real/ 기준). --check는 이것만 비교한다.
# regression/(기존 엔진 판정표 기준)과 scenarios/(시뮬레이터 시나리오)는 빌드하지 않는다.
GENERATED_FILES = (
    "facts_catalog.yaml",
    "question_groups.yaml",
    "codes.yaml",
    "sources.yaml",
    "outcome_guidance.yaml",
    "glossary.yaml",
    "rule_notes.yaml",
    "skills/interviewer.md",
    "question_guide.yaml",
    "conversion_report.md",
    "rules/common/scope.yaml",
    "rules/common/business.yaml",
)
GENERATED_DIRS = ("rules/tables",)

P_S0, P_S1, P_DESIGNATED, P_HOUSEHOLD, P_INTERPRET, P_GENERAL = 1100, 1000, 500, 400, 300, 100

SKIP_FACTS = {
    "code",
    "general_group",
    "no_specific_code_applies",
    "residue_choice",
    "this_waste_designated",
    "waste_kind",
    "material",
}
EFFECTIVE_FROM = "2026-10-02"
CATCH_ALL = re.compile(r"^그 밖(의|에)")


def read(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def dump(path: Path, data: Any, header: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=110)
    path.write_text(header + text, encoding="utf-8", newline="\n")


# ---- 조건식 도우미 ----------------------------------------------------------------------


def leaf_true(c: dict, v: Any) -> bool:
    op, x = c["op"], c.get("value")
    if op == "eq":
        return v == x
    if op == "ne":
        return v != x
    if op == "in":
        return v in x
    if op == "not_in":
        return v not in x
    if op == "lt":
        return v < x
    if op == "lte":
        return v <= x
    if op == "gt":
        return v > x
    if op == "gte":
        return v >= x
    raise ValueError(op)


MIN_STATUSES = ("CLAIMED", "EVIDENCED")


def iter_leaves(e: Any, defs: dict[str, dict] | None = None):
    """원본 조건식의 단순 조건들(정의 참조는 펼친다)."""
    if isinstance(e, list):
        for x in e:
            yield from iter_leaves(x, defs)
    elif "all" in e or "any" in e:
        for x in e.get("all") or e.get("any"):
            yield from iter_leaves(x, defs)
    elif "not" in e:
        yield from iter_leaves(e["not"], defs)
    elif "ref" in e:
        if defs is not None and e["ref"] in defs:
            yield from iter_leaves(defs[e["ref"]]["when"], defs)
    else:
        yield e


def fold_expr(e: Any, preset: dict[str, Any], defs: dict[str, dict], refs: set[str]) -> Any:
    """원본 조건식을 프리셋 값으로 부분 평가한다. True | False | 남은 식.

    - 목록은 AND(기존 형식). `{all|any: [...]}`, `{not: 식}`, `{ref: 정의 이름}`, 단순 조건.
    - 프리셋에 있는 사실의 조건은 참·거짓으로 접고, 참은 빼고 거짓은 식 전체를 접는다(Kleene).
    - 평탄한 AND 목록의 결과는 이전 `fold`와 같다(조건 순서 유지).
    """
    if isinstance(e, list):
        e = {"all": e}
    if "ref" in e:
        name = e["ref"]
        if name not in defs:
            raise SystemExit(f"정의되지 않은 조건 이름: {name} (knowledge/definitions.yaml)")
        refs.add(name)
        return fold_expr(defs[name]["when"], preset, defs, refs)
    if "all" in e or "any" in e:
        is_all = "all" in e
        stop, skip = (False, True) if is_all else (True, False)
        items = []
        for x in e["all"] if is_all else e["any"]:
            v = fold_expr(x, preset, defs, refs)
            if v is stop:
                return stop
            if v is skip:
                continue
            items.append(v)
        if not items:
            return skip
        if len(items) == 1:
            return items[0]
        return {"all" if is_all else "any": items}
    if "not" in e:
        v = fold_expr(e["not"], preset, defs, refs)
        return (not v) if isinstance(v, bool) else {"not": v}
    if e.get("min_status") not in (None, *MIN_STATUSES):
        raise SystemExit(f"min_status는 {MIN_STATUSES} 중 하나여야 합니다: {e}")
    if e["fact"] in preset:
        return leaf_true(e, preset[e["fact"]])
    return e


def top_parts(reduced: Any) -> list[Any]:
    """접은 식의 최상위 AND 항목들(참이면 없음)."""
    if reduced is True:
        return []
    if isinstance(reduced, dict) and "all" in reduced:
        return list(reduced["all"])
    return [reduced]


def knowledge_rev(src: Path = KNOWLEDGE) -> str:
    """원본 파일 내용의 sha256 앞 8자리. 테이블 버전·생성물 머리말에 쓴다."""
    h = hashlib.sha256()
    for name in SOURCE_FILES:
        h.update(name.encode())
        h.update(b"\0")
        h.update((src / name).read_bytes())
    return h.hexdigest()[:8]


class Converter:
    def __init__(self, src: Path = KNOWLEDGE):
        self.src = src
        self.facts: dict[str, dict] = read(src / "facts.yaml")
        rules = read(src / "law_rules" / "scope_and_business.yaml")
        self.base_rules: list[dict] = rules["rules"]
        self.s3: list[dict] = read(src / "law_rules" / "designated.yaml")["rules"]
        m = read(src / "materials.yaml")
        self.materials: dict[str, dict] = m["materials"]
        self.groups_meta = m.get("groups") or {}
        self.code_tests: dict[str, dict] = m.get("code_tests") or {}
        a4 = read(src / "annex4_codes.yaml")
        self.a4_groups: list[dict] = a4.get("groups") or []
        self.codes: list[dict] = a4["codes"]
        self.code_index = {c["id"]: c for c in self.codes}
        self.s4 = read(src / "code_map.yaml")
        self.sources: dict[str, dict] = read(src / "sources.yaml")
        self.ov = read(src / "fact_settings.yaml") or {}
        self.defs: dict[str, dict] = (read(src / "definitions.yaml") or {}).get("definitions") or {}
        if self.s4.get("designated_exclusions"):
            raise SystemExit(
                "code_map.yaml의 designated_exclusions는 쓰지 않는다. "
                "법 규칙의 exceptions로 옮기세요(knowledge/README.md 원본 형식)"
            )
        self.reviews = ReviewIndex(src)
        self.verified_rules = 0
        self.excluded = set(self.s4.get("excluded_codes", []))
        self.used_facts: set[str] = set()
        self.fact_band: dict[str, int] = {}
        self.report: dict[str, Any] = defaultdict(list)

    # ---- 공통 --------------------------------------------------------------------------

    def rv(self, deps: list[str]) -> dict:
        """생성 규칙이 기대는 검토 단위와 그 결과(review). knowledge/reviews.yaml 기준."""
        deps = list(dict.fromkeys(deps))
        review = self.reviews.review_of(deps)
        if review == "VERIFIED":
            self.verified_rules += 1
        return {"review_units": deps, "review": review}

    def evidence(self, source_id: str) -> str:
        return (self.sources.get(source_id) or {}).get("evidence", "LAW")

    def is_law(self, rule: dict) -> bool:
        return self.evidence(rule["source"]) == "LAW"

    def concludes_itself(self, rule: dict) -> bool:
        """원본 결론을 그대로 낼지(아니면 해석 필요로 끝낸다).

        `conclusion: interpret`이면 해석 필요, 없으면 근거가 법령일 때만 그대로 낸다(기본값).
        """
        mode = rule.get("conclusion")
        if mode not in (None, "auto", "interpret"):
            raise SystemExit(f"{rule['id']}: conclusion은 auto | interpret: {mode}")
        return mode != "interpret" and self.is_law(rule)

    def fold(self, rule: dict, preset: dict[str, Any] | None = None) -> tuple[Any, list[str]]:
        """규칙 조건을 프리셋으로 접는다. (접은 식, 쓴 정의의 검토 단위 목록)."""
        refs: set[str] = set()
        reduced = fold_expr(rule["when"], preset or {}, self.defs, refs)
        return reduced, [f"{DEF_PREFIX}{n}" for n in sorted(refs)]

    def basis(self, rule: dict) -> list[dict]:
        out = []
        items = [
            {"source": rule["source"], "location": rule.get("location"), "quote": rule.get("quote")}
        ] + list(rule.get("supporting") or [])
        for it in items:
            src = self.sources.get(it["source"], {})
            ref = " ".join(x for x in (src.get("title"), it.get("location")) if x)
            b = {
                "type": src.get("evidence", "LAW"),
                "ref": ref or it["source"],
                "source_id": it["source"],
            }
            if it.get("location"):
                b["location"] = it["location"]
            if it.get("quote"):
                b["excerpt"] = it["quote"]
            out.append(b)
        return out

    def code_basis(self, code: str) -> dict:
        c = self.code_index[code]
        title = self.sources["RULE-A4"]["title"]
        return {
            "type": "LAW",
            "ref": f"{title} {code}",
            "excerpt": f"{code} {c['name']}",
            "source_id": "RULE-A4",
            "location": code,
        }

    def confirm_target(self, mid: str | None) -> bool:
        """이 소재가 확인대상 폐기물(시행규칙 제17조의2제1항)인가.

        목록은 fact_settings.yaml의 confirm_target.
        """
        if mid is None:
            return False
        kinds = (self.ov.get("confirm_target") or {}).get("waste_kinds") or []
        return self.materials.get(mid, {}).get("waste_kind") in kinds

    def leaf(self, c: dict, band: int, mid: str | None = None) -> dict:
        fid = c["fact"]
        self.used_facts.add(fid)
        self.fact_band[fid] = max(self.fact_band.get(fid, 0), band)
        out = {"fact": fid, "op": c["op"], "value": c.get("value")}
        is_test = self.facts.get(fid, {}).get("cost") == "TEST"
        # 증빙 수준: 원본에 적었으면 그대로, 아니면 시험 수치만 성적서(EVIDENCED) 필요
        if c.get("min_status"):
            if c["min_status"] != "CLAIMED":
                out["min_status"] = c["min_status"]
        elif is_test:
            out["min_status"] = "EVIDENCED"
        # 확인대상 폐기물은 '기준 미만'도 분석결과서로만 받는다(말로는 지정 후보를 지우지 않음)
        excluded = (self.ov.get("confirm_target") or {}).get("exclude_facts") or []
        if is_test and fid not in excluded and self.confirm_target(mid):
            out["falsify_min_status"] = "EVIDENCED"
        return out

    def emit(self, reduced: Any, band: int, mid: str | None = None) -> Any:
        """접은 식 → 엔진 규칙 형식."""
        if reduced is True:
            # 조건이 모두 접혀 사라짐 → 이 테이블에서는 항상 참
            return {"fact": "material", "op": "eq", "value": mid}
        if "all" in reduced or "any" in reduced:
            key = "all" if "all" in reduced else "any"
            return {key: [self.emit(x, band, mid) for x in reduced[key]]}
        if "not" in reduced:
            return {"not": self.emit(reduced["not"], band, mid)}
        return self.leaf(reduced, band, mid)

    # ---- 공통 조각: 범위·사업장 -----------------------------------------------------------

    def scope_fragment(self) -> dict:
        rules = []
        for r in self.base_rules:
            if r["stage"] == "S0" and r["concludes"] in ("NOT_WASTE", "CIRCULAR_RESOURCE"):
                prio = P_S0
                outcome = r["concludes"] if self.concludes_itself(r) else "INTERPRETATION_NEEDED"
            elif r["stage"] == "S1" and r["concludes"] == "EXCLUDED":
                prio = P_S1
                outcome = "EXCLUDED" if self.concludes_itself(r) else "INTERPRETATION_NEEDED"
            else:
                continue
            reduced, def_units = self.fold(r)
            rules.append(
                {
                    "rule_id": r["id"],
                    "source_rule": r["id"],
                    "priority": prio,
                    "when": self.emit(reduced, 2),
                    "then": {
                        "code": None,
                        "category": "OUT_OF_SCOPE",
                        "outcome": outcome,
                        "name": r.get("plain"),
                    },
                    "basis": self.basis(r),
                    **self.rv([r["id"], *def_units]),
                }
            )
        return {"rules": rules}

    def business_fragment(self) -> dict:
        alts = []
        basis = []
        alt_ids = []
        for r in self.base_rules:
            if r["stage"] != "S2" or r["concludes"] != "BUSINESS":
                continue
            if any(c["fact"] == "this_waste_designated" for c in iter_leaves(r["when"], self.defs)):
                continue  # 지정폐기물 대역이 위에 있으므로 따로 둘 필요 없음
            reduced, def_units = self.fold(r)
            alts.append(self.emit(reduced, 2))
            alt_ids += [r["id"], *def_units]
        hh = next(r for r in self.base_rules if r["id"] == "S2-HOUSEHOLD")
        basis = self.basis(hh)
        return {
            "rules": [
                {
                    "rule_id": "S2-HOUSEHOLD",
                    "source_rule": "S2-HOUSEHOLD",
                    "priority": P_HOUSEHOLD,
                    "when": {"not": {"any": alts}},
                    "then": {
                        "code": None,
                        "category": "OUT_OF_SCOPE",
                        "outcome": "HOUSEHOLD",
                        "name": "생활폐기물(사업장폐기물이 아님)",
                    },
                    "basis": basis,
                    # 생활폐기물 = 사업장폐기물 규칙이 모두 거짓 → 그 규칙들에도 기댄다
                    **self.rv(["S2-HOUSEHOLD", *alt_ids]),
                }
            ]
        }

    # ---- 지정 코드 범위 (s4_map 재현) -----------------------------------------------------

    def designated_codes(self, rule_id: str, mat: dict) -> list[str]:
        m = self.s4["designated"]
        keys = [k for k in m if rule_id.startswith(k)]
        if not keys:
            return []
        prefixes = m[max(keys, key=len)]
        cands = [
            c["id"]
            for c in self.codes
            if c["section"] == "DESIGNATED"
            and c["id"] not in self.excluded
            and any(c["id"].startswith(p) for p in prefixes)
        ]
        mat_des = (mat.get("codes") or {}).get("DESIGNATED") or []
        if mat_des:
            narrowed = [c for c in cands if any(c.startswith(p) for p in mat_des)]
            if narrowed:
                cands = narrowed
        kind = mat.get("waste_kind")
        for sp in self.s4.get("designated_split", []):
            if set(prefixes) != set(sp["when_prefixes"]):
                continue
            target = (sp.get("by_waste_kind") or {}).get(kind)
            if target is None:
                hits = {
                    code
                    for pre, code in (sp.get("by_fired") or {}).items()
                    if rule_id.startswith(pre)
                }
                target = hits.pop() if len(hits) == 1 else None
            if target in cands:
                cands = [target]
        return cands

    def outcome_reason(self, mat: dict) -> str | None:
        """번호 없는 일반 결론의 구체적 이유(결과 카드에 그대로 보인다)."""
        test = self.code_tests.get(mat.get("code_needs_test") or "")
        if test and test.get("message"):
            return " ".join(str(test["message"]).split())
        if mat.get("reason"):
            return " ".join(str(mat["reason"]).split())
        return None

    def general_codes(self, mat: dict) -> tuple[list[str], str | None]:
        if mat.get("no_general_code"):
            return [], "NO_MIXTURE_RULE"
        if mat.get("code_needs_test"):
            return [], "CODE_NEEDS_TEST"
        if mat.get("designated_only"):  # 별표 4에 지정 번호만 있는 소재(예: 납축전지 03-10-01)
            return [], "NO_GENERAL_CODE"
        if mat.get("general_by_family"):  # 목록에 없는 폐기물: 별표 4 일반 번호 전체(계열로 좁힘)
            prefixes = ["51-"]
        else:
            prefixes = []
        prefixes = (
            prefixes
            or (mat.get("codes") or {}).get("GENERAL")
            or self.s4["general_by_kind"].get(mat.get("waste_kind"), [])
        )
        if not prefixes:
            return [], "NO_GENERAL_CODE"
        cands = [
            c["id"]
            for c in self.codes
            if c["section"] == "GENERAL"
            and c["id"] not in self.excluded
            and any(c["id"].startswith(p) for p in prefixes)
        ]
        return (cands, None) if cands else ([], "NO_GENERAL_CODE")

    # ---- 소재 테이블 -----------------------------------------------------------------------

    def material_table(self, mid: str, mat: dict) -> dict:
        preset = {"waste_kind": mat.get("waste_kind"), **(mat.get("presets") or {})}
        designated: list[tuple[dict, Any]] = []
        interpret: list[tuple[dict, Any]] = []
        uses: dict[str, list[str]] = {}  # 규칙 → 쓴 정의의 검토 단위
        complement = None
        for r in self.s3:
            if r.get("complement_of"):
                complement = r
                continue
            folded, uses[r["id"]] = self.fold(r, preset)
            if folded is False:
                continue
            if r["concludes"] == "DESIGNATED" and self.concludes_itself(r):
                designated.append((r, folded))
            else:
                interpret.append((r, folded))

        rules: list[dict] = []
        code_sets: dict[str, list[str]] = {}
        for r, _ in designated:
            cs = self.designated_codes(r["id"], mat)
            if not cs:
                self.report["mapping_missing"].append(f"{mid}:{r['id']}")
            code_sets[r["id"]] = cs
        union = {c for cs in code_sets.values() for c in cs}
        need_choice = len(union) > 1
        by_id = {r["id"]: folded for r, folded in designated}
        for r, folded in designated:
            cs = code_sets[r["id"]]
            if not cs:
                continue
            extra: list[Any] = []
            ex_ids: list[str] = []
            # 법 규칙의 예외: 그 규칙들이 성립하면 이 규칙은 적용하지 않는다(이 소재에 있는 것만)
            for ex in r.get("exceptions") or []:
                excluders = [
                    rid for rid in by_id if any(rid.startswith(p) for p in ex["unless_any"])
                ]
                for x in excluders:
                    ex_ids += [x, *uses[x]]
                if excluders:
                    extra.append({"not": {"any": [self.emit(by_id[x], 3, mid) for x in excluders]}})
            base_leaves = [self.emit(p, 3, mid) for p in top_parts(folded)]
            for code in cs:
                parts = base_leaves + extra
                rid = f"{mid}:{r['id']}"
                if need_choice:
                    parts = parts + [{"fact": "annex4_code", "op": "eq", "value": code}]
                    rid = f"{rid}:{code}"
                when = (
                    (parts[0] if len(parts) == 1 else {"all": parts})
                    if parts
                    else {"fact": "material", "op": "eq", "value": mid}
                )
                rules.append(
                    {
                        "rule_id": rid,
                        "source_rule": r["id"],
                        "priority": P_DESIGNATED,
                        "when": when,
                        "then": {
                            "code": code,
                            "category": "DESIGNATED",
                            "name": self.code_index[code]["name"],
                        },
                        "basis": self.basis(r) + [self.code_basis(code)],
                        **self.rv(
                            [
                                r["id"],
                                *uses[r["id"]],
                                *ex_ids,
                                CODE_MAP_UNIT,
                                f"{MATERIAL_PREFIX}{mid}",
                            ]
                        ),
                    }
                )
                if not need_choice:
                    break

        for r, folded in interpret:
            rules.append(
                {
                    "rule_id": f"{mid}:{r['id']}",
                    "source_rule": r["id"],
                    "priority": P_INTERPRET,
                    "when": self.emit(folded, 3, mid),
                    "then": {
                        "code": None,
                        "category": "NEEDS_INTERPRETATION",
                        "outcome": "INTERPRETATION_NEEDED",
                        "name": r.get("item"),
                    },
                    "basis": self.basis(r),
                    **self.rv([r["id"], *uses[r["id"]], f"{MATERIAL_PREFIX}{mid}"]),
                }
            )

        gcodes, goutcome = self.general_codes(mat)
        gbasis = self.basis(complement) if complement else []
        # 일반 코드의 원본: "지정폐기물 외의 것"을 정의한 보완 규칙(없으면 소재 항목만)
        gsource = {"source_rule": complement["id"]} if complement else {}
        gdeps = [complement["id"]] if complement else []
        gdeps += [f"{MATERIAL_PREFIX}{mid}", CODE_MAP_UNIT]
        if goutcome:
            rules.append(
                {
                    "rule_id": f"{mid}:GENERAL",
                    **gsource,
                    "priority": P_GENERAL,
                    "when": {"fact": "material", "op": "eq", "value": mid},
                    "then": {
                        "code": None,
                        "category": "GENERAL",
                        "outcome": goutcome,
                        **({"reason": r} if (r := self.outcome_reason(mat)) else {}),
                    },
                    "basis": gbasis,
                    **self.rv(gdeps),
                }
            )
            self.report["general_outcome"].append(f"{mid}: {goutcome}")
        else:
            many = len(gcodes) > 1
            for code in gcodes:
                when: Any = {"fact": "material", "op": "eq", "value": mid}
                rid = f"{mid}:GENERAL"
                if many:
                    when = {"fact": "annex4_code", "op": "eq", "value": code}
                    rid = f"{rid}:{code}"
                    self.used_facts.add("annex4_code")
                if mat.get("general_by_family"):  # 계열(예: 51-22 폐콘크리트)을 먼저 고르게 한다
                    when = {
                        "all": [
                            {"fact": "general_group", "op": "eq", "value": code[:5]},
                            {"fact": "annex4_code", "op": "eq", "value": code},
                        ]
                    }
                    self.used_facts.add("general_group")
                rules.append(
                    {
                        "rule_id": rid,
                        **gsource,
                        "priority": P_GENERAL,
                        "when": when,
                        "then": {
                            "code": code,
                            "category": "GENERAL",
                            "name": self.code_index[code]["name"],
                        },
                        "basis": gbasis + [self.code_basis(code)],
                        **self.rv(gdeps),
                    }
                )
        if need_choice:
            self.used_facts.add("annex4_code")
        self.report["tables"].append(
            f"{mid}: 지정 {len(designated)}규칙/{len(union)}코드, 해석 {len(interpret)}, "
            f"일반 {len(gcodes) or goutcome}"
        )
        return {
            "table_id": mid,
            "title": mat["label"],
            "version": f"2026.11.0+kb-{self.rev()}",
            "effective_from": EFFECTIVE_FROM,
            "hit_policy": "PRIORITY",
            "applies_when": {"fact": "material", "op": "eq", "value": mid},
            "includes": ["../common/scope.yaml", "../common/business.yaml"],
            "rules": rules,
        }

    _rev: str | None = None

    def rev(self) -> str:
        if self._rev is None:
            self._rev = knowledge_rev(self.src)
        return self._rev

    # ---- 카탈로그 --------------------------------------------------------------------------

    def help_text(self, f: dict) -> str | None:
        parts = [h["text"] for h in f.get("how_to_check") or [] if h.get("text")]
        t = f.get("test")
        if t:
            parts.append(f"시험: {t.get('item', '')} — {t.get('method', '')}".strip())
            if t.get("report"):
                parts.append(f"성적서에서 확인할 값: {t['report']}")
        note = f.get("note")
        if isinstance(note, dict) and note.get("text"):
            parts.append(note["text"])
        return "\n".join(parts) or None

    def material_group_fact(self, mats: dict[str, dict]) -> dict:
        """소재 2단계 질문의 1단계: 기존 materials.yaml groups(변환한 소재가 있는 분류만)."""
        ov = self.ov.get("material_group") or {}
        used = {m["group"] for m in mats.values()}
        unknown = used - set(self.groups_meta)
        if unknown:
            raise SystemExit(f"materials.yaml groups에 없는 분류: {sorted(unknown)}")
        groups = {g: meta for g, meta in self.groups_meta.items() if g in used}
        labels = {g: (ov.get("labels") or {}).get(g, meta["label"]) for g, meta in groups.items()}
        aliases = ov.get("aliases") or {}
        hints = {g: (ov.get("hints") or {}).get(g, m.get("hint")) for g, m in groups.items()}
        help_lines = [f"{labels[g]}: {h}" for g, h in hints.items() if h]
        counts = Counter(m["group"] for m in mats.values())
        self.report["material_groups"] = [f"{g} {labels[g]}: 소재 {counts[g]}개" for g in groups]
        return {
            "key": "material_group",
            "label": ov.get("label", "소재 분류"),
            "type": "enum",
            "values": labels,
            "value_aliases": {g: list(aliases[g]) for g in groups if aliases.get(g)},
            "ask_cost": 1,
            "legal_priority": 1,
            "question_hint": ov.get("question_hint", "어떤 종류의 폐기물인가요?"),
            "help": "\n".join(help_lines) or None,
        }

    def catalog(self) -> list[dict]:
        ov = self.ov.get("facts") or {}
        out: list[dict] = []
        mats = {k: v for k, v in self.materials.items() if not v.get("unlisted")}
        out.append(self.material_group_fact(mats))
        out.append(
            {
                "key": "material",
                "label": "소재",
                "type": "enum",
                "values": {k: v["label"] for k, v in mats.items()},
                "value_aliases": {k: v["aliases"] for k, v in mats.items() if v.get("aliases")},
                "ask_cost": 1,
                "legal_priority": 1,
                "question_hint": self.facts["material"]["question"],
                "help": self.help_text(self.facts["material"]),
                "parent": "material_group",
                "value_parent": {k: v["group"] for k, v in mats.items()},
            }
        )
        # 대리 질문 사실(fact_settings의 implies)은 규칙이 직접 쓰지 않아도
        # 카탈로그에 둔다(질문 전략)
        screening = {fid for fid, o in ov.items() if (o or {}).get("implies")}
        for fid, f in self.facts.items():
            if fid in SKIP_FACTS or fid.startswith("reporting_"):
                continue
            if fid not in self.used_facts and fid not in screening:
                continue
            if f.get("kind") == "interpretive_choice" or f.get("derived_from"):
                continue
            item: dict[str, Any] = {"key": fid, "label": f.get("label"), "type": f["type"]}
            if f["type"] == "enum":
                vals = f.get("values")
                if not isinstance(vals, dict):
                    raise SystemExit(f"{fid}: enum values 형식 미지원")
                item["values"] = vals
            if f.get("unit"):
                item["unit"] = f["unit"]
            cost = f.get("cost", "USER")
            if cost == "TEST":
                # 시험 수치는 사용자가 바로 알기 어렵다 → 관문(예/아니오) 질문보다 뒤에 묻는다.
                item.update(ask_cost=4, evidence_cost=50, evidence_type="TEST_REPORT")
            elif cost == "DOCUMENT":
                item.update(ask_cost=2, evidence_type="DOCUMENT")
            else:
                item["ask_cost"] = 1
            band = self.fact_band.get(fid, 1)
            item["legal_priority"] = 3 if band >= 3 else (2 if band == 2 else 1)
            item["question_hint"] = f.get("question") or f.get("label") or fid
            h = self.help_text(f)
            if h:
                item["help"] = h
            item.update(ov.get(fid) or {})
            out.append(item)
        if "general_group" in self.used_facts:
            f = self.facts["general_group"]
            # 계열 = 일반 번호의 앞 5자리(51-22 등). 별표 4에 계열 행이 없으면 첫 번호의 명칭을 쓴다
            names = {
                g["id"]: g["name"]
                for g in self.a4_groups
                if g.get("section") == "GENERAL" and g.get("level") == "group"
            }
            families: dict[str, str] = {}
            for c in self.codes:
                if c["section"] == "GENERAL" and c["id"] not in self.excluded:
                    fam = c["id"][:5]
                    families.setdefault(fam, names.get(fam) or c["name"])
            out.append(
                {
                    "key": "general_group",
                    "label": f.get("label"),
                    "type": "enum",
                    "values": {k: f"{k} {v}" for k, v in families.items()},
                    "ask_cost": 1,
                    "legal_priority": 1,
                    "question_hint": f.get("question") or f.get("label"),
                    **({"help": self.help_text(f)} if self.help_text(f) else {}),
                }
            )
        designated_or_general = [
            c
            for c in self.codes
            if c["section"] in ("DESIGNATED", "GENERAL") and c["id"] not in self.excluded
        ]
        out.append(
            {
                "key": "annex4_code",
                "label": "별표 4 분류번호",
                "type": "enum",
                "values": {c["id"]: f"{c['id']} {c['name']}" for c in designated_or_general},
                "domain": "referenced",
                "ask_last": True,
                "auto_single": True,
                "internal": True,
                "ask_cost": 1,
                "legal_priority": 1,
                # 질문 문구는 facts.yaml의 code 항목(사람이 고치는 원본)에서 가져온다
                "question_hint": (self.facts.get("code") or {}).get("question")
                or "이 폐기물에 해당하는 분류번호(시행규칙 별표 4)를 골라 주세요.",
                "help": (
                    (self.help_text(self.facts["code"]) if "code" in self.facts else None)
                    or "기존 배출자신고서나 처리 계약서의 분류번호와 명칭을 대조하세요."
                )
                + " '그 밖의' 번호는 같은 분류의 다른 번호에 해당하지 않을 때만 고릅니다.",
            }
        )
        return out

    def codes_file(self) -> dict:
        return {
            "codes": [
                {
                    "code": c["id"],
                    "name": c["name"],
                    "category": c["section"],
                    "effective_from": EFFECTIVE_FROM,
                }
                for c in self.codes
            ]
        }

    # ---- 실행 --------------------------------------------------------------------------

    def run(self, out: Path) -> None:
        tables_dir = out / "rules" / "tables"
        if tables_dir.exists():
            for p in tables_dir.glob("*.yaml"):
                p.unlink()
        hdr = (
            f"# 자동 생성: tools/build_kb.py (knowledge {self.rev()}). "
            "직접 고치지 말고 knowledge/를 고친 뒤 다시 빌드.\n"
        )
        dump(out / "rules" / "common" / "scope.yaml", self.scope_fragment(), hdr)
        dump(out / "rules" / "common" / "business.yaml", self.business_fragment(), hdr)
        n = 0
        for mid, mat in self.materials.items():
            if mat.get("unlisted"):
                self.report["skipped_materials"].append(f"{mid}: 목록에 없는 소재(unlisted)")
                continue
            dump(tables_dir / f"{mid}.yaml", self.material_table(mid, mat), hdr)
            n += 1
        dump(out / "facts_catalog.yaml", self.catalog(), hdr)
        dump(out / "question_groups.yaml", {"groups": self.ov.get("groups") or []}, hdr)
        dump(out / "codes.yaml", self.codes_file(), hdr)
        dump(out / "sources.yaml", self.sources, hdr)
        # 경로추천 안내는 사람이 쓴 표 그대로 옮긴다(변환 없음)
        shutil.copyfile(self.src / "outcome_guidance.yaml", out / "outcome_guidance.yaml")
        # 용어집도 사람이 쓴 그대로 옮긴다(판정 무관, 질문 카드 terms)
        shutil.copyfile(self.src / "glossary.yaml", out / "glossary.yaml")
        # 문진 설명용(판정 무관): 원본 규칙의 쉬운 설명, 문진 진행 AI 지침
        # (docs/design/agent-skill-harness.md)
        dump(out / "rule_notes.yaml", self.rule_notes(), hdr)
        (out / "skills").mkdir(exist_ok=True)
        shutil.copyfile(self.src / "skills" / "interviewer.md", out / "skills" / "interviewer.md")
        shutil.copyfile(self.src / "question_guide.yaml", out / "question_guide.yaml")
        self.write_report(out, n)
        print(f"테이블 {n}개, 사실 {len(self.used_facts)}개 → {out}")

    def rule_notes(self) -> dict:
        """원본 규칙 ID → 제목·쉬운 설명. 생성 규칙의 source_rule로 찾는다(설명 전용)."""
        notes: dict[str, dict] = {}
        for r in [*self.base_rules, *self.s3]:
            item = {k: r[k] for k in ("title", "plain") if r.get(k)}
            if item:
                notes[r["id"]] = item
        return {"rules": notes}

    def write_report(self, out: Path, n: int) -> None:
        lines = [
            "# 규칙 빌드 보고서",
            "",
            f"- 원본: `knowledge/` ({self.rev()}). 기존 엔진 resource_engine `{LEGACY_REV}`의 "
            "rules/에서 옮겨 왔다.",
            f"- 소재 테이블: {n}개, 시행일 {EFFECTIVE_FROM}",
            "- 전문가 검토(`knowledge/reviews.yaml`): "
            f"생성 규칙 {self.verified_rules}개가 `VERIFIED`, 나머지는 `UNVERIFIED`다.",
            "",
            "## 우선순위 대역",
            "| 대역 | priority | 내용 |",
            "|---|---|---|",
            f"| SCOPE_S0 | {P_S0} | 순환자원·폐기물 아님 (법령 아닌 근거는 해석 필요) |",
            f"| SCOPE_S1 | {P_S1} | 폐기물관리법 적용 제외 |",
            f"| DESIGNATED | {P_DESIGNATED} | 법령 근거 지정폐기물 → 별표 4 지정 코드 |",
            f"| HOUSEHOLD | {P_HOUSEHOLD} | 사업장 조건 모두 거짓 → 생활폐기물 |",
            f"| INTERPRET | {P_INTERPRET} | 해석 필요, 질의회신 근거 규칙 |",
            f"| GENERAL | {P_GENERAL} | 사업장일반폐기물 코드 |",
            "",
            "## 소재 2단계 질문",
            "- 소재 분류(material_group, 기존 materials.yaml groups) → 그 분류의 소재(material).",
            "- 규칙은 소재만 참조한다. 분류는 소재 선택지를 줄이고, 소재가 하나면 자동으로 정한다.",
            *[f"- {x}" for x in self.report.get("material_groups", [])],
            "",
            "## 변환하지 않은 기능",
            "- 결정 카드(해석 선택, residue_choice 등): 해석 필요 규칙은 판정 불가로 안내한다.",
            "- S5 재활용 유형(별표 4의3), S6 배출자신고·처리계획: 이번 범위 밖.",
            "- '그 밖의' 번호를 고를 때의 no_specific_code_applies 확인: 선택지로만 제시한다.",
            "- 일반 코드를 정할 수 없는 소재(general_group 경로)는 NO_GENERAL_CODE로 안내한다.",
            "",
            "## 의도한 차이",
            "- 지정 사유가 여럿일 때 기존 엔진은 사유별 번호 범위를 합친 뒤, "
            "모든 사유가 소재 자체에서 "
            "나온 경우에만 소재 번호로 좁혔다. 새 테이블은 사유마다 따로 좁힌 뒤 합친다. "
            "그래서 선택지가 기존보다 적거나 같다(예: 액상 PP + 유해화학물질 → 01-01-02와 09번대).",
            "- 산·알칼리 + 유해화학물질: 법이 제9호를 제외하므로 제외를 먼저 적용해 산·알칼리 번호 "
            "하나로 정한다(기존은 선택지 여러 개).",
            "- 지정 기준 미만 산·알칼리: 기존은 일반 그룹·번호를 물었지만 "
            "NO_GENERAL_CODE로 안내한다.",
            "- 회귀 비교 결과는 regression/summary.md, "
            "허용 기준은 tests/test_legacy_regression.py.",
            "- 시험 수치 조건은 `min_status: EVIDENCED`다. 지정 판정에는 성적서가 필요하고, "
            "기준 미만 진술로는 지정 후보를 지울 수 있다.",
            "- 단 확인대상 폐기물(시행규칙 제17조의2제1항, "
            "`fact_settings.yaml`의 `confirm_target`) "
            "소재는 시험 수치 조건에 `falsify_min_status: EVIDENCED`를 붙인다. "
            "기준 미만도 분석결과서로만 받는다(PCB 수치는 제외).",
            "",
        ]
        for key, title in (
            ("general_outcome", "일반 코드 대신 안내로 끝나는 소재"),
            ("mapping_missing", "번호 범위 대응이 없는 지정 규칙"),
            ("skipped_materials", "변환하지 않은 소재"),
        ):
            items = self.report.get(key) or []
            bullets = [f"- {x}" for x in items] or ["- 없음"]
            lines += [f"## {title} ({len(items)})", *bullets, ""]
        lines += ["## 소재별 규칙 수", *[f"- {x}" for x in self.report["tables"]], ""]
        (out / "conversion_report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


# ---- 회귀 데이터 ---------------------------------------------------------------------------

BASE = {
    "material_fate": "released",
    "circular_resource_recognized": False,
    "law_exclusion": "none",
    "emission_facility": True,
}


def regression(legacy: Path, out: Path) -> None:
    src = legacy / "tests" / "data" / "material_tables.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = []
    stats: Counter = Counter()
    for mid, table in data["tables"].items():
        for i, r in enumerate(table["rows"]):
            res = r["result"] or ""
            m = re.fullmatch(r"번호 선택 필요\((\d+)개\)", res)
            if r["status"] == "DETERMINED":
                expect = {"kind": "CODE", "code": res}
            elif m:
                expect = {
                    "kind": "CODE_CHOICE",
                    "n": int(m.group(1)),
                    "multi_reason": "MULTI_REASON" in r.get("flags", []),
                }
            else:
                m2 = re.search(r"\(([A-Z_]+)\)", res)
                expect = {"kind": "STOP", "reason": m2.group(1) if m2 else res}
            stats[expect["kind"]] += 1
            rows.append(
                {
                    "id": f"{mid}#{i + 1}",
                    "material": mid,
                    "answers": r["answers"],
                    "designated": r.get("designated"),
                    "designated_by": r.get("designated_by"),
                    "expect": expect,
                }
            )
    out.mkdir(parents=True, exist_ok=True)
    path = out / "material_rows.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    meta = {
        "source": str(src.name),
        "as_of": data.get("as_of"),
        "base": BASE,
        "rows": len(rows),
        "kinds": dict(stats),
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"회귀 행 {len(rows)}개 {dict(stats)} → {path}")


def generated_paths(out: Path) -> set[str]:
    """out 안에서 빌드가 만드는 파일들의 상대 경로(있는 것만)."""
    found = {p for p in GENERATED_FILES if (out / p).is_file()}
    for d in GENERATED_DIRS:
        found |= {f"{d}/{p.name}" for p in (out / d).glob("*.yaml")}
    return found


def check(src: Path, out: Path) -> list[str]:
    """out이 src로 빌드한 결과와 같은지. 다른 파일 목록(같으면 빈 목록)."""
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp)
        Converter(src).run(fresh)
        want, have = generated_paths(fresh), generated_paths(out)
        problems = [f"없음: {p}" for p in sorted(want - have)]
        problems += [f"원본에 없는 생성 파일: {p}" for p in sorted(have - want)]
        problems += [
            f"다름: {p}"
            for p in sorted(want & have)
            if (fresh / p).read_bytes() != (out / p).read_bytes()
        ]
    return problems


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="knowledge/ → data/real/ 규칙 빌드")
    ap.add_argument("--src", default=str(KNOWLEDGE), help="원본 폴더(기본 knowledge/)")
    ap.add_argument("--out", default=str(OUT), help="생성 폴더(기본 data/real/)")
    ap.add_argument("--check", action="store_true", help="생성물이 원본과 같은지만 확인")
    ap.add_argument(
        "--legacy-regression",
        metavar="LEGACY_DIR",
        help="기존 엔진 저장소의 판정표(tests/data/material_tables.json)로 회귀 기준을 다시 만든다",
    )
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    if args.check:
        problems = check(src, out)
        if problems:
            print(
                "data/real/이 knowledge/로 빌드한 결과와 다릅니다. "
                "`uv run python tools/build_kb.py`로 다시 빌드하세요."
            )
            print("\n".join(f"  - {p}" for p in problems))
            return 1
        print("data/real/ 최신(knowledge/와 같음)")
        return 0
    Converter(src).run(out)
    if args.legacy_regression:
        regression(Path(args.legacy_regression), out / "regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
