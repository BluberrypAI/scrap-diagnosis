"""결정적 응답 문구. LLM이 꺼져 있거나 응답 검증에 실패했을 때 쓴다(턴은 절대 실패하지 않는다)."""

from __future__ import annotations

# 결론이 나지 않은 경우(UNSUPPORTED). 확정할 수 없다.
FAILURE_TEXT = {
    "NO_TABLE": "이 소재·폐기물은 아직 판정 규칙이 없어 분류번호를 정할 수 없습니다.",
    "AMBIGUOUS_TABLE": "입력하신 내용으로는 적용할 판정 기준이 둘 이상이라 정할 수 없습니다.",
    "RULE_TIE": "규칙끼리 결론이 엇갈려 자동으로 정할 수 없습니다. 담당자 검토가 필요합니다.",
    "QUESTION_LIMIT": "질문을 충분히 드렸지만 아직 정할 수 없습니다. 확인된 내용으로 검토를 요청해 주세요.",
    "UNDETERMINABLE": "지금 자료로는 분류번호를 정할 수 없습니다. 확인이 필요한 항목을 정리해 드립니다.",
    "NO_PATH": "더 진행할 수 있는 질문이 없습니다. 담당자 검토가 필요합니다.",
}

# 규칙 엔진이 분류번호 없이 낸 결론(FINAL_REVIEW, result_type NO_CODE). 확정할 수 있다.
OUTCOME_TEXT = {
    "NOT_WASTE": "말씀하신 내용대로라면 아직 사업에 쓰는 물질이라 폐기물관리법상 폐기물이 아닙니다.",
    "CIRCULAR_RESOURCE": "순환자원으로 인정받은 물질이라 폐기물로 보지 않습니다.",
    "EXCLUDED": "이 물질은 폐기물관리법이 아니라 다른 법의 적용을 받습니다.",
    "HOUSEHOLD": "사업장폐기물에 해당하는 조건이 없어 생활폐기물로 보입니다.",
    "INTERPRETATION_NEEDED": "법령만으로 정하기 어려운 경우라 관할 기관의 해석이 필요합니다.",
    "NO_GENERAL_CODE": "지정폐기물은 아니지만, 일반폐기물 세부 분류번호는 담당자 확인이 필요합니다.",
    "CODE_NEEDS_TEST": "분류번호를 정하려면 성분 분석(시험)이 더 필요합니다.",
    "NO_MIXTURE_RULE": "여러 소재가 섞여 나누기 어려운 폐기물이라 분류번호 기준이 없습니다. "
    "소재별로 나눠 확인해야 합니다.",
}
NO_CODE_NEXT_STEP = "확정하시면 다음 단계에서 어떻게 처리하면 되는지 안내해 드립니다."
WASTE_CODE_NEXT_STEP = "확정하면 경로 추천으로 넘어갑니다."

# ---- 화면용 짧은 라벨 (docs/ui/ui-contract.md) ---------------------------------------------

# 코드 없는 결론의 짧은 이름(건 목록 카드 result_label 등)
OUTCOME_LABEL = {
    "NOT_WASTE": "폐기물 아님",
    "CIRCULAR_RESOURCE": "순환자원",
    "EXCLUDED": "다른 법 적용(적용 제외)",
    "HOUSEHOLD": "생활폐기물",
    "INTERPRETATION_NEEDED": "관할 기관 해석 필요",
    "NO_GENERAL_CODE": "일반폐기물 세부 번호 확인 필요",
    "CODE_NEEDS_TEST": "시험 필요",
    "NO_MIXTURE_RULE": "혼합물(소재별 확인 필요)",
}

CATEGORY_LABEL = {"DESIGNATED": "지정폐기물", "GENERAL": "사업장일반폐기물"}

# 사실 출처 배지
SOURCE_LABEL = {
    "UTTERANCE": "말함",
    "DOCUMENT": "서류",
    "PROFILE": "기업 정보",
    "PROFILE_CONFIRMED": "기업 정보(확인됨)",
    "SCREENING": "묶음 답",
    "DERIVED": "자동",
    "SIMULATION": "시험",
}

# 건 상태 배지
STATUS_LABEL = {
    "DIAGNOSING": "문진 중",
    "NEEDS_INFO": "추가 정보 필요",
    "CODE_CONFIRMED": "확정",
    "IN_TRANSIT": "운반 중",
    "COMPLETED": "완료",
}

# 건 목록 카드의 '다음 할 일'. 확정 전에는 마지막 턴의 분기, 확정 뒤에는 인계 행동으로 정한다.
NEXT_ACTION_BY_BRANCH = {
    "ASK_FACT": "질문에 답하기",
    "RESOLVE_CONFLICT": "다른 값 확인하기",
    "FINAL_REVIEW": "판정 확인 후 확정",
    "REQUEST_EVIDENCE": "서류 올리기",
    "UNSUPPORTED": "추가 정보 확인",
}
NEXT_ACTION_BY_ROUTE = {
    "RECOMMEND_ROUTE": "경로 추천 대기",
    "NO_ROUTE_NEEDED": "처리 경로 필요 없음",
    "REFER_OTHER_LAW": "다른 법 담당 기관 안내",
    "REFER_MUNICIPALITY": "지자체 배출 방법 안내",
    "REFER_AUTHORITY": "관할 기관 질의 안내",
    "NEEDS_TEST": "시험 후 문진 재개",
    "MANUAL_CLASSIFICATION": "담당자 분류 확인",
}
NEXT_ACTION_BY_STATUS = {"IN_TRANSIT": "운반 중", "COMPLETED": "완료"}
NEW_CASE_TITLE = "새 폐기물"

# 판정 보드·충돌 카드 문구
RETRACT_REPLY_LABEL = "{label}: 모름으로 되돌리기"
CONFLICT_ACCEPT_DOCUMENT = "서류 값({value})이 맞아요"
CONFLICT_UPLOAD_NEW = "서류가 잘못됐어요(새 서류 올리기)"
CONFLICT_EDIT_FACT = "{label} 다시 답하기"
DOCUMENT_MESSAGE = "서류를 올렸어요: {filename}"


def code_conclusion(code: str, name: str | None) -> str:
    """분류번호가 있는 결론 문장(결과 카드)."""
    return f"분류번호 {code} {name or ''}".strip() + "로 판정됩니다"


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
    note = (
        " 이 판정은 검토 전 규칙(UNVERIFIED)에 따른 것이라 참고용입니다."
        if payload.get("unverified")
        else ""
    )
    if v.get("code") is None:  # 코드 없는 결론
        conclusion = v.get("conclusion") or OUTCOME_TEXT.get(v.get("outcome") or "", "")
        return f"{conclusion} 내용이 맞으면 확정해 주세요. {payload.get('next_step', '')}{note}"
    cat = {"DESIGNATED": "지정폐기물", "GENERAL": "사업장일반폐기물"}.get(v.get("category"), "")
    head = f"분류번호는 {v['code']} {v.get('name') or ''}".strip()
    tail = f" ({cat})" if cat else ""
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
