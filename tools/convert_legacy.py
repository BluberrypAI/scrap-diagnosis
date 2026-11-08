"""기존 엔진(resource_engine) 규칙 → 새 사실 카탈로그 + 소재별 PRIORITY 테이블.

    uv run python tools/convert_legacy.py --legacy C:/Users/zxc20/re_project/resource_engine
    uv run python tools/convert_legacy.py --legacy ... --regression   # 회귀 데이터도 생성

기존 엔진의 S0→S5 단계 흐름을 우선순위 대역으로 펴서 소재마다 테이블 하나로 만든다.
  SCOPE_S0 1100 / SCOPE_S1 1000 : 순환자원·폐기물 아님·법 적용 제외 (코드 없는 결론)
  DESIGNATED 500                : 법령 근거 지정폐기물 규칙 → 별표 4 지정 코드
  HOUSEHOLD 400                 : 사업장 조건이 모두 거짓 → 생활폐기물 (코드 없는 결론)
  INTERPRET 300                 : 해석 필요 규칙과 법령이 아닌 근거(질의회신·해설)의 규칙
  GENERAL 100                   : 지정폐기물이 아닐 때의 일반 코드
상위 대역이 미확인이면 하위 대역은 확정되지 않으므로 기존 단계 순서가 그대로 재현된다.
기존 YAML은 읽기만 한다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEGACY = Path("C:/Users/zxc20/re_project/resource_engine")
OUT = ROOT / "data" / "real"

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
    path.write_text(header + text, encoding="utf-8")


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


def fold(conds: list[dict], preset: dict[str, Any]) -> list[dict] | None:
    """프리셋 값으로 AND 조건을 부분 평가. 거짓이면 None, 아니면 남은 조건."""
    out = []
    for c in conds:
        if c["fact"] in preset:
            if not leaf_true(c, preset[c["fact"]]):
                return None
            continue
        out.append(c)
    return out


class Converter:
    def __init__(self, legacy: Path, overrides: Path):
        r = legacy / "rules"
        self.legacy = legacy
        self.facts: dict[str, dict] = read(r / "facts.yaml")
        rules = read(r / "rules.yaml")
        self.base_rules: list[dict] = rules["rules"]
        self.s3: list[dict] = read(r / "rules_s3.yaml")["rules"]
        m = read(r / "materials.yaml")
        self.materials: dict[str, dict] = m["materials"]
        self.groups_meta = m.get("groups") or {}
        a4 = read(r / "annex4_codes.yaml")
        self.codes: list[dict] = a4["codes"]
        self.code_index = {c["id"]: c for c in self.codes}
        self.s4 = read(r / "s4_map.yaml")
        self.sources: dict[str, dict] = read(r / "sources.yaml")
        self.ov = read(overrides) or {}
        self.excluded = set(self.s4.get("excluded_codes", []))
        self.used_facts: set[str] = set()
        self.fact_band: dict[str, int] = {}
        self.report: dict[str, Any] = defaultdict(list)

    # ---- 공통 --------------------------------------------------------------------------

    def evidence(self, source_id: str) -> str:
        return (self.sources.get(source_id) or {}).get("evidence", "LAW")

    def is_law(self, rule: dict) -> bool:
        return self.evidence(rule["source"]) == "LAW"

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
        }

    def leaf(self, c: dict, band: int) -> dict:
        fid = c["fact"]
        self.used_facts.add(fid)
        self.fact_band[fid] = max(self.fact_band.get(fid, 0), band)
        out = {"fact": fid, "op": c["op"], "value": c.get("value")}
        if self.facts.get(fid, {}).get("cost") == "TEST":
            out["min_status"] = "EVIDENCED"
        return out

    def expr(self, conds: list[dict], band: int, mid: str | None = None) -> Any:
        leaves = [self.leaf(c, band) for c in conds]
        if not leaves:
            # 조건이 모두 접혀 사라짐 → 이 테이블에서는 항상 참
            return {"fact": "material", "op": "eq", "value": mid}
        return leaves[0] if len(leaves) == 1 else {"all": leaves}

    # ---- 공통 조각: 범위·사업장 -----------------------------------------------------------

    def scope_fragment(self) -> dict:
        rules = []
        for r in self.base_rules:
            if r["stage"] == "S0" and r["concludes"] in ("NOT_WASTE", "CIRCULAR_RESOURCE"):
                prio = P_S0
                outcome = r["concludes"] if self.is_law(r) else "INTERPRETATION_NEEDED"
            elif r["stage"] == "S1" and r["concludes"] == "EXCLUDED":
                prio, outcome = P_S1, "EXCLUDED"
            else:
                continue
            rules.append(
                {
                    "rule_id": r["id"],
                    "priority": prio,
                    "when": self.expr(r["when"], 2),
                    "then": {
                        "code": None,
                        "category": "OUT_OF_SCOPE",
                        "outcome": outcome,
                        "name": r.get("plain"),
                    },
                    "basis": self.basis(r),
                    "review": r.get("review", "UNVERIFIED"),
                }
            )
        return {"rules": rules}

    def business_fragment(self) -> dict:
        alts = []
        basis = []
        for r in self.base_rules:
            if r["stage"] != "S2" or r["concludes"] != "BUSINESS":
                continue
            if any(c["fact"] == "this_waste_designated" for c in r["when"]):
                continue  # 지정폐기물 대역이 위에 있으므로 따로 둘 필요 없음
            alts.append(self.expr(r["when"], 2))
        hh = next(r for r in self.base_rules if r["id"] == "S2-HOUSEHOLD")
        basis = self.basis(hh)
        return {
            "rules": [
                {
                    "rule_id": "S2-HOUSEHOLD",
                    "priority": P_HOUSEHOLD,
                    "when": {"not": {"any": alts}},
                    "then": {
                        "code": None,
                        "category": "OUT_OF_SCOPE",
                        "outcome": "HOUSEHOLD",
                        "name": "생활폐기물(사업장폐기물이 아님)",
                    },
                    "basis": basis,
                    "review": hh.get("review", "UNVERIFIED"),
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

    def general_codes(self, mat: dict) -> tuple[list[str], str | None]:
        if mat.get("no_general_code"):
            return [], "NO_MIXTURE_RULE"
        if mat.get("code_needs_test"):
            return [], "CODE_NEEDS_TEST"
        prefixes = (mat.get("codes") or {}).get("GENERAL") or self.s4["general_by_kind"].get(
            mat.get("waste_kind"), []
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
        designated: list[tuple[dict, list[dict]]] = []
        interpret: list[tuple[dict, list[dict]]] = []
        complement = None
        for r in self.s3:
            if r.get("complement_of"):
                complement = r
                continue
            folded = fold(r["when"], preset)
            if folded is None:
                continue
            if r["concludes"] == "DESIGNATED" and self.is_law(r):
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
            for ex in self.s4.get("designated_exclusions", []):
                if not r["id"].startswith(ex["drop"]):
                    continue
                excluders = [
                    rid for rid in by_id if any(rid.startswith(p) for p in ex["if_any_fired"])
                ]
                if excluders:
                    extra.append({"not": {"any": [self.expr(by_id[x], 3, mid) for x in excluders]}})
            base_leaves = [self.leaf(c, 3) for c in folded]
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
                        "priority": P_DESIGNATED,
                        "when": when,
                        "then": {
                            "code": code,
                            "category": "DESIGNATED",
                            "name": self.code_index[code]["name"],
                        },
                        "basis": self.basis(r) + [self.code_basis(code)],
                        "review": r.get("review", "UNVERIFIED"),
                    }
                )
                if not need_choice:
                    break

        for r, folded in interpret:
            rules.append(
                {
                    "rule_id": f"{mid}:{r['id']}",
                    "priority": P_INTERPRET,
                    "when": self.expr(folded, 3, mid),
                    "then": {
                        "code": None,
                        "category": "NEEDS_INTERPRETATION",
                        "outcome": "INTERPRETATION_NEEDED",
                        "name": r.get("item"),
                    },
                    "basis": self.basis(r),
                    "review": r.get("review", "UNVERIFIED"),
                }
            )

        gcodes, goutcome = self.general_codes(mat)
        gbasis = self.basis(complement) if complement else []
        if goutcome:
            rules.append(
                {
                    "rule_id": f"{mid}:GENERAL",
                    "priority": P_GENERAL,
                    "when": {"fact": "material", "op": "eq", "value": mid},
                    "then": {"code": None, "category": "GENERAL", "outcome": goutcome},
                    "basis": gbasis,
                    "review": "UNVERIFIED",
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
                rules.append(
                    {
                        "rule_id": rid,
                        "priority": P_GENERAL,
                        "when": when,
                        "then": {
                            "code": code,
                            "category": "GENERAL",
                            "name": self.code_index[code]["name"],
                        },
                        "basis": gbasis + [self.code_basis(code)],
                        "review": "UNVERIFIED",
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
            "version": f"2026.11.0+re-{self.legacy_rev()}",
            "effective_from": EFFECTIVE_FROM,
            "hit_policy": "PRIORITY",
            "applies_when": {"fact": "material", "op": "eq", "value": mid},
            "includes": ["../common/scope.yaml", "../common/business.yaml"],
            "rules": rules,
        }

    _rev: str | None = None

    def legacy_rev(self) -> str:
        if self._rev is None:
            import subprocess

            try:
                self._rev = subprocess.run(
                    ["git", "-C", str(self.legacy), "rev-parse", "--short", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
            except Exception:  # noqa: BLE001
                self._rev = "unknown"
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
        for fid, f in self.facts.items():
            if fid in SKIP_FACTS or fid.startswith("reporting_") or fid not in self.used_facts:
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
                "question_hint": "시행규칙 별표 4의 세부분류 중 이 폐기물에 해당하는 번호",
                "help": "기존 배출자신고서나 처리 계약서의 분류번호와 명칭을 대조하세요. "
                "'그 밖의' 번호는 같은 분류의 다른 번호에 해당하지 않을 때만 고릅니다.",
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
            f"# 자동 생성: tools/convert_legacy.py (resource_engine {self.legacy_rev()}). "
            "직접 고치지 말고 변환기를 다시 실행.\n"
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
        self.write_report(out, n)
        print(f"테이블 {n}개, 사실 {len(self.used_facts)}개 → {out}")

    def write_report(self, out: Path, n: int) -> None:
        lines = [
            "# 기존 엔진 규칙 변환 보고서",
            "",
            f"- 원본: resource_engine `{self.legacy_rev()}` (rules/*.yaml)",
            f"- 소재 테이블: {n}개, 시행일 {EFFECTIVE_FROM}",
            "- 모든 규칙은 기존과 같이 `review: UNVERIFIED`다.",
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
        (out / "conversion_report.md").write_text("\n".join(lines), encoding="utf-8")


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


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy", default=str(DEFAULT_LEGACY))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--overrides", default=str(ROOT / "tools" / "legacy_overrides.yaml"))
    ap.add_argument("--regression", action="store_true", help="회귀 데이터도 생성")
    args = ap.parse_args()
    legacy, out = Path(args.legacy), Path(args.out)
    Converter(legacy, Path(args.overrides)).run(out)
    if args.regression:
        regression(legacy, out / "regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
