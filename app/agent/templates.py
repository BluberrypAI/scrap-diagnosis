"""결정적 응답 문구. LLM이 꺼져 있거나 응답 검증에 실패했을 때 쓴다(턴은 절대 실패하지 않는다)."""

from __future__ import annotations

from app.domain.josa import attach

# 결론이 나지 않은 경우(UNSUPPORTED). 확정할 수 없다.
FAILURE_TEXT = {
    "NO_TABLE": "이 소재·폐기물은 아직 판정 규칙이 없어 분류번호를 정할 수 없습니다.",
    "AMBIGUOUS_TABLE": "입력하신 내용으로는 적용할 판정 기준이 둘 이상이라 정할 수 없습니다.",
    "RULE_TIE": "규칙끼리 결론이 엇갈려 자동으로 정할 수 없습니다. 담당자 검토가 필요합니다.",
    "QUESTION_LIMIT": "질문을 충분히 드렸지만 아직 정할 수 없습니다. 확인된 내용으로 검토를 요청해 주세요.",
    "UNDETERMINABLE": "지금 자료로는 분류번호를 정할 수 없습니다.",
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
    "DESIGNATED_CODE_NEEDED": "지정폐기물입니다. 세부 분류번호는 확인이 필요해요.",
}
NO_CODE_NEXT_STEP = "확정하시면 다음 단계에서 어떻게 처리하면 되는지 안내해 드립니다."


def no_code_next_step(action: str | None) -> str:
    """코드 없는 결론의 다음 단계. 확정 전에도 확정하면 무엇으로 이어지는지 보여 준다.

    경로추천 안내의 행동(route_guidance.action) 이름을 쓴다. 안내 요지(summary)는 경로추천 AI용
    문장이라 결론 문장과 겹치므로 여기서는 쓰지 않는다.
    """
    label = NEXT_ACTION_BY_ROUTE.get(action or "")
    if not label:
        return NO_CODE_NEXT_STEP
    return f"확정하면 다음 단계에서 {attach(f"'{label}'", '로')} 이어집니다."


def outcome_reason(name: str | None) -> str | None:
    """코드 없는 결론의 이유 한 줄. 규칙의 설명(then.name)을 쓴다.

    S0·S1 규칙은 설명 문장이고, 지정폐기물 해석 규칙은 짧은 항목 이름이다.
    """
    name = (name or "").strip()
    if not name:
        return None
    if name.endswith(("다.", "다", "요.", "요")):
        return name if name.endswith(".") else f"{name}."
    return f"판단 근거가 된 경우: {name}."


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
    "DESIGNATED_CODE_NEEDED": "지정폐기물(세부 번호 확인 필요)",
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


UNVERIFIED_NOTE = "전문가 검토 전 기준으로 낸 참고용 결과입니다."


def code_conclusion(code: str, name: str | None, category: str | None = None) -> str:
    """분류번호가 있는 결론 문장(결과 카드).

    법령 명칭은 괄호·'제외한다' 같은 문구가 들어 있어 조사를 바로 붙이면 문장이 꼬인다.
    번호와 구분을 먼저 말하고 명칭은 따로 둔다.
    """
    cat = CATEGORY_LABEL.get(category or "", "")
    head = f"분류번호는 {code}({cat})입니다." if cat else f"분류번호는 {code}입니다."
    return f"{head} 명칭: {name}" if name else head


EVIDENCE_TEXT = {
    "TEST_REPORT": "시험성적서",
    "MSDS": "물질안전보건자료(MSDS)",
    "EQUIPMENT_NAMEPLATE": "기기 명판 사진 또는 절연유 분석 기록",
    "EMISSION_FACILITY_PERMIT": "배출시설 설치허가증(신고증명서)",
    "CIRCULAR_RESOURCE_CERTIFICATE": "순환자원 인정서",
    "WASTE_DISCHARGE_REPORT": "폐기물 배출자신고서",
    "CONSTRUCTION_CONTRACT": "공사 계약서",
    "FACILITY_NOTIFICATION": "오니 발생시설 확인 자료(배출시설 허가·신고 서류)",
    "DOCUMENT": "관련 서류",
}


def evidence_label(t: str) -> str:
    return EVIDENCE_TEXT.get(t, t)


def _is_question(text: str) -> bool:
    """이미 묻거나 부탁하는 문장인지. 괄호로 끝나도 물음표가 있으면 질문이다."""
    if "?" in text:
        return True
    return text.rstrip(" .").endswith(("요", "까", "니다", "세요"))


def ask_fact(payload: dict) -> str:
    q = payload["question"]
    lead = payload.get("lead")
    parts = [lead] if lead else []
    if q.get("already_answered"):
        done = ", ".join(q["already_answered"])
        rest = ", ".join(q.get("items") or [])
        parts.append(f"{attach(done, '은')} 확인했습니다. 남은 항목({rest})도 해당 없나요?")
        return " ".join(parts).strip()
    text = q["question"].strip()
    if not _is_question(text):
        text = f"{attach(text, '을')} 알려 주세요."
    parts.append(text)
    return " ".join(parts).strip()


LEACH_SUFFIX = " 용출 농도"
TEST_LAB_HINT = "시험성적서가 없으면 폐기물 분석전문기관에 시험을 의뢰하세요."


def summarize_labels(labels: list[str]) -> str:
    """서류에서 확인할 항목 목록을 짧게. 용출 항목이 여럿이면 '용출시험 n종(…)'으로 묶는다."""
    leach = [x[: -len(LEACH_SUFFIX)] for x in labels if x.endswith(LEACH_SUFFIX)]
    rest = [x for x in labels if not x.endswith(LEACH_SUFFIX)]
    out = []
    if len(leach) >= 3:
        out.append(f"용출시험 {len(leach)}종({'·'.join(leach)})")
    else:
        rest = [f"{x}{LEACH_SUFFIX}" for x in leach] + rest
    return ", ".join(out + rest)


def request_evidence(payload: dict) -> str:
    docs = payload["documents"]
    parts = [
        f"{evidence_label(d['evidence_type'])} — {summarize_labels(d['fact_labels'])}" for d in docs
    ]
    msg = f"확정하려면 서류로 확인해야 할 항목이 남았습니다. 올려 주실 서류: {' / '.join(parts)}."
    if any(d["evidence_type"] == "TEST_REPORT" for d in docs):
        msg += f" {TEST_LAB_HINT}"
    return msg


def final_review(payload: dict) -> str:
    v = payload["verdict"]
    note = f" {UNVERIFIED_NOTE}" if payload.get("unverified") else ""
    if v.get("code") is None:  # 코드 없는 결론: 결론 → 이유 → 확정하면 받을 안내
        conclusion = v.get("conclusion") or OUTCOME_TEXT.get(v.get("outcome") or "", "")
        reason = f" {v['reason']}" if v.get("reason") else ""
        nxt = payload.get("next_step") or NO_CODE_NEXT_STEP
        return f"{conclusion}{reason} 답한 내용이 맞으면 확정해 주세요. {nxt}{note}"
    head = code_conclusion(v["code"], v.get("name"), v.get("category"))
    if v.get("name"):
        head += "."
    return f"{head} 답한 내용이 맞으면 확정해 주세요.{note}"


def resolve_conflict(payload: dict) -> str:
    msgs = [c["message"] for c in payload["conflicts"]]
    return " ".join(msgs) + " 어느 쪽이 맞는지 알려 주세요."


MAX_LISTED = 3


def unsupported(payload: dict) -> str:
    """판정 불가. 무엇이 부족한지와 어떻게 하면 이어지는지까지 말한다(막다른 길을 만들지 않는다)."""
    reason = payload.get("failure_reason") or "NO_PATH"
    parts = [FAILURE_TEXT.get(reason, FAILURE_TEXT["NO_PATH"])]
    items = payload.get("open_items") or []
    if items:
        shown = ", ".join(items[:MAX_LISTED])
        more = f" 외 {len(items) - MAX_LISTED}개" if len(items) > MAX_LISTED else ""
        parts.append(f"아직 확인되지 않은 항목: {shown}{more}.")
    docs = payload.get("evidence_labels") or []
    if docs:
        parts.append(f"{attach(', '.join(docs), '을')} 준비해 올리면 이어서 판정합니다.")
        if payload.get("needs_test_report"):
            parts.append(TEST_LAB_HINT)
    if payload.get("unknown_items"):
        hint = payload.get("unknown_hint")
        first = payload["unknown_items"][0]
        parts.append("'모름'으로 답한 항목은 판정 보드에서 고치면 이어서 진행합니다.")
        if hint:
            parts.append(f"{first} 확인 방법: {hint}")
    return " ".join(parts)


def answer_prefix(payload: dict) -> str:
    help_text = payload.get("help")
    if help_text:
        return f"말씀하신 질문에 대해: {help_text.splitlines()[0]}"
    return "질문하신 내용은 준비된 자료에서 답을 찾지 못했어요. 관할 기관이나 전문가에게 확인해 주세요."


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
