"""쉬운 설명·이유 문장 검증. 설명은 법적 효력이 없으므로 규칙과 어긋나지 않게 막는다."""
import re

from wastecalc import evaluate, load_kb, render_text

KB = load_kb(as_of="2026-11-05")
BASE = {"no_longer_needed": True, "direct_reinput": False, "circular_resource_recognized": False,
        "law_exclusion": "none"}
GATES_NO = {"oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": False}
NUM = re.compile(r"\d+(?:\.\d+)?")


def ev(a):
    return evaluate(a, strict=False, kb=KB)


def test_every_rule_has_plain_explanation():
    missing = [r.id for r in KB.rules if not r.plain]
    assert not missing, missing


def test_numbers_in_plain_text_come_from_the_rule():
    """쉬운 설명에 나온 숫자는 그 규칙의 조건값이나 근거 원문에 있어야 한다(숫자를 지어내지 않음)."""
    for r in KB.rules:
        allowed = set()
        for c in r.when:
            vals = c.value if isinstance(c.value, list) else [c.value]
            for v in vals:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    allowed |= {f"{v:g}", str(v)}
        allowed |= set(NUM.findall(r.quote))
        for s in r.supporting:
            allowed |= set(NUM.findall(s["quote"]))
        plain = re.sub(r"별표\s*\d+(?:의\d+)?|제\d+(?:조|호|항)(?:의\d+)?", "", r.plain)  # 조항 번호는 기준값이 아님
        for n in NUM.findall(plain):
            assert n in allowed, (r.id, n, r.plain)


def test_because_shows_user_value_against_threshold():
    r = ev({**BASE, "emission_facility": False, "work_type": "none", "daily_avg_kg": 450})
    s2 = next(d for d in r["decided"] if d["stage"] == "S2")
    assert any("450kg/일" in b and "300kg/일 이상" in b for b in s2["explanation"]["because"])


def test_household_lists_why_each_route_failed():
    r = ev({**BASE, "emission_facility": False, "work_type": "none", "daily_avg_kg": 120,
            "designated_waste_emitted": False, "waste_facility": False, "public_facility": "none",
            "waste_kind": "other", "physical_state": "solid", **GATES_NO})
    s2 = next(d for d in r["decided"] if d["stage"] == "S2")
    text = " ".join(s2["explanation"]["because"])
    assert "120kg/일" in text and "배출시설" in text and "해당 없음" in text


def test_not_designated_skips_unrelated_waste_kinds():
    r = ev({**BASE, "emission_facility": True, "waste_kind": "other", "physical_state": "solid", **GATES_NO})
    s3 = next(d for d in r["decided"] if d["stage"] == "S3")
    because = s3["explanation"]["because"]
    assert len(because) == 3  # 기름·PCB·유해화학물질 경로만 (종류가 다른 경로는 무관하므로 생략)
    assert not any("오니" in b for b in because)


def test_every_decided_stage_has_explanation():
    flows = [
        {**BASE, "emission_facility": True, "waste_kind": "acid", "physical_state": "liquid", "ph": 1, **GATES_NO,
         "code": "02-01-01"},
        {**BASE, "emission_facility": True, "waste_kind": "other", "physical_state": "solid", **GATES_NO,
         "general_group": "51-29", "code": "51-29-01"},
        {**BASE, "emission_facility": True, "waste_kind": "asbestos_processing", "physical_state": "solid", **GATES_NO},
        {"circular_resource_recognized": True},
    ]
    for f in flows:
        r = ev(f)
        for d in r["decided"]:
            assert d.get("explanation", {}).get("plain"), (d["stage"], f)


def test_render_has_reason_source_and_glossary_sections():
    r = ev({**BASE, "emission_facility": True, "waste_kind": "other", "physical_state": "solid", **GATES_NO,
            "general_group": "51-29", "code": "51-29-01"})
    text = render_text(r, glossary=KB.glossary)
    assert "왜:" in text and "근거 원문" in text and "용어 풀이" in text
    assert text.index("왜:") < text.index("근거 원문") < text.index("용어 풀이")


def test_resolution_explains_why_each_answer_matters():
    r = ev({**BASE, "emission_facility": True, "waste_kind": "acid", "physical_state": "liquid", **GATES_NO})
    card = r["resolution"][0]
    assert card["fact"] == "ph" and all(d.get("plain") for d in card["decides"])
