"""문진 → 경로추천 AI 인계 객체 (docs/handoff-contract.md, diagnosis-handoff-v1).

확정할 때 한 번 만들어 판정 버전(Verdict)에 저장한다.
경로추천 AI는 이 객체만 보고 다음 행동을 정한다.
route_guidance 표는 코드가 아니라 데이터 파일(`data/<kb>/outcome_guidance.yaml`)이다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from app.domain.clock import seoul_iso
from app.domain.facts import Fact
from app.rules.evaluator import Candidate
from app.rules.model import KnowledgeBase, Rule

CONTRACT = "diagnosis-handoff-v1"

RESULT_WASTE_CODE = "WASTE_CODE"
RESULT_NO_CODE = "NO_CODE"
RESULT_TYPES = (RESULT_WASTE_CODE, RESULT_NO_CODE)

# 코드 없는 결론(규칙 엔진이 결론을 냄). 결론이 나지 않은 실패(NO_TABLE 등)는 여기 없다.
OUTCOMES = (
    "NOT_WASTE",
    "CIRCULAR_RESOURCE",
    "EXCLUDED",
    "HOUSEHOLD",
    "INTERPRETATION_NEEDED",
    "NO_GENERAL_CODE",
    "CODE_NEEDS_TEST",
    "NO_MIXTURE_RULE",
)

ACTIONS = (
    "RECOMMEND_ROUTE",
    "NO_ROUTE_NEEDED",
    "REFER_OTHER_LAW",
    "REFER_MUNICIPALITY",
    "REFER_AUTHORITY",
    "NEEDS_TEST",
    "MANUAL_CLASSIFICATION",
)

# 계약 표의 모든 행. 데이터 파일에 하나라도 빠지면 KB 로드가 실패한다.
REQUIRED_GUIDANCE: tuple[tuple[str, str | None], ...] = (
    (RESULT_WASTE_CODE, None),
    *((RESULT_NO_CODE, o) for o in OUTCOMES),
)


def result_type_of(decided: Candidate) -> str:
    return RESULT_WASTE_CODE if decided.code is not None else RESULT_NO_CODE


class RouteGuidanceOut(BaseModel):
    action: str
    summary: str
    notes: list[str] = []


class HandoffFact(BaseModel):
    value: Any
    status: str
    source_type: str


class HandoffEvidence(BaseModel):
    fact: str
    document_id: str


class HandoffBasis(BaseModel):
    id: str
    type: str
    ref: str
    excerpt: str | None = None


class HandoffTimestamps(BaseModel):
    diagnosis_started_at: str  # ISO 8601, Asia/Seoul
    confirmed_at: str  # ISO 8601, Asia/Seoul
    as_of: str  # 법 기준일(대화를 시작한 Asia/Seoul 날짜). reopen해도 바뀌지 않는다


class HandoffKB(BaseModel):
    kb_version: str
    table_id: str | None
    table_version: str | None


class Handoff(BaseModel):
    contract: str = CONTRACT
    case_id: str
    verdict_version: int
    result_type: str
    waste_code: str | None
    waste_name: str | None
    category: str | None
    outcome: str | None
    route_guidance: RouteGuidanceOut
    facts: dict[str, HandoffFact]
    evidence: list[HandoffEvidence]
    basis: list[HandoffBasis]
    review: str
    timestamps: HandoffTimestamps
    kb: HandoffKB


def build_handoff(
    kb: KnowledgeBase,
    *,
    case_id: str,
    verdict_version: int,
    decided: Candidate,
    rule: Rule | None,
    effective: dict[str, Fact],
    table_id: str | None,
    table_version: str | None,
    kb_version: str,
    diagnosis_started_at: datetime,
    confirmed_at: datetime,
    as_of: date,
) -> Handoff:
    """확정 시점의 인계 객체. 안내 항목이 없으면 KeyError(로드 때 이미 검증하므로 나오면 버그)."""
    result_type = result_type_of(decided)
    outcome = None if result_type == RESULT_WASTE_CODE else decided.outcome
    g = kb.guidance_for(result_type, outcome)
    facts: dict[str, HandoffFact] = {}
    evidence: list[HandoffEvidence] = []
    for k, f in sorted(effective.items()):
        if not f.is_known:
            continue
        d = f.model_dump(mode="json")
        facts[k] = HandoffFact(value=d["value"], status=d["status"], source_type=f.source_type)
        if f.source_type == "DOCUMENT" and f.source_ref:
            evidence.append(HandoffEvidence(fact=k, document_id=f.source_ref))
    basis = [
        HandoffBasis(id=f"B{i}", type=b.type, ref=b.ref, excerpt=b.excerpt)
        for i, b in enumerate(rule.basis if rule else (), start=1)
    ]
    return Handoff(
        case_id=case_id,
        verdict_version=verdict_version,
        result_type=result_type,
        waste_code=decided.code,
        waste_name=decided.name if decided.code is not None else None,
        category=decided.category,
        outcome=outcome,
        route_guidance=RouteGuidanceOut(action=g.action, summary=g.summary, notes=list(g.notes)),
        facts=facts,
        evidence=evidence,
        basis=basis,
        review=(rule.review if rule and rule.review else "UNVERIFIED"),
        timestamps=HandoffTimestamps(
            diagnosis_started_at=seoul_iso(diagnosis_started_at),
            confirmed_at=seoul_iso(confirmed_at),
            as_of=as_of.isoformat(),
        ),
        kb=HandoffKB(kb_version=kb_version, table_id=table_id, table_version=table_version),
    )
