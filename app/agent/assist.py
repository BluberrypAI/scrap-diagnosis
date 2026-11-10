"""문진 중 보충 설명(assist): 왜 묻는지, 왜 이 결과인지, 용어 뜻.

설계: docs/design/agent-skill-harness.md

- 판정에는 쓰지 않는다. 엔진 평가가 끝난 뒤 그 결과를 설명할 자료
  (근거 조문·쉬운 설명·용어집)만 모은다.
- 어떤 자료를 모을지는 의도(intent)에 따라 코드가 정한다(AI가 도구를 고르지 않는다).
- AI가 쓴 설명 문장은 responder가 guard로 검사하고, 실패하면 여기 template_text로 바꾼다.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from app.agent.router import Branch, EngineStep
from app.domain.verdict import AssistSource, AssistView, TermView
from app.rules.evaluator import TV
from app.rules.glossary import find_terms
from app.rules.guide_index import FACT, TERM, TOPIC
from app.rules.model import KnowledgeBase, Rule
from app.rules.selector import QuestionChoice

if TYPE_CHECKING:  # 타입 표기용(순환 import 방지)
    from app.agent.web_search import WebSearch

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
    guide: list[dict[str, Any]] = []  # 질문 안내(무엇을·왜·어떻게 확인·선택지 뜻·예시·FAQ)
    topics: list[dict[str, Any]] = []  # 사용자 질문에 걸린 참고 주제(MSDS 등)
    matched: bool = False  # 사용자 질문에 직접 답할 자료(FAQ·주제·용어)를 찾았나
    chosen: list[str] = []  # 추출 AI가 뜻으로 고른 자료 id(guide_index)
    best_faq: dict[str, str] | None = (
        None  # 사용자 질문과 가장 가까운 FAQ(질문 안내·참고 주제 전체에서)
    )
    web_used: bool = False  # 자료가 없어 웹 검색 결과를 썼나
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


_BIGRAM = re.compile(r"[가-힣A-Za-z0-9]")


def _bigrams(s: str) -> set[str]:
    chars = "".join(_BIGRAM.findall(s or "")).lower()
    return {chars[i : i + 2] for i in range(len(chars) - 1)}


def _similar(question: str, candidate: str) -> float:
    """사용자 질문과 FAQ 질문의 글자 두 개 묶음 겹침 비율(0~1)."""
    a, b = _bigrams(question), _bigrams(candidate)
    return len(a & b) / len(b) if b else 0.0


FAQ_MATCH = 0.35


def _fact_guide(kb: KnowledgeBase, key: str, user_question: str | None) -> tuple[dict, bool]:
    g = (kb.question_guide.get("facts") or {}).get(key)
    if not g:
        return {}, False
    fd = kb.catalog.get(key)
    out: dict[str, Any] = {"label": (fd.label if fd else None) or key}
    for k in ("what", "why", "how_to_check", "yes_examples", "no_examples"):
        if g.get(k):
            out[k] = g[k]
    opts = g.get("options") or {}
    if opts:
        labels = dict(fd.value_labels) if fd else {}
        if fd and fd.type == "bool":
            labels = {"true": "예", "false": "아니오"}
        out["options"] = [
            {"label": labels.get(str(v), str(v)), "means": o.get("means", "")}
            for v, o in opts.items()
        ]
    faq = g.get("faq") or []
    scored = sorted(faq, key=lambda f: -_similar(user_question or "", f.get("q", "")))
    hit = bool(scored) and _similar(user_question or "", scored[0].get("q", "")) >= FAQ_MATCH
    out["faq"] = scored[:3]
    return out, hit


def _relevance(user_question: str | None, g: dict) -> float:
    text = " ".join([g.get("label") or "", g.get("what") or ""])
    faq = max(
        (_similar(user_question or "", f.get("q", "")) for f in g.get("faq") or []), default=0
    )
    return _similar(user_question or "", text) + faq


def _best_faq(user_question: str | None, guide: list[dict], topics: list[dict]) -> dict | None:
    cands = [f for g in [*guide, *topics] for f in g.get("faq") or []]
    if not cands or not user_question:
        return None
    best = max(cands, key=lambda f: _similar(user_question, f.get("q", "")))
    return best if _similar(user_question, best.get("q", "")) >= FAQ_MATCH else None


def _topic_item(name: str, tp: dict, text: str) -> dict:
    item = {"topic": name, **{k: tp[k] for k in ("plain", "detail") if tp.get(k)}}
    faq = sorted(tp.get("faq") or [], key=lambda f: -_similar(text, f.get("q", "")))
    item["faq"] = faq[:3]
    return item


def _topics(kb: KnowledgeBase, user_question: str | None, chosen: list[str]) -> list[dict]:
    """AI가 뜻으로 고른 주제(chosen) 먼저, 그다음 이름·키워드가 질문에 들어 있는 주제."""
    text = (user_question or "").lower()
    topics = kb.question_guide.get("topics") or {}
    found = [_topic_item(n, topics[n], text) for n in chosen if n in topics]
    for name, tp in topics.items():
        keys = [name, *(tp.get("keywords") or [])]
        if name not in chosen and any(k and k.lower() in text for k in keys):
            found.append(_topic_item(name, tp, text))
    return found[:3]


def build_context(
    kb: KnowledgeBase,
    step: EngineStep,
    rule_index: dict[str, Rule],
    intent: Intent,
    user_question: str | None,
    answered_question: QuestionChoice | None = None,
    web: WebSearch | None = None,
    about: list[str] | None = None,
) -> AssistContext:
    """answered_question: 같은 메시지에 답과 질문이 함께 오면 방금 답한 질문을 설명한다.

    about: 추출 AI가 '설명 자료 목록'(app/rules/guide_index.py)에서 뜻으로 고른 자료 id.
    단어가 겹치지 않는 질문도 자료를 찾게 한다. guard가 목록에 있는 id만 남긴다.
    """
    ctx = AssistContext(intent=intent, user_question=user_question, chosen=list(about or []))
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
        hits = []
        if ctx.about != "result":
            for key in (q.facts or [q.key]) if q is not None else []:
                g, hit = _fact_guide(kb, key, user_question)
                if g:
                    ctx.guide.append(g)
                hits.append(hit)
        # AI가 고른 질문 안내(지금 질문 밖의 사실이어도)
        have = {g.get("label") for g in ctx.guide}
        for aid in ctx.chosen:
            if aid.startswith(FACT):
                g, _ = _fact_guide(kb, aid[len(FACT) :], user_question)
                if g and g.get("label") not in have:
                    ctx.guide.append(g)
                    have.add(g.get("label"))
        chosen_terms = {aid[len(TERM) :] for aid in ctx.chosen if aid.startswith(TERM)}
        if chosen_terms:
            known = {x.term for x in ctx.terms}
            ctx.terms += [
                TermView(term=e.term, plain=e.plain, example=e.example)
                for e in kb.glossary
                if e.term in chosen_terms and e.term not in known
            ]
        # 사용자 질문과 가까운 안내가 앞에 오게(묶음 질문은 사실이 여럿)
        ctx.guide.sort(key=lambda g: -_relevance(user_question, g))
        chosen_topics = [aid[len(TOPIC) :] for aid in ctx.chosen if aid.startswith(TOPIC)]
        ctx.topics = _topics(kb, user_question, chosen_topics)
        ctx.best_faq = _best_faq(user_question, ctx.guide, ctx.topics)
        asked_terms = find_terms(kb.glossary, user_question)
        ctx.matched = (
            any(hits)
            or bool(ctx.chosen)
            or bool(ctx.best_faq)
            or bool(ctx.topics)
            or bool(asked_terms)
            or (intent == "why" and bool(ctx.rules or ctx.guide))
        )
        if not ctx.matched and web is not None and user_question:
            _add_web(ctx, web, user_question)
    return ctx


def _add_web(ctx: AssistContext, web: WebSearch, user_question: str) -> None:
    """준비된 자료가 없을 때만: 허용 도메인 웹 검색 결과를 근거로 붙인다(공식 확인 필요)."""
    from app.agent.web_search import safe_query  # 순환 import 방지

    query = safe_query(f"{user_question} 폐기물")
    if not query:
        return
    try:
        results = web.search(query, limit=3)
    except Exception:  # noqa: BLE001 - 검색 실패는 설명 실패일 뿐 문진은 계속한다
        return
    n = len(ctx.sources)
    for i, r in enumerate(results, start=n + 1):
        ctx.sources.append(
            AssistSource(id=f"S{i}", type="WEB", ref=r.title, excerpt=r.snippet, url=r.url)
        )
    ctx.web_used = bool(results)


def template_text(ctx: AssistContext) -> str:
    """AI 없이 만드는 설명(결정적). AI 응답이 검사에 걸렸을 때도 쓴다."""
    if ctx.intent == "off_topic":
        return OFF_TOPIC_TEXT
    parts: list[str] = []
    if ctx.best_faq:  # 사용자 질문과 가장 가까운 FAQ 답을 먼저
        parts.append(ctx.best_faq.get("a", ""))
    elif ctx.intent == "term" or (ctx.intent == "why" and not ctx.rules):
        parts += [f"{t.term}: {t.plain}" for t in ctx.terms[:2]]
    if ctx.intent == "why" and not ctx.best_faq:
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
    if ctx.intent == "term" and not parts:
        for g in ctx.guide[:1]:
            if g.get("what"):
                parts.append(g["what"])
    for tp in ctx.topics[:1] if not ctx.best_faq else []:
        if tp.get("plain"):
            parts.append(tp["plain"])
    if ctx.web_used:
        parts.append("준비된 설명이 없어 공공기관 웹 검색 결과를 붙였어요. 공식 자료로 확인하세요.")
    if not parts:
        parts.append("이 질문의 근거 자료를 찾지 못했어요. 관할 기관에 확인할 수 있어요.")
    if ctx.review == "UNVERIFIED":
        parts.append("검토 전 규칙이라 참고용이에요.")
    return " ".join(parts)


def to_view(ctx: AssistContext, text: str) -> AssistView:
    return AssistView(
        intent=ctx.intent, text=text, sources=ctx.sources, terms=ctx.terms, review=ctx.review
    )
