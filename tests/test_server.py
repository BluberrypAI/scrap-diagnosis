from wastecalc import server


def test_session_flow_and_text_plus_json():
    r = server.start_assessment({"no_longer_needed": True, "direct_reinput": False,
                                 "circular_resource_recognized": False, "law_exclusion": "none"}, strict=False)
    assert not r.isError
    sid = r.structuredContent["session_id"]
    assert r.structuredContent["stage"] == "S2"
    assert "사업장폐기물" in r.content[0].text

    r2 = server.answer_question(sid, "emission_facility", True)
    assert r2.structuredContent["decided"][-1]["conclusion"] == "BUSINESS"


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
