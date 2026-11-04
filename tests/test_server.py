from wastecalc import server


def test_session_flow_and_text_plus_json():
    r = server.start_assessment({"no_longer_needed": True, "direct_reinput": False, "continuous_feedstock": False,
                                 "circular_resource_recognized": False, "law_exclusion": "none"}, strict=False)
    assert not r.isError
    sid = r.structuredContent["session_id"]
    assert r.structuredContent["stage"] == "S2"
    assert r.structuredContent["next_question"]["choices"][-1]["value"] == "UNKNOWN"

    r2 = server.answer_question(sid, "emission_facility", True)
    assert r2.structuredContent["summary"]["S2"] == "사업장폐기물"


def test_compact_is_small_and_explain_is_full():
    import json
    base = {"no_longer_needed": True, "direct_reinput": False, "continuous_feedstock": False, "circular_resource_recognized": False,
            "law_exclusion": "none", "emission_facility": True}
    c = server.evaluate_facts(base)
    full = server.explain(answers=base)
    size = lambda r: len(json.dumps(r.structuredContent, ensure_ascii=False)) + len(r.content[0].text)
    assert size(c) < 6000 < 50000 < size(full)
    assert c.structuredContent["next_question"]["fact"] == "waste_kind"
    assert "근거 원문" in full.content[0].text


def test_batch_answers_in_one_call():
    r = server.start_assessment({"no_longer_needed": True, "direct_reinput": False, "continuous_feedstock": False,
                                 "circular_resource_recognized": False, "law_exclusion": "none",
                                 "emission_facility": True}, strict=False)
    sid = r.structuredContent["session_id"]
    r2 = server.answer_question(sid, answers={"waste_kind": "other", "physical_state": "solid", "oil_presence": "none",
                                              "pcb_possible": False, "toxic_chemical_discard": False, "designated_residue": False})
    assert r2.structuredContent["summary"]["S3"].startswith("지정폐기물 아님")
    assert r2.structuredContent["next_question"]["fact"] == "general_group"


def test_compact_keeps_same_judgment_as_full():
    base = {"no_longer_needed": True, "direct_reinput": False, "continuous_feedstock": False, "circular_resource_recognized": False,
            "law_exclusion": "none", "emission_facility": True, "waste_kind": "acid", "physical_state": "liquid",
            "oil_presence": "none", "pcb_possible": False, "toxic_chemical_discard": False, "designated_residue": False}
    c, f = server.evaluate_facts(base).structuredContent, server.explain(answers=base).structuredContent
    assert c["status"] == f["status"] == "NEED_TEST"
    assert c["summary"] == f["summary"]
    assert c["next_question"]["fact"] == f["next_question"]["fact"] == "ph"
    assert "ES 06304.1" in c["next_question"]["test"]["method"]


def test_invalid_value_is_error_not_guess():
    r = server.start_assessment({"law_exclusion": "sewage"})
    assert r.isError and "허용 값" in r.content[0].text


def test_unknown_session():
    r = server.answer_question("nope", "emission_facility", True)
    assert r.isError


def test_get_rule_returns_quote():
    r = server.get_rule("S2-DAILY-300KG")
    assert "300킬로그램" in r.structuredContent["quote"]


def test_allowed_recycling_types_tool():
    r = server.allowed_recycling_types("51-29-01")
    assert r.structuredContent["listed"] and r.structuredContent["cells"][0]["types"][0]["r_code"] == "R-3-3"
    assert server.allowed_recycling_types("02-01-04").structuredContent["listed"] is False
    assert server.allowed_recycling_types("99-99-99").isError


def test_r_code_definition_tool():
    assert "재사용" in server.r_code_definition("R-1").structuredContent["definition"]
