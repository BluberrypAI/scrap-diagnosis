"""대리 질문의 추정(질문 전략과 판정 조건의 분리, docs/engine/algorithm.md 5절).

법 규칙에는 법 문언의 조건만 둔다(예: PCB 함량 2mg/L 이상). 사용자에게 바로 묻기 어려운 사실은
답하기 쉬운 **대리 질문**(예: "PCB를 쓴 기기·절연유와 관련이 있나요?")으로 묻고, 그 답이 대상 사실의
값을 추정하게 한다. 카탈로그의 `implies`가 이 관계를 정한다.

- 추정은 저장하지 않는다. 평가할 때마다 유효 사실에 더한다. 그래서 대리 질문 답을 고치거나
  철회하면 추정도 함께 바뀐다.
- 대상 사실에 이미 값이 있으면(말·서류) 그 값이 이긴다. 예: "PCB 관련 없음"이라 했어도 성적서에
  PCB 3mg/L가 있으면 지정폐기물 규칙이 성립한다.
- 출처는 DERIVED, 상태는 CLAIMED다. 기준 미만 추정은 규칙을 거짓으로만 만들므로 증빙이 필요 없다.

보수 관계(`complement`)는 같은 시험이 함께 내는 두 수치의 합이 일정할 때 한쪽 값으로 다른 쪽을
계산한다(예: 수분함량 + 고형물함량 = 100, 폐기물공정시험기준 중량법). 양방향이고, 계산값은 원래 값의
상태(성적서면 EVIDENCED)를 이어받는다. 이 관계를 둔 사실은 대상 사실의 대리 질문이기도 하다
(둘 다 모르면 이 사실을 먼저 묻는다).
"""

from __future__ import annotations

from app.domain.facts import Fact, FactStatus
from app.domain.ranges import NumRange
from app.rules.answers import coerce_value
from app.rules.model import FactDef, KnowledgeBase


def _answer_key(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def screening_map(kb: KnowledgeBase) -> dict[str, list[str]]:
    """대상 사실 → 그 값을 추정할 수 있는 대리 질문 사실들."""
    out: dict[str, list[str]] = {}
    for fd in kb.catalog.values():
        targets = [t for ts in fd.implies.values() for t in ts]
        if fd.complement:
            targets.append(fd.complement[0])
        for t in targets:
            if fd.key not in out.setdefault(t, []):
                out[t].append(fd.key)
    return out


def _complement_value(v: object, total: float) -> object:
    if isinstance(v, NumRange):
        return NumRange(
            lo=None if v.hi is None else round(total - v.hi, 9),
            lo_inc=v.hi_inc if v.hi is not None else True,
            hi=None if v.lo is None else round(total - v.lo, 9),
            hi_inc=v.lo_inc if v.lo is not None else False,
        )
    return round(total - float(v), 9)


def _apply_complement(kb: KnowledgeBase, fd: FactDef, out: dict[str, Fact]) -> None:
    tkey, total = fd.complement
    pairs = ((fd.key, tkey), (tkey, fd.key))
    for src, dst in pairs:
        f, cur = out.get(src), out.get(dst)
        if f is None or not f.is_known or (cur is not None and cur.is_known):
            continue
        label = kb.catalog[src].label or src
        out[dst] = Fact(
            key=dst,
            value=_complement_value(f.value, total),
            status=f.status,  # 같은 시험의 값이므로 원래 값의 상태를 잇는다
            source_type="DERIVED",
            source_ref=f"complement:{src}",
            note=f"'{label}' 값에서 계산(합계 {total:g})",
            recorded_at=f.recorded_at,
        )
        return


def apply_implications(kb: KnowledgeBase, facts: dict[str, Fact]) -> dict[str, Fact]:
    """유효 사실 + 대리 질문 답에서 추정한 사실(대상에 값이 없을 때만)."""
    screens = [fd for fd in kb.catalog.values() if fd.implies or fd.complement]
    if not screens:
        return facts
    out = dict(facts)
    for fd in screens:
        if fd.complement:
            _apply_complement(kb, fd, out)
        f = facts.get(fd.key)
        if f is None or not f.is_known:
            continue
        targets = fd.implies.get(_answer_key(f.value))
        if not targets:
            continue
        label = fd.label or fd.key
        for tkey, tval in targets.items():
            cur = out.get(tkey)
            if cur is not None and cur.is_known:
                continue  # 명시된 값이 우선
            out[tkey] = Fact(
                key=tkey,
                value=coerce_value(kb.catalog[tkey], tval),
                status=FactStatus.CLAIMED,
                source_type="DERIVED",
                source_ref=f"implies:{fd.key}",
                note=f"'{label}' 답에서 추정",
                recorded_at=f.recorded_at,
            )
    return out


def assumption_notes(kb: KnowledgeBase, facts: dict[str, Fact]) -> list[str]:
    """대리 질문 답에서 추정한 사실의 안내 문장(결과 카드·인계 객체에 표시).

    추정은 시험·서류가 아니라 사용자 답에 근거하므로, 결과를 보는 사람이 알 수 있게 밝힌다.
    보수 관계(complement)로 계산한 값은 같은 시험의 값이라 여기에 넣지 않는다.
    """
    notes: list[str] = []
    parents = {fd.parent for fd in kb.catalog.values() if fd.parent}
    for key, f in sorted(facts.items()):
        if f.hedged and f.is_known and key in parents:
            continue  # 상위 분류(소재 분류)는 세부 값(소재) 안내로 충분
        if f.hedged and f.is_known:  # 사용자가 추측으로 답한 값("아마 ~일걸")
            fd = kb.catalog.get(key)
            label = (fd.label or key) if fd else key
            shown = fd.value_labels.get(str(f.value), str(f.value)) if fd else str(f.value)
            if fd and fd.type == "bool":
                shown = "예" if f.value else "아니오"
            notes.append(
                f"{label}: 사용자가 추측으로 답한 값('{shown}')입니다. 확실하지 않으면 확인하세요."
            )
            continue
        if f.source_type != "DERIVED" or not (f.source_ref or "").startswith("implies:"):
            continue
        src = f.source_ref.split(":", 1)[1]
        sfd, tfd = kb.catalog.get(src), kb.catalog.get(key)
        slabel = (sfd.label or src) if sfd else src
        tlabel = (tfd.label or key) if tfd else key
        notes.append(
            f"{tlabel}: 시험값이 아니라 '{slabel}' 답에서 기준 미만으로 추정했습니다."
            " 의심되면 시험성적서로 확인하세요."
        )
    return notes
