"""개발자용: 엔진 규칙을 그래프로 보기(참조 화면 #/dev/rules). prod에서는 404.

규칙 테이블 하나를 "평가 순서(우선순위 단계) → 조건 → 결론" 흐름으로 바꾼다. 같은 원본 규칙에서
번호만 다르게 생성된 규칙(예: 기름 5% → 06-01-01~07)은 노드 하나로 묶는다.
판정과 무관한 보기 전용이다.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import KBDep, require_dev_endpoint
from app.api.errors import ERROR_RESPONSES, api_error
from app.domain.verdict import _value_text, fact_label
from app.rules.model import All, AnyOf, Cond, Expr, KnowledgeBase, Not, Rule

router = APIRouter(
    prefix="/dev/rules",
    tags=["dev"],
    responses=ERROR_RESPONSES,
    dependencies=[Depends(require_dev_endpoint)],
)

# 우선순위 단계(docs/engine/algorithm.md): 높은 단계가 먼저 판정을 막거나 정한다
BANDS = [
    (1100, "① 폐기물인가 (S0)"),
    (1000, "② 폐기물관리법 대상인가 (S1)"),
    (500, "③ 지정폐기물인가 (S3)"),
    (400, "④ 생활폐기물 (S2)"),
    (300, "⑤ 해석 필요"),
    (100, "⑥ 일반 분류번호"),
]
SKIP_FACTS = {"annex4_code", "material"}  # 번호 선택·소재는 노드 결론으로 보인다


class GraphRule(BaseModel):
    id: str
    source_rule: str
    title: str | None = None
    plain: str | None = None
    conditions: list[str]
    outcomes: list[str]  # 결론(번호 + 이름, 또는 코드 없는 결론)
    review: str | None = None


class GraphBand(BaseModel):
    priority: int
    label: str
    rules: list[GraphRule]


class TableGraph(BaseModel):
    table_id: str
    title: str | None
    version: str
    bands: list[GraphBand]
    mermaid: str


class TableItem(BaseModel):
    table_id: str
    title: str | None
    rules: int


def expr_text(kb: KnowledgeBase, e: Expr) -> list[str]:
    """조건식 → 사람이 읽는 줄 목록(맨 위 AND는 줄로 나눈다)."""
    if isinstance(e, All):
        return [x for it in e.items for x in expr_text(kb, it)]
    return [_one(kb, e)] if _one(kb, e) else []


def _one(kb: KnowledgeBase, e: Expr) -> str:
    if isinstance(e, Cond):
        if e.fact in SKIP_FACTS:
            return ""
        evid = " [서류]" if e.min_status.value == "EVIDENCED" else ""
        return f"{fact_label(kb, e.fact)}: {_value_text(kb, e)}{evid}"
    if isinstance(e, AnyOf):
        parts = [p for p in (_one(kb, it) for it in e.items) if p]
        return "(" + " 또는 ".join(parts) + ")" if parts else ""
    if isinstance(e, Not):
        inner = _one(kb, e.item)
        return f"아님[{inner}]" if inner else ""
    if isinstance(e, All):
        parts = [p for p in (_one(kb, it) for it in e.items) if p]
        return " 그리고 ".join(parts)
    return ""


def _outcome(kb: KnowledgeBase, r: Rule) -> str:
    t = r.then
    if t.code:
        name = t.name or (kb.codes[t.code].name if t.code in kb.codes else "")
        return f"{t.code} {name}".strip()
    return {
        "NOT_WASTE": "폐기물 아님",
        "CIRCULAR_RESOURCE": "순환자원(폐기물 아님)",
        "EXCLUDED": "폐기물관리법 적용 제외",
        "HOUSEHOLD": "생활폐기물(범위 밖)",
        "INTERPRETATION_NEEDED": "해석 필요(관할 기관 확인)",
        "NO_GENERAL_CODE": "일반 번호 없음",
        "CODE_NEEDS_TEST": "시험 필요",
        "NO_MIXTURE_RULE": "혼합물 규칙 없음",
    }.get(t.outcome or "", t.outcome or "")


def _band(priority: int) -> int:
    return next((p for p, _ in BANDS if priority >= p), BANDS[-1][0])


def build_graph(kb: KnowledgeBase, table_id: str) -> TableGraph:
    table = next((t for t in kb.tables if t.table_id == table_id), None)
    if table is None:
        raise api_error(404, "없는 규칙 테이블입니다", "TABLE_NOT_FOUND")
    grouped: dict[int, OrderedDict[str, GraphRule]] = {p: OrderedDict() for p, _ in BANDS}
    for r in sorted(table.rules, key=lambda x: -x.priority):
        src = r.source_rule or r.rule_id
        bucket = grouped[_band(r.priority)]
        conds = expr_text(kb, r.when)
        key = src + "|" + " / ".join(conds)
        if key in bucket:
            out = _outcome(kb, r)
            if out not in bucket[key].outcomes:
                bucket[key].outcomes.append(out)
            continue
        note = kb.rule_notes.get(src, {})
        bucket[key] = GraphRule(
            id=r.rule_id,
            source_rule=src,
            title=note.get("title"),
            plain=note.get("plain"),
            conditions=conds,
            outcomes=[_outcome(kb, r)],
            review=r.review,
        )
    bands = [
        GraphBand(priority=p, label=label, rules=list(grouped[p].values()))
        for p, label in BANDS
        if grouped[p]
    ]
    return TableGraph(
        table_id=table.table_id,
        title=table.title,
        version=table.version,
        bands=bands,
        mermaid=to_mermaid(table.title or table.table_id, bands),
    )


def _q(s: str) -> str:
    return s.replace('"', "#quot;").replace("<", "&lt;").replace(">", "&gt;")


def to_mermaid(title: str, bands: list[GraphBand]) -> str:
    """평가 순서대로 단계를 잇고, 단계마다 조건 → 결론 노드를 붙인다."""
    lines: list[str] = ["flowchart TD", f'  start(["{_q(title)}"])']
    prev = "start"
    for bi, band in enumerate(bands):
        b = f"B{bi}"
        lines.append(f'  {b}{{{{"{_q(band.label)}"}}}}')
        lines.append(f"  {prev} -->|해당 없으면| {b}" if bi else f"  {prev} --> {b}")
        for ri, rule in enumerate(band.rules):
            r, o = f"R{bi}_{ri}", f"O{bi}_{ri}"
            cond = "<br/>".join(_q(c) for c in rule.conditions[:6]) or "(조건 없음)"
            if len(rule.conditions) > 6:
                cond += f"<br/>…외 {len(rule.conditions) - 6}개"
            outs = rule.outcomes
            out = "<br/>".join(_q(x) for x in outs[:4]) + (
                f"<br/>…외 {len(outs) - 4}개" if len(outs) > 4 else ""
            )
            lines.append(f'  {r}["{cond}"]')
            lines.append(f'  {o}(["{out}"])')
            lines.append(f"  {b} --> {r} -->|모두 맞으면| {o}")
            lines.append(f'  click {r} call ruleClick("{_q(rule.source_rule)}")')
            lines.append(f"  class {o} outcome")
        prev = b
    lines.append("  classDef outcome fill:#e1f5ee,stroke:#0f6e56,color:#085041")
    return "\n".join(lines)


# ---- 전체 구조 한 장 ---------------------------------------------------------------------

# 폐기물관리법 시행령 별표 1(지정폐기물의 종류)의 호 이름(보기용)
LAW_ITEMS = {
    "1": "제1호 특정시설 폐기물(합성수지·합성고무·오니)",
    "2": "제2호 부식성 폐기물(폐산·폐알칼리)",
    "3": "제3호 유해물질 함유 폐기물(광재·분진·소각재 등)",
    "4": "제4호 폐유기용제",
    "5": "제5호 폐페인트·폐래커",
    "6": "제6호 폐유",
    "7": "제7호 폐석면",
    "8": "제8호 PCB 함유 폐기물",
    "9": "제9호 유해화학물질 폐기",
    "10": "제10호 의료폐기물",
}
COMMON = [
    ("S0", "① 폐기물인가 (S0)", ("S0-",), "OUT_NOT", "폐기물 아님·순환자원 / 해석 필요"),
    ("S1", "② 폐기물관리법 대상인가 (S1)", ("S1-EX",), "OUT_EX", "폐기물관리법 적용 제외"),
    ("S2", "③ 사업장폐기물인가 (S2)", ("S2-",), "OUT_HH", "생활폐기물(범위 밖)"),
]


class OverviewNode(BaseModel):
    title: str
    detail: list[str] = []  # 클릭하면 보일 규칙·소재 목록


class Overview(BaseModel):
    mermaid: str
    nodes: dict[str, OverviewNode]
    stats: dict[str, int]


def _item_of(r: Rule) -> str | None:
    import re

    loc = r.basis[0].location if r.basis else ""
    m = re.search(r"제(\d+)호", loc or "")
    return m.group(1) if m else None


def _law_node(item, item_rules, nodes, note, n_materials, indent) -> str:  # noqa: ANN001
    iid = f"L{item}"
    name = LAW_ITEMS.get(item, f"제{item}호")
    nodes[iid] = OverviewNode(
        title=f"{name} · 소재 {n_materials}개에 적용",
        detail=[note(s) for s in sorted(item_rules[item])],
    )
    return f'{indent}{iid}["{_q(name)}<br/>규칙 {len(item_rules[item])}개"]'


def build_overview(kb: KnowledgeBase) -> Overview:
    """전체 규칙 구조: 공통 단계 → 소재 분류 → 지정폐기물 법 조항 → 결론."""
    mat = kb.catalog.get("material")
    grp = kb.catalog.get("material_group")
    parent = dict(mat.value_parent) if mat else {}
    group_label = dict(grp.value_labels) if grp else {}
    group_mats: dict[str, list[str]] = {}
    group_items: dict[str, dict[str, int]] = {}
    item_rules: dict[str, set[str]] = {}
    for t in kb.tables:
        mid = t.applies_when.value if isinstance(t.applies_when, Cond) else t.table_id
        g = parent.get(str(mid), "special")
        group_mats.setdefault(g, []).append(t.title or t.table_id)
        seen: set[str] = set()
        for r in t.rules:
            if 500 <= r.priority < 1000:
                item = _item_of(r)
                if item:
                    item_rules.setdefault(item, set()).add(r.source_rule or r.rule_id)
                    if item not in seen:
                        seen.add(item)
                        group_items.setdefault(g, {}).setdefault(item, 0)
                        group_items[g][item] += 1
    nodes: dict[str, OverviewNode] = {}

    def note(src: str) -> str:
        n = kb.rule_notes.get(src, {})
        return f"{src}: {n.get('plain') or n.get('title') or ''}".strip()

    lines = ["flowchart TD", '  START(["문진 시작: 소재·상태·답변"])']
    prev = "START"
    for nid, label, prefixes, out_id, out_label in COMMON:
        srcs = sorted(k for k in kb.rule_notes if k.startswith(prefixes))
        lines.append(f'  {nid}{{{{"{_q(label)}<br/>규칙 {len(srcs)}개"}}}}')
        lines.append(f"  {prev} --> {nid}")
        lines.append(f'  {out_id}(["{_q(out_label)}"])')
        lines.append(f"  {nid} -.->|해당하면| {out_id}")
        lines.append(f"  class {out_id} stop")
        lines.append(f'  click {nid} call ruleClick("{nid}")')
        nodes[nid] = OverviewNode(title=label, detail=[note(s) for s in srcs])
        prev = nid
    lines.append('  subgraph GROUPS["소재 분류(소재별 규칙 표)"]')
    order = list(group_label)
    for g in sorted(group_mats, key=lambda x: order.index(x) if x in order else 99):
        gid = f"G_{g}"
        name = group_label.get(g, g)
        lines.append(f'    {gid}["{_q(name)}<br/>소재 {len(group_mats[g])}개"]')
        nodes[gid] = OverviewNode(title=name, detail=sorted(group_mats[g]))
    lines.append("  end")
    lines.append(f"  {prev} -->|사업장폐기물이면 소재별로| GROUPS")
    # 거의 모든 소재에 걸리는 조항(기름·PCB·유해화학물질)은 '공통 오염 확인'으로 묶어
    # 선 하나로 잇는다
    total = sum(len(v) for v in group_mats.values())
    covered = {
        item: sum(items.get(item, 0) for items in group_items.values()) for item in item_rules
    }
    common = {item for item, n in covered.items() if n >= total * 0.7}
    lines.append('  subgraph LAW["지정폐기물 기준(시행령 별표 1)"]')
    lines.append('    subgraph COMMONLAW["모든 소재 공통: 오염 확인"]')
    for item in sorted(common, key=int):
        lines.append(_law_node(item, item_rules, nodes, note, covered[item], indent="      "))
    lines.append("    end")
    for item in sorted(set(item_rules) - common, key=int):
        lines.append(_law_node(item, item_rules, nodes, note, covered[item], indent="    "))
    lines.append("  end")
    lines.append("  GROUPS -->|모든 소재| COMMONLAW")
    for g, items in group_items.items():
        for item, n in sorted(items.items(), key=lambda x: int(x[0])):
            if item not in common:
                lines.append(f"  G_{g} -->|소재 {n}| L{item}")
    lines += [
        '  DES(["지정폐기물 분류번호"])',
        '  INT(["해석 필요(관할 기관 확인)"])',
        '  GEN(["일반 분류번호(사업장일반폐기물)"])',
        "  LAW -->|하나라도 맞으면| DES",
        "  GROUPS -->|잔류물 등 법 조문만으로 못 정함| INT",
        "  GROUPS -->|지정 기준에 해당 없으면| GEN",
        "  class DES,INT,GEN outcome",
        "  classDef outcome fill:#e1f5ee,stroke:#0f6e56,color:#085041",
        "  classDef stop fill:#f1efe8,stroke:#888780,color:#444441",
    ]
    for gid in (k for k in nodes if k.startswith(("G_", "L"))):
        lines.append(f'  click {gid} call ruleClick("{gid}")')
    stats = {
        "materials": sum(len(v) for v in group_mats.values()),
        "law_rules": len(kb.rule_notes),
        "tables": len(kb.tables),
        "engine_rules": sum(len(t.rules) for t in kb.tables),
    }
    return Overview(mermaid="\n".join(lines), nodes=nodes, stats=stats)


@router.get("/overview", response_model=Overview)
def overview(kb: KBDep) -> Overview:
    """전체 규칙 구조 한 장(공통 단계 → 소재 분류 → 지정폐기물 법 조항 → 결론)."""
    return build_overview(kb)


@router.get("/tables", response_model=list[TableItem])
def list_tables(kb: KBDep) -> list[dict[str, Any]]:
    return [
        {"table_id": t.table_id, "title": t.title, "rules": len(t.rules)}
        for t in sorted(kb.tables, key=lambda t: t.title or t.table_id)
    ]


@router.get("/tables/{table_id}", response_model=TableGraph)
def table_graph(table_id: str, kb: KBDep) -> TableGraph:
    return build_graph(kb, table_id)
