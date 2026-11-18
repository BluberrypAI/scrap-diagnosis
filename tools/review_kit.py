"""도메인 전문가 규칙 검토 도구.

    uv run python tools/review_kit.py export             # build/review/에 검토 카드·검토표
    uv run python tools/review_kit.py import 검토표.csv  # 채운 검토표 → reviews.yaml
    uv run python tools/review_kit.py import 검토표.csv --dry-run
    uv run python tools/review_kit.py status              # 검토 현황

import 뒤에는 `uv run python tools/build_kb.py`로 다시 빌드해야 엔진에 반영된다
(생성 규칙의 review가 바뀐다). 흐름은 knowledge/README.md "검토하는 방법".
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import string
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_kb import iter_leaves  # noqa: E402
from kb_review import (  # noqa: E402
    DEF_PREFIX,
    MATERIAL_PREFIX,
    STATUS_ALIASES,
    STATUS_LABEL,
    Unit,
    dump_reviews,
    latest_reviews,
    load_reviews,
    unit_status,
    units_from,
)

from app.rules.glossary import find_terms, parse_glossary  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
DATA = ROOT / "data" / "real"
OUT = ROOT / "build" / "review"

CSV_COLUMNS = (
    "검토 단위",
    "내용 해시",
    "종류",
    "제목",
    "근거 조문",
    "생성 규칙 수",
    "현재 상태",
    "검토 결과(맞음/고쳐야 함/틀림)",
    "검토자",
    "검토일(YYYY-MM-DD)",
    "의견",
    "엔진에서",  # 참고용(가져오기에서 읽지 않음): 결론을 냄 / 다른 규칙의 조건 / 엔진 미사용
)
KIND_LABEL = {
    "LAW_RULE": "법 규칙",
    "DEFINITION": "공통 정의",
    "MATERIAL": "소재",
    "CODE_MAP": "번호 대응표",
}
CONCLUDES = {
    "DESIGNATED": "지정폐기물",
    "NOT_DESIGNATED": "지정폐기물 아님",
    "BUSINESS": "사업장폐기물",
    "HOUSEHOLD": "생활폐기물",
    "EXCLUDED": "폐기물관리법 적용 제외",
    "NOT_WASTE": "폐기물 아님",
    "CIRCULAR_RESOURCE": "순환자원",
    "WASTE": "폐기물",
    "APPLIES": "폐기물관리법 적용",
    "NEEDS_INTERPRETATION": "해석 필요(관할 기관 확인)",
}
OPS = {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥"}
# 생성 규칙의 결론 → 엔진 결론 문구
ENGINE_OUTCOME = {
    "INTERPRETATION_NEEDED": "해석 필요(관할 기관 확인)",
    "NOT_WASTE": "폐기물 아님",
    "CIRCULAR_RESOURCE": "순환자원(폐기물 아님)",
    "EXCLUDED": "폐기물관리법 적용 제외",
    "HOUSEHOLD": "생활폐기물",
    "NO_GENERAL_CODE": "일반 번호 없이 담당자 확인 안내",
    "CODE_NEEDS_TEST": "번호를 정하려면 시험 필요 안내",
    "NO_MIXTURE_RULE": "혼합물: 소재별 분리 문진 안내",
    "DESIGNATED_CODE_NEEDED": "지정폐기물이나 세부 번호는 확인 필요(지정폐기물 허가 업체 안내)",
}
ENGINE_USE = {
    "CONCLUDES": "결론을 내는 규칙",
    "CONDITION": "조건으로 쓰임",
    "UNUSED": "엔진 미사용",
}


def engine_label(then: dict) -> str:
    code, cat = then.get("code"), then.get("category")
    if code and cat == "DESIGNATED":
        return "지정폐기물(별표 4 번호)"
    if code:
        return "사업장일반폐기물(별표 4 번호)"
    out = then.get("outcome")
    return ENGINE_OUTCOME.get(out, out or "?")


def read(p: Path) -> Any:
    with p.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---- 원본 읽기와 문장 만들기 ---------------------------------------------------------------


class Knowledge:
    def __init__(self, src: Path = KNOWLEDGE, data: Path = DATA):
        self.src = src
        self.facts: dict[str, dict] = read(src / "facts.yaml")
        base = read(src / "law_rules" / "scope_and_business.yaml")
        self.stages: dict[str, dict] = base.get("stages") or {}
        self.rules: dict[str, dict] = {r["id"]: r for r in base["rules"]}
        designated = read(src / "law_rules" / "designated.yaml")["rules"]
        self.rules.update({r["id"]: r for r in designated})
        mats = read(src / "materials.yaml")
        self.materials: dict[str, dict] = mats["materials"]
        self.groups: dict[str, dict] = mats.get("groups") or {}
        self.code_map: dict = read(src / "code_map.yaml")
        defs_path = src / "definitions.yaml"
        self.defs: dict[str, dict] = (
            ((read(defs_path) or {}).get("definitions") or {}) if defs_path.exists() else {}
        )
        self.codes: dict[str, dict] = {c["id"]: c for c in read(src / "annex4_codes.yaml")["codes"]}
        self.sources: dict[str, dict] = read(src / "sources.yaml")
        self.units = units_from(src)
        self.latest = latest_reviews(load_reviews(src / "reviews.yaml"))
        self.fanout, self.tables = self._fanout(data)
        self.reg_rows = self._regression_rows(data)

    # 생성 규칙이 각 검토 단위에 얼마나 기대는지(영향 크기)와 엔진이 실제로 내는 결론
    def _fanout(self, data: Path) -> tuple[Counter, dict[str, set[str]]]:
        n: Counter = Counter()
        tables: dict[str, set[str]] = defaultdict(set)
        self.engine: dict[str, set[str]] = defaultdict(set)  # 원본 규칙 → 엔진 결론 문구
        self.table_codes: dict[str, set[str]] = defaultdict(set)  # 소재 → 생성 규칙의 번호
        files = [(p, p.stem) for p in sorted((data / "rules" / "tables").glob("*.yaml"))]
        common = sorted((data / "rules" / "common").glob("*.yaml"))
        files += [(p, "(모든 소재 공통)") for p in common]
        for p, where in files:
            for r in read(p).get("rules") or []:
                for u in r.get("review_units") or []:
                    n[u] += 1
                    tables[u].add(where)
                if r.get("source_rule"):
                    self.engine[r["source_rule"]].add(engine_label(r.get("then") or {}))
                code = (r.get("then") or {}).get("code")
                if code and where != "(모든 소재 공통)":
                    self.table_codes[where].add(code)
        return n, tables

    def engine_use(self, uid: str) -> str:
        """CONCLUDES(그 규칙으로 결론) | CONDITION(다른 규칙의 조건으로만) | UNUSED."""
        if self.engine.get(uid):
            return "CONCLUDES"
        return "CONDITION" if self.fanout.get(uid) else "UNUSED"

    def unused_reason(self, r: dict) -> str:
        leaves = iter_leaves(r.get("when") or [], self.defs)
        kinds = {c.get("value") for c in leaves if c["fact"] == "waste_kind"}
        kinds = {v for v in kinds if isinstance(v, str)}
        have = {m.get("waste_kind") for m in self.materials.values() if not m.get("unlisted")}
        missing = sorted(kinds - have)
        if missing:
            labels = ", ".join(self.value_text("waste_kind", v) for v in missing)
            return f"이 폐기물 종류({labels})를 고르는 소재가 없음. 지금 판정에는 영향이 없음"
        return "엔진은 이 결론을 따로 내지 않음(다른 결론이 아니면 다음 단계로 진행)"

    def _regression_rows(self, data: Path) -> Counter:
        n: Counter = Counter()
        path = data / "regression" / "material_rows.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                for rid in json.loads(line).get("designated_by") or []:
                    n[rid] += 1
        return n

    def status(self, u: Unit) -> str:
        return unit_status(u, self.latest)

    def fact_label(self, fid: str) -> str:
        return (self.facts.get(fid) or {}).get("label") or fid

    def value_text(self, fid: str, v: Any) -> str:
        f = self.facts.get(fid) or {}
        if isinstance(v, list):
            return ", ".join(self.value_text(fid, x) for x in v)
        if isinstance(v, bool):
            return "예" if v else "아니오"
        vals = f.get("values")
        if isinstance(vals, dict) and str(v) in {str(k) for k in vals}:
            return str(next(vals[k] for k in vals if str(k) == str(v)))
        unit = f.get("unit") or ""
        return f"{v}{unit}"

    def cond_text(self, c: dict) -> str:
        fid, op, v = c["fact"], c["op"], c.get("value")
        label, val = self.fact_label(fid), self.value_text(fid, v)
        if op == "eq":
            s = f"{label}: {val}"
        elif op == "ne":
            s = f"{label}: {val}이(가) 아님"
        elif op == "in":
            s = f"{label}: [{val}] 중 하나"
        elif op == "not_in":
            s = f"{label}: [{val}]이(가) 아님"
        elif op in OPS:
            s = f"{label} {OPS[op]} {val}"
        else:
            s = f"{label} {op} {val}"
        # 엔진의 실제 동작 기준(build_kb.py leaf): 원본의 min_status, 없으면 시험 수치만 성적서 필요
        cost = (self.facts.get(fid) or {}).get("cost")
        need = c.get("min_status") or ("EVIDENCED" if cost == "TEST" else "CLAIMED")
        if need == "EVIDENCED":
            s += " (시험성적서 필요)" if cost == "TEST" else " (서류로 확인해야 함)"
        elif cost in ("TEST", "DOCUMENT"):
            s += " (말로 답해도 됨 · 서류로 확인 가능)"
        return s

    def expr_lines(self, e: Any, depth: int = 0) -> list[str]:
        """원본 조건식 → 들여쓴 문장 목록.

        최상위 목록·all은 그냥 나열한다(카드 제목이 '모두 만족').
        """
        pad = "  " * depth
        if isinstance(e, list):
            e = {"all": e}
        if "all" in e:
            if depth == 0:
                return [x for it in e["all"] for x in self.expr_lines(it, 0)]
            return [f"{pad}다음을 모두 만족:"] + [
                x for it in e["all"] for x in self.expr_lines(it, depth + 1)
            ]
        if "any" in e:
            return [f"{pad}다음 중 하나 이상:"] + [
                x for it in e["any"] for x in self.expr_lines(it, depth + 1)
            ]
        if "not" in e:
            return [f"{pad}다음이 아님:"] + self.expr_lines(e["not"], depth + 1)
        if "ref" in e:
            d = self.defs.get(e["ref"]) or {}
            head = f"{pad}[공통 정의 {e['ref']}] {d.get('plain') or d.get('title') or ''}".rstrip()
            return [head] + (self.expr_lines(d["when"], depth + 1) if d.get("when") else [])
        return [f"{pad}{'· ' if depth else ''}{self.cond_text(e)}"]

    def source_text(self, source: str, location: str | None) -> str:
        src = self.sources.get(source) or {}
        title = src.get("title") or source
        loc = location or ""
        # 제목과 위치가 같은 별표면 겹치지 않게
        # 예: "… 시행령 별표 1(지정폐기물의 종류)" + "별표 1 제8호"
        m = re.match(r"(별표\s*\d+(?:의\d+)?)", loc)
        if m and m.group(1) in title:
            title = title[: title.index(m.group(1))].strip()
        parts = [f"{title} {loc}".strip()]
        if src.get("version"):
            parts.append(str(src["version"]))
        if src.get("effective_on"):
            parts.append(f"{src['effective_on']} 시행")
        return " · ".join(parts)

    def code_prefixes(self, rule_id: str) -> list[str]:
        m = self.code_map.get("designated") or {}
        keys = [k for k in m if rule_id.startswith(k)]
        return list(m[max(keys, key=len)]) if keys else []

    def code_names(self, prefixes: list[str], section: str | None = None) -> list[str]:
        out = []
        for cid, c in self.codes.items():
            if section and c.get("section") != section:
                continue
            if any(cid.startswith(p) for p in prefixes):
                out.append(f"{cid} {c.get('name', '')}")
        return out


# ---- 카드 내용 ----------------------------------------------------------------------------


def card(k: Knowledge, u: Unit) -> dict:
    st = k.status(u)
    rec = k.latest.get(u.unit)
    base = {
        "unit": u.unit,
        "kind": u.kind,
        "kind_label": KIND_LABEL[u.kind],
        "hash": u.hash,
        "title": u.title,
        "status": st,
        "status_label": STATUS_LABEL[st],
        "fanout": k.fanout.get(u.unit, 0),
        "tables": len(k.tables.get(u.unit, ())),
        "last": rec,
        "rows": [],  # (항목, 내용 목록)
        "location": "",
        "engine": k.engine_use(u.unit),
    }
    rows = base["rows"]
    if u.kind == "LAW_RULE":
        r = u.content
        stage = k.stages.get(r.get("stage"), {}).get("title", r.get("stage"))
        base["location"] = k.source_text(r["source"], r.get("location"))
        rows.append(("단계", [f"{r.get('stage')} {stage}"]))
        if r.get("plain"):
            rows.append(("쉬운 설명", [r["plain"]]))
        if r.get("complement_of"):
            comp = r["complement_of"]
            comp = comp if isinstance(comp, list) else [comp]
            names = ", ".join(CONCLUDES.get(c, c) for c in comp)
            rows.append(("조건", [f"{names}에 해당하는 규칙이 모두 확실히 거짓일 때"]))
        else:
            conds = k.expr_lines(r.get("when") or [])
            rows.append(("조건(모두 만족)", conds or ["(조건 없음)"]))
        concl = [CONCLUDES.get(r["concludes"], r["concludes"])]
        if r["concludes"] == "DESIGNATED":
            pre = k.code_prefixes(r["id"])
            if pre:
                concl.append("별표 4 번호 범위: " + ", ".join(pre) + " (번호 대응표)")
        rows.append(("원본 결론", concl))
        rows.append(("엔진 결론", engine_rows(k, r, base["engine"])))
        exc = exception_rows(k, r)
        if exc:
            rows.append(("제외", exc))
        quote = [f"{base['location']}", f"“{r['quote']}”"] if r.get("quote") else [base["location"]]
        rows.append(("근거", quote))
        for s in r.get("supporting") or []:
            line = k.source_text(s["source"], s.get("location"))
            extra = [f"“{s['quote']}”"] if s.get("quote") else []
            if s.get("note"):
                extra.append(f"({s['note']})")
            rows.append(("보조 근거", [line, *extra]))
        if r.get("gaps"):
            rows.append(("확인하지 못한 점", list(r["gaps"])))
        n_reg = k.reg_rows.get(r["id"], 0)
        rows.append(
            (
                "영향",
                [
                    f"생성 규칙 {base['fanout']}개, 소재 테이블 {base['tables']}개",
                    *([f"기존 엔진 판정표에서 이 규칙으로 지정된 행 {n_reg}개"] if n_reg else []),
                ],
            )
        )
    elif u.kind == "DEFINITION":
        d = u.content
        base["location"] = k.source_text(d["source"], d.get("location")) if d.get("source") else ""
        if d.get("plain"):
            rows.append(("쉬운 설명", [d["plain"]]))
        rows.append(("조건", k.expr_lines(d.get("when") or [])))
        if d.get("quote"):
            rows.append(("근거", [base["location"], f"“{d['quote']}”"]))
        name = u.unit.removeprefix(DEF_PREFIX)
        users = sorted(
            rid
            for rid, rr in k.rules.items()
            if any(c.get("ref") == name for c in _refs(rr.get("when") or []))
        )
        rows.append(("쓰는 법 규칙", users or ["(없음)"]))
        rows.append(("영향", [f"생성 규칙 {base['fanout']}개 (이 정의를 고치면 함께 바뀜)"]))
    elif u.kind == "MATERIAL":
        m = u.content
        grp = (k.groups.get(m.get("group")) or {}).get("label", m.get("group"))
        rows.append(("소재 분류", [grp]))
        if m.get("waste_kind"):
            rows.append(("폐기물 종류", [k.value_text("waste_kind", m["waste_kind"])]))
        if m.get("presets"):
            rows.append(
                (
                    "소재가 정하는 사실",
                    [f"{k.fact_label(f)}: {k.value_text(f, v)}" for f, v in m["presets"].items()],
                )
            )
        codes = m.get("codes") or {}
        if codes.get("GENERAL"):
            gen = codes["GENERAL"]
            rows.append(("일반 번호 후보", k.code_names(gen, "GENERAL") or gen))
        if codes.get("DESIGNATED"):
            des = codes["DESIGNATED"]
            rows.append(("지정 번호 후보", k.code_names(des, "DESIGNATED") or des))
        mid = u.unit.removeprefix(MATERIAL_PREFIX)
        made = k.table_codes.get(mid, set())
        if made:
            own = [
                c
                for c in sorted(made)
                if any(
                    c.startswith(p)
                    for p in [*(codes.get("GENERAL") or []), *(codes.get("DESIGNATED") or [])]
                )
            ]
            other = [c for c in sorted(made) if c not in own]
            lines = [f"{c} {k.codes.get(c, {}).get('name', '')}".strip() for c in own]
            if other:
                lines.append(
                    "다른 지정폐기물 규칙(기름·PCB·유해화학물질 등)이 성립할 때: "
                    + ", ".join(other)
                )
            rows.append(("엔진이 실제로 내는 번호", lines))
            idle = [
                p
                for p in [*(codes.get("GENERAL") or []), *(codes.get("DESIGNATED") or [])]
                if not any(c.startswith(p) for c in made)
            ]
            if idle:
                rows.append(
                    (
                        "쓰이지 않는 후보",
                        [
                            f"{p}: 이 소재의 조건(소재가 정하는 사실 등)으로는 "
                            "이 번호가 나오지 않음"
                            for p in idle
                        ],
                    )
                )
        flags = []
        if m.get("code_needs_test"):
            flags.append("번호를 정하려면 시험이 필요함(시험 필요 안내로 끝남)")
        if m.get("no_general_code"):
            flags.append("혼합물이라 일반 번호를 정하지 않음(소재별로 나눠 문진)")
        if m.get("unlisted"):
            flags.append("목록에 보이지 않는 소재(빌드하지 않음)")
        if flags:
            rows.append(("특이 사항", flags))
        if m.get("note"):
            rows.append(("메모", [str(m["note"])]))
        if m.get("aliases"):
            rows.append(("다른 이름", [", ".join(m["aliases"])]))
        rows.append(("영향", [f"이 소재 테이블의 생성 규칙 {base['fanout']}개"]))
        rows.append(("참고", ["소재는 법 판단을 하지 않는다. 지정폐기물 여부는 법 규칙이 정한다."]))
    else:
        cm = u.content
        lines = [f"{pre} → {', '.join(v)}" for pre, v in (cm.get("designated") or {}).items()]
        rows.append(("지정폐기물 규칙 → 별표 4 번호 범위", lines))
        gk = cm.get("general_by_kind") or {}
        if gk:
            rows.append(
                (
                    "폐기물 종류 → 일반 번호 범위",
                    [
                        f"{k.value_text('waste_kind', kind)} → {', '.join(v)}"
                        for kind, v in gk.items()
                    ],
                )
            )
        if cm.get("excluded_codes"):
            rows.append(("쓰지 않는 번호", [", ".join(cm["excluded_codes"])]))
        rows.append(("영향", [f"생성 규칙 {base['fanout']}개"]))
    return base


def _refs(e: Any):
    """조건식 안의 {ref: …} 항목들."""
    if isinstance(e, list):
        for x in e:
            yield from _refs(x)
    elif "all" in e or "any" in e:
        yield from _refs(e.get("all") or e.get("any"))
    elif "not" in e:
        yield from _refs(e["not"])
    elif "ref" in e:
        yield e


def engine_rows(k: Knowledge, r: dict, use: str) -> list[str]:
    """법 규칙 카드의 '엔진 결론' 행."""
    if use == "UNUSED":
        return [f"엔진 미사용: {k.unused_reason(r)}"]
    if use == "CONDITION":
        if r.get("stage") == "S2":
            return [
                "이 규칙 자체는 결론을 내지 않음. 생활폐기물 규칙(S2-HOUSEHOLD)의"
                " 판단 조건으로 쓰임:"
                " 사업장 조건이 모두 거짓일 때만 생활폐기물"
            ]
        return ["다른 규칙의 조건으로만 쓰임(예: 다른 지정폐기물 규칙의 제외 조건)"]
    out = sorted(k.engine[r["id"]])
    original = CONCLUDES.get(r["concludes"], r["concludes"])
    law = (k.sources.get(r["source"]) or {}).get("evidence", "LAW") == "LAW"
    if r.get("conclusion") == "interpret":
        out.append(f"원본에서 해석 필요로 끝내도록 정함(원본 결론: {original})")
    elif not law and r["concludes"] in ("DESIGNATED", "NOT_WASTE", "CIRCULAR_RESOURCE"):
        out.append(
            f"근거가 법령이 아니라(질의회신·해설) 원본 결론({original}) 대신 해석 필요로 끝냄"
        )
    return out


def exception_rows(k: Knowledge, r: dict) -> list[str]:
    """법 규칙의 예외(exceptions): 그 규칙들이 성립하면 이 규칙은 적용하지 않는다."""
    out = []
    for e in r.get("exceptions") or []:
        names = []
        for p in e["unless_any"]:
            items = sorted(
                {str(x.get("item") or x["id"]) for x in k.rules.values() if x["id"].startswith(p)}
            )
            if items:
                more = " 등" if len(items) > 2 else ""
                names.append(f"{p}* ({', '.join(items[:2])}{more})")
        out.append("다음 규칙이 성립하면 이 규칙은 적용하지 않음: " + "; ".join(names))
        if e.get("plain"):
            out.append(e["plain"])
        if e.get("quote"):
            out.append(f"근거: {e.get('location') or ''} “{e['quote']}”".replace("  ", " "))
    return out


def add_glossary(k: Knowledge, c: dict) -> None:
    """카드 글에 나온 전문용어의 쉬운 설명을 "용어 풀이" 행으로 붙인다(knowledge/glossary.yaml)."""
    path = k.src / "glossary.yaml"
    if not hasattr(k, "_glossary"):
        k._glossary = parse_glossary(read(path)) if path.exists() else ()
    texts = [c["title"], c["location"], *(x for _, items in c["rows"] for x in items)]
    found = find_terms(k._glossary, *texts)
    if found:
        c["rows"].append(("용어 풀이", [f"{e.term}: {e.plain}" for e in found]))


def all_cards(k: Knowledge) -> list[dict]:
    order = {"LAW_RULE": 0, "DEFINITION": 1, "CODE_MAP": 2, "MATERIAL": 3}
    cards = [card(k, u) for u in k.units.values()]
    for c in cards:
        add_glossary(k, c)
    return sorted(cards, key=lambda c: (order[c["kind"]], -c["fanout"], c["unit"]))


# ---- 내보내기 -----------------------------------------------------------------------------


def write_csv(cards: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:  # BOM: 엑셀에서 한글이 깨지지 않게
        w = csv.writer(fh)
        w.writerow(CSV_COLUMNS)
        for c in cards:
            w.writerow(
                [
                    c["unit"],
                    c["hash"],
                    c["kind_label"],
                    c["title"],
                    c["location"],
                    c["fanout"],
                    c["status_label"],
                    "",
                    "",
                    "",
                    "",
                    ENGINE_USE[c["engine"]],
                ]
            )


def write_html(cards: list[dict], path: Path, rev: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = Counter(c["status"] for c in cards)
    kinds = Counter(c["kind"] for c in cards)
    esc = html.escape

    def card_html(c: dict) -> str:
        rows = "".join(
            f"<dt>{esc(name)}</dt><dd>{''.join(f'<p>{esc(str(x))}</p>' for x in items)}</dd>"
            for name, items in c["rows"]
        )
        last = c["last"]
        last_html = (
            "<p class='last'>마지막 검토: "
            f"{esc(STATUS_LABEL.get(last['status'], last['status']))} · "
            f"{esc(str(last.get('reviewer', '')))} · {esc(str(last.get('reviewed_at', '')))}"
            + (f" · {esc(str(last.get('comment')))}" if last.get("comment") else "")
            + "</p>"
            if last
            else ""
        )
        search = " ".join([c["unit"], c["title"], c["location"]]).lower()
        return (
            f"<article class='card' data-status='{c['status']}' data-kind='{c['kind']}' "
            f"data-engine='{c['engine']}' data-search='{esc(search)}'>"
            f"<header><span class='chip s-{c['status']}'>{esc(c['status_label'])}</span>"
            + (
                f"<span class='eng-UNUSED'>{ENGINE_USE['UNUSED']}</span>"
                if c["engine"] == "UNUSED"
                else ""
            )
            + f"<span class='kind'>{esc(c['kind_label'])}</span>"
            f"<code class='uid'>{esc(c['unit'])}</code></header>"
            f"<h3>{esc(str(c['title']))}</h3><dl>{rows}</dl>{last_html}"
            f"<footer>내용 해시 <code>{esc(c['hash'])}</code> · "
            "검토표(CSV)의 같은 행에 결과를 적어 주세요"
            f"</footer></article>"
        )

    status_buttons = "".join(
        f"<button type='button' data-f='{s}'>{esc(STATUS_LABEL[s])} {counts.get(s, 0)}</button>"
        for s in ("UNVERIFIED", "STALE", "NEEDS_CHANGE", "REJECTED", "VERIFIED")
    )
    kind_buttons = "".join(
        f"<button type='button' data-k='{k}'>{esc(KIND_LABEL[k])} {kinds.get(k, 0)}</button>"
        for k in ("LAW_RULE", "DEFINITION", "CODE_MAP", "MATERIAL")
    )
    engines = Counter(c["engine"] for c in cards)
    engine_buttons = "".join(
        f"<button type='button' data-e='{e}'>{esc(ENGINE_USE[e])} {engines.get(e, 0)}</button>"
        for e in ("CONCLUDES", "CONDITION", "UNUSED")
    )
    body = "".join(card_html(c) for c in cards)
    page = string.Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        rev=esc(rev),
        total=len(cards),
        verified=counts.get("VERIFIED", 0),
        status_buttons=status_buttons,
        kind_buttons=kind_buttons,
        engine_buttons=engine_buttons,
        cards=body,
        today=date.today().isoformat(),
    )
    path.write_text(page, encoding="utf-8", newline="\n")


TEMPLATE = Path(__file__).with_name("review_cards.html")  # 검토 카드 HTML 틀($이름 자리 채움)


# ---- 가져오기 -----------------------------------------------------------------------------


def import_csv(
    path: Path, src: Path = KNOWLEDGE, *, dry_run: bool = False
) -> tuple[list[dict], list[str]]:
    """검토표를 검사하고 새 기록을 만든다. 오류가 하나라도 있으면 아무것도 쓰지 않는다."""
    units = units_from(src)
    records = load_reviews(src / "reviews.yaml")
    new: list[dict] = []
    errors: list[str] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [
            c
            for c in ("검토 단위", "내용 해시", CSV_COLUMNS[7], "검토자", CSV_COLUMNS[9])
            if c not in (reader.fieldnames or [])
        ]
        if missing:
            return [], [f"검토표에 없는 열: {missing}"]
        for i, row in enumerate(reader, start=2):
            raw = (row.get(CSV_COLUMNS[7]) or "").strip()
            if not raw:
                continue  # 검토하지 않은 행
            uid = (row.get("검토 단위") or "").strip()
            where = f"{i}행({uid})"
            u = units.get(uid)
            if u is None:
                errors.append(f"{where}: 없는 검토 단위")
                continue
            status = STATUS_ALIASES.get(raw)
            if status is None:
                errors.append(
                    f"{where}: 검토 결과는 맞음 / 고쳐야 함 / 틀림 중 하나여야 합니다: {raw!r}"
                )
                continue
            h = (row.get("내용 해시") or "").strip()
            if h != u.hash:
                errors.append(
                    f"{where}: 검토한 뒤 규칙 내용이 바뀌었습니다(해시 {h} → {u.hash}). "
                    "새 검토 카드로 다시 검토해 주세요"
                )
                continue
            reviewer = (row.get("검토자") or "").strip()
            if not reviewer:
                errors.append(f"{where}: 검토자가 비어 있습니다")
                continue
            day = (row.get(CSV_COLUMNS[9]) or "").strip()
            try:
                date.fromisoformat(day)
            except ValueError:
                errors.append(f"{where}: 검토일은 YYYY-MM-DD 형식이어야 합니다: {day!r}")
                continue
            comment = (row.get("의견") or "").strip()
            if status != "VERIFIED" and not comment:
                errors.append(f"{where}: '고쳐야 함'·'틀림'은 의견이 필요합니다")
                continue
            rec = {
                "unit": uid,
                "content_hash": h,
                "status": status,
                "reviewer": reviewer,
                "reviewed_at": day,
            }
            if comment:
                rec["comment"] = comment
            new.append(rec)
    if not errors and new and not dry_run:
        dump_reviews(src / "reviews.yaml", records + new)
    return new, errors


def status_summary(src: Path = KNOWLEDGE) -> dict[str, Counter]:
    units = units_from(src)
    latest = latest_reviews(load_reviews(src / "reviews.yaml"))
    out: dict[str, Counter] = defaultdict(Counter)
    for u in units.values():
        out[KIND_LABEL[u.kind]][STATUS_LABEL[unit_status(u, latest)]] += 1
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="도메인 전문가 규칙 검토 도구")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="검토 카드(HTML)와 검토표(CSV) 만들기")
    ex.add_argument("--out", default=str(OUT))
    im = sub.add_parser("import", help="전문가가 채운 검토표를 reviews.yaml에 더하기")
    im.add_argument("csv")
    im.add_argument("--dry-run", action="store_true")
    sub.add_parser("status", help="검토 현황")
    args = ap.parse_args()

    if args.cmd == "export":
        from build_kb import check, knowledge_rev

        if check(KNOWLEDGE, DATA):
            print("data/real/이 knowledge/와 다릅니다. 먼저 tools/build_kb.py로 빌드하세요.")
            return 1
        k = Knowledge()
        cards = all_cards(k)
        out = Path(args.out)
        write_html(cards, out / "검토카드.html", knowledge_rev())
        write_csv(cards, out / "검토표.csv")
        print(f"검토 단위 {len(cards)}개 → {out / '검토카드.html'}, {out / '검토표.csv'}")
        return 0
    if args.cmd == "import":
        new, errors = import_csv(Path(args.csv), dry_run=args.dry_run)
        if errors:
            print("검토표에 문제가 있어 아무것도 반영하지 않았습니다.")
            print("\n".join(f"  - {e}" for e in errors))
            return 1
        verb = "반영할" if args.dry_run else "반영한"
        print(f"{verb} 검토 {len(new)}건: {dict(Counter(r['status'] for r in new))}")
        if new and not args.dry_run:
            print("다음: tools/build_kb.py로 다시 빌드하세요(생성 규칙의 review가 바뀝니다).")
        return 0
    for kind, c in status_summary().items():
        print(f"{kind}: {dict(c)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
