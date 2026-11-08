"""결정적 응답 문구. LLM이 꺼져 있거나 응답 검증에 실패했을 때 쓴다(턴은 절대 실패하지 않는다)."""

from __future__ import annotations

FAILURE_TEXT = {
    "NO_TABLE": "이 소재·폐기물은 아직 판정 규칙이 없어 분류번호를 정할 수 없습니다.",
    "AMBIGUOUS_TABLE": "입력하신 내용으로는 적용할 판정 기준이 둘 이상이라 정할 수 없습니다.",
    "RULE_TIE": "규칙끼리 결론이 엇갈려 자동으로 정할 수 없습니다. 담당자 검토가 필요합니다.",
    "QUESTION_LIMIT": "질문을 충분히 드렸지만 아직 정할 수 없습니다. 확인된 내용으로 검토를 요청해 주세요.",
    "UNDETERMINABLE": "지금 자료로는 분류번호를 정할 수 없습니다. 확인이 필요한 항목을 정리해 드립니다.",
    "NOT_WASTE": "말씀하신 내용대로라면 아직 사업에 쓰는 물질이라 폐기물관리법상 폐기물이 아닙니다.",
    "CIRCULAR_RESOURCE": "순환자원으로 인정받은 물질은 폐기물로 보지 않습니다.",
    "EXCLUDED": "이 물질은 폐기물관리법이 아니라 다른 법의 적용을 받습니다.",
    "HOUSEHOLD": "사업장폐기물에 해당하는 조건이 없어 생활폐기물로 보입니다. 이 서비스의 범위 밖입니다.",
    "INTERPRETATION_NEEDED": "법령만으로 정하기 어려운 경우라 관할 기관의 해석이 필요합니다.",
    "NO_GENERAL_CODE": "지정폐기물은 아니지만, 일반폐기물 분류번호를 정하는 기준이 아직 없습니다.",
    "CODE_NEEDS_TEST": "분류번호를 정하려면 성분 분석이 더 필요합니다.",
    "NO_MIXTURE_RULE": "여러 소재가 섞여 나누기 어려운 폐기물은 분류번호 기준을 확인하지 못했습니다.",
    "NO_PATH": "더 진행할 수 있는 질문이 없습니다. 담당자 검토가 필요합니다.",
}

EVIDENCE_TEXT = {
    "TEST_REPORT": "시험성적서",
    "MSDS": "물질안전보건자료(MSDS)",
    "EQUIPMENT_NAMEPLATE": "기기 명판 사진 또는 절연유 분석 기록",
    "EMISSION_FACILITY_PERMIT": "배출시설 설치허가증(신고증명서)",
    "CIRCULAR_RESOURCE_CERTIFICATE": "순환자원 인정서",
    "WASTE_DISCHARGE_REPORT": "폐기물 배출자신고서",
    "CONSTRUCTION_CONTRACT": "공사 계약서",
    "FACILITY_NOTIFICATION": "시설 설치 신고서",
    "DOCUMENT": "관련 서류",
}


def evidence_label(t: str) -> str:
    return EVIDENCE_TEXT.get(t, t)


def ask_fact(payload: dict) -> str:
    q = payload["question"]
    lead = payload.get("lead")
    parts = [lead] if lead else []
    if q.get("already_answered"):
        done = ", ".join(q["already_answered"])
        rest = ", ".join(q.get("items") or [])
        parts.append(f"{done}은(는) 확인했습니다. 남은 항목({rest})도 해당 없나요?")
        return " ".join(parts).strip()
    text = q["question"].strip()
    if not text.endswith(("?", "요", "요.")):
        text = f"{text}을(를) 알려 주세요."
    parts.append(text)
    return " ".join(parts).strip()


def request_evidence(payload: dict) -> str:
    docs = payload["documents"]
    names = ", ".join(evidence_label(d["evidence_type"]) for d in docs)
    facts = ", ".join(f for d in docs for f in d["fact_labels"])
    return f"확정하려면 서류 확인이 필요합니다. {names}를 올려 주세요. (확인할 항목: {facts})"


def final_review(payload: dict) -> str:
    v = payload["verdict"]
    cat = {"DESIGNATED": "지정폐기물", "GENERAL": "사업장일반폐기물"}.get(v.get("category"), "")
    head = f"분류번호는 {v['code']} {v.get('name') or ''}".strip()
    tail = f" ({cat})" if cat else ""
    note = (
        " 이 판정은 검토 전 규칙(UNVERIFIED)에 따른 것이라 참고용입니다."
        if payload.get("unverified")
        else ""
    )
    return f"{head}{tail}로 판정됩니다. 내용이 맞으면 확정해 주세요.{note}"


def resolve_conflict(payload: dict) -> str:
    msgs = [c["message"] for c in payload["conflicts"]]
    return " ".join(msgs) + " 어느 쪽이 맞는지 알려 주세요."


def unsupported(payload: dict) -> str:
    reason = payload.get("failure_reason") or "NO_PATH"
    return FAILURE_TEXT.get(reason, FAILURE_TEXT["NO_PATH"])


def answer_prefix(payload: dict) -> str:
    help_text = payload.get("help")
    if help_text:
        return f"말씀하신 질문에 대해: {help_text.splitlines()[0]}"
    return "질문하신 내용은 판정 근거 자료를 확인한 뒤 안내해 드리겠습니다."


def render(branch: str, payload: dict) -> str:
    body = {
        "ASK_FACT": ask_fact,
        "REQUEST_EVIDENCE": request_evidence,
        "FINAL_REVIEW": final_review,
        "RESOLVE_CONFLICT": resolve_conflict,
        "UNSUPPORTED": unsupported,
    }[branch](payload)
    if payload.get("user_question"):
        return f"{answer_prefix(payload)} {body}"
    return body
