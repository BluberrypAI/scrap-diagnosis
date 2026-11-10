"""문진 중 보충 설명(assist): 왜 묻는지, 왜 이 결과인지, 용어 뜻.

설계: docs/design/agent-skill-harness.md

- 판정에는 쓰지 않는다. 엔진 평가가 끝난 뒤 그 결과를 설명할 자료
  (근거 조문·쉬운 설명·용어집)만 모은다.
- 어떤 자료를 모을지는 의도(intent)에 따라 코드가 정한다(AI가 도구를 고르지 않는다).
- AI가 쓴 설명 문장은 responder가 guard로 검사하고, 실패하면 여기 template_text로 바꾼다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.agent.router import Branch, EngineStep
from app.domain.verdict import AssistSource, AssistView, TermView
from app.rules.evaluator import TV
from app.rules.glossary import find_terms
from app.rules.model import KnowledgeBase, Rule
from app.rules.selector import QuestionChoice

Intent = Literal["why", "term", "off_topic"]  # AssistView.intent와 같음
INTENTS: tuple[str, ...] = ("why", "term", "off_topic")
OFF_TOPIC_TEXT = "지금은 폐기물 분류번호를 찾는 문진만 도와드려요."
MAX_RULES = 3


class AssistContext(BaseModel):
    """설명 문장을 쓰는 데 필요한 자료. responder payload의 assist로 들어간다."""

    intent: Intent
    user_question: str | None = None
    about: Literal["question", "result", "none"] = "none"
    question: str | None = None
    option_effects: dict[str, int] = {}  # 답 → 남는 후보 수
    rules: list[dict[str, Any]] = []  # {plain, basis_ids}
    sources: list[AssistSource] = []
    terms: list[TermView] = []
    review: str | None = None

    def payload(self) -> dict[str, Any]:
        d = self.model_dump(mode="json", exclude_none=True)
        d["sources"] = [s.model_dump(mode="json") for s in self.sources]
        return d


def _rules_for_question(
    step: EngineStep, rule_index: dict[str, Rule], q: QuestionChoice | None, answered: bool
) -> list[Rule]:
    """질문의 사실이 걸린 규칙(우선순위 높은 순).

    아직 안 답한 질문이면 성립 여부를 모르는 규칙만 고른다.
    """
    if q is None:
        return []
    keys = set(q.facts or [q.key])
    found: list[Rule] = []
    for r in step.evaluation.rule_results:
        if not answered and r.status != TV.UNKNOWN:
            continue
        rule = rule_index.get(r.rule_id)
        if rule is not None and rule.facts() & keys:
            found.append(rule)
    found.sort(key=lambda x: -x.priority)
    out: list[Rule] = []
    seen: set[str] = set()
    for rule in found:  # 같은 원본 규칙(소재만 다른 생성 규칙)은 한 번만
        k = rule.source_rule or rule.rule_id
        if k not in seen:
            seen.add(k)
            out.append(rule)
    return out[:MAX_RULES]


def build_context(
    kb: KnowledgeBase,
    step: EngineStep,
    rule_index: dict[str, Rule],
    intent: Intent,
    user_question: str | None,
    answered_question: QuestionChoice | None = None,
) -> AssistContext:
    """answered_question: 같은 메시지에 답과 질문이 함께 오면 방금 답한 질문을 설명한다."""
    ctx = AssistContext(intent=intent, user_question=user_question)
    d, ev = step.decision, step.evaluation
    q = answered_question or d.question
    if intent == "why":
        if answered_question is None and d.branch == Branch.FINAL_REVIEW and ev.decided:
            ctx.about = "result"
            rule = rule_index.get(ev.decided.rule_ids[0])
            rules = [rule] if rule else []
        else:
            ctx.about = "question" if q is not None else "none"
            rules = _rules_for_question(step, rule_index, q, answered_question is not None)
            if q is not None:
                ctx.question = q.question_hint
                top = next((e for e in q.score_breakdown if e.key == q.key), None)
                if top is not None:
                    ctx.option_effects = dict(top.outcomes)
        n = 0
        for rule in rules:
            ids = []
            for b in rule.basis[:2]:
                n += 1
                sid = f"S{n}"
                ids.append(sid)
                ctx.sources.append(AssistSource(id=sid, type=b.type, ref=b.ref, excerpt=b.excerpt))
            note = kb.rule_notes.get(rule.source_rule or "", {})
            ctx.rules.append({"plain": note.get("plain") or "", "basis_ids": ids})
            if rule.review == "UNVERIFIED":
                ctx.review = "UNVERIFIED"
    if intent in ("why", "term"):
        texts = [user_question, q.question_hint if q else None]
        ctx.terms = [
            TermView(term=e.term, plain=e.plain, example=e.example)
            for e in find_terms(kb.glossary, *texts)
        ][:4]
    return ctx


def template_text(ctx: AssistContext) -> str:
    """AI 없이 만드는 설명(결정적). AI 응답이 검사에 걸렸을 때도 쓴다."""
    if ctx.intent == "off_topic":
        return OFF_TOPIC_TEXT
    parts: list[str] = []
    if ctx.intent == "term" or (ctx.intent == "why" and not ctx.rules):
        parts += [f"{t.term}: {t.plain}" for t in ctx.terms[:2]]
    if ctx.intent == "why":
        lead = (
            "이 결과는 다음 규칙에 따른 거예요."
            if ctx.about == "result"
            else ("이 답에 따라 적용되는 법 규칙이 달라져서 여쭤봐요.")
        )
        plains = [r["plain"] for r in ctx.rules if r.get("plain")]
        if plains:
            parts.insert(0, lead)
            parts.append(plains[0])
        if ctx.sources:
            parts.append(f"근거: {ctx.sources[0].ref}")
    if not parts:
        parts.append("이 질문의 근거 자료를 찾지 못했어요. 관할 기관에 확인할 수 있어요.")
    if ctx.review == "UNVERIFIED":
        parts.append("검토 전 규칙이라 참고용이에요.")
    return " ".join(parts)


def to_view(ctx: AssistContext, text: str) -> AssistView:
    return AssistView(
        intent=ctx.intent, text=text, sources=ctx.sources, terms=ctx.terms, review=ctx.review
    )
