"""내부 API(/internal/v1) 테스트: 실제 knowledge/flow 규칙과 SQLite DB를 쓴다."""

from conftest import headers, make_client

H = headers()
PP_SCRAP = [
    ("material", "pp"),
    ("input_form", "scrap"),
    ("discharged", "yes"),
    ("Q-PLASTIC-KIND", "none_all"),
    ("packaging_used", "no"),
    ("Q-CONTAMINATION", "none_all"),
    ("law_exclusion", "none"),
    ("circular_recognized", "no"),
    ("emission_facility", "yes"),
]


# 남은 질문에 답할 때의 기본 답(대부분 '예', 아래 사실은 흔한 답)
DEFAULT = {"law_exclusion": "none", "circular_recognized": "no"}


def typical(q):
    """질문 카드에 대한 흔한 답: 묶음은 '모두 해당 없음', 단일은 DEFAULT 또는 '예'."""
    return "none_all" if q["unit"] == "group" else DEFAULT.get(q["key"], "yes")


def reply(client, case_id, key, value=None, kind=None, h=H):
    if kind is None:
        kind = value if value in ("none_all", "expand", "unknown", "retract") else "value"
    qr = {"key": key, "kind": kind}
    if kind == "value":
        qr["value"] = value
    return client.post(
        f"/internal/v1/cases/{case_id}/diagnosis/messages", json={"quick_reply": qr}, headers=h
    )


def new_case(client, h=H, **body):
    res = client.post("/internal/v1/cases", json=body, headers=h)
    assert res.status_code == 201, res.text
    return res.json()


def run_answers(client, case_id, answers, h=H):
    turn = None
    for key, value in answers:
        res = reply(client, case_id, key, value, h=h)
        assert res.status_code == 200, res.text
        turn = res.json()
    return turn


def test_first_question_is_material(client):
    d = new_case(client, memo="PP 사출 자투리")
    q = d["turn"]["ui"]["question"]
    assert d["turn"]["branch"] == "ASK_FACT"
    assert q["key"] == "material" and q["input"] == "choice"
    assert {"pp", "pe", "pet", "aluminium"} <= {o["value"] for o in q["options"]}
    assert d["case"]["status"] == "DIAGNOSING"
    assert d["case"]["summary"]["title"] == "PP 사출 자투리"


def test_form_options_follow_material(client):
    cid = new_case(client)["case"]["id"]
    turn = reply(client, cid, "material", "pet").json()
    q = turn["ui"]["question"]
    assert q["key"] == "input_form"
    assert [o["value"] for o in q["options"] if o["kind"] == "value"] == [
        "flake",
        "bottle",
        "bale",
        "other",
    ]


def test_pp_scrap_to_confirmed_handoff(client):
    cid = new_case(client)["case"]["id"]
    turn = run_answers(client, cid, PP_SCRAP)
    assert turn["branch"] == "FINAL_REVIEW"
    assert turn["ui"]["can_confirm"] is True
    assert turn["ui"]["result"]["code"] == "51-03-01"
    res = client.post(
        f"/internal/v1/cases/{cid}/confirm", json={"expected_code": "51-03-01"}, headers=H
    )
    assert res.status_code == 200, res.text
    h = res.json()["handoff"]
    # 서버(scrap-server treatment.py)가 읽는 필드
    assert h["contract"] == "diagnosis-handoff-v1" and h["case_id"] == cid
    assert (h["result_type"], h["category"], h["waste_code"]) == (
        "WASTE_CODE",
        "GENERAL",
        "51-03-01",
    )
    assert h["route_guidance"]["action"] == "RECOMMEND_ROUTE"
    assert h["facts"]["material"]["value"] == "pp"
    assert h["facts"]["input_form"] == {
        "value": "scrap",
        "status": "CLAIMED",
        "source_type": "UTTERANCE",
    }
    assert h["facts"]["physical_state"]["value"] == "solid"
    assert h["timestamps"]["as_of"] and h["basis"]
    detail = client.get(f"/internal/v1/cases/{cid}", headers=H).json()
    assert detail["case"]["status"] == "CODE_CONFIRMED"
    assert detail["handoff"] == h
    assert detail["case"]["summary"]["next_action"] == "경로 추천 대기"


def test_company_facts_remembered_for_next_case(client):
    first = new_case(client)["case"]["id"]
    run_answers(client, first, PP_SCRAP)
    second = new_case(client)["case"]["id"]
    turn = run_answers(client, second, PP_SCRAP[:-1])  # 사업장 질문 없이 끝나야 한다
    assert turn["branch"] == "FINAL_REVIEW"
    sources = {f["key"]: f["source_type"] for f in turn["ui"]["board"]["facts"]}
    assert sources["emission_facility"] == "PROFILE"
    # 다른 기업에는 기억이 넘어가지 않는다
    other = new_case(client, h=headers("co-2"))["case"]["id"]
    turn = run_answers(client, other, PP_SCRAP[:-1], h=headers("co-2"))
    assert turn["ui"]["question"]["key"] == "emission_facility"


def test_edit_and_retract_do_not_change_company_facts(client):
    first = new_case(client)["case"]["id"]
    run_answers(client, first, PP_SCRAP)  # 첫 답 emission_facility=yes를 기억
    # 같은 건에서 고치기·되돌리기를 해도 회사 기억은 그대로다
    assert reply(client, first, "emission_facility", "no").status_code == 200
    assert reply(client, first, "emission_facility", "retract").status_code == 200
    second = new_case(client)["case"]["id"]
    turn = run_answers(client, second, PP_SCRAP[:-1])
    facts = {f["key"]: f for f in turn["ui"]["board"]["facts"]}
    assert facts["emission_facility"]["source_type"] == "PROFILE"
    assert facts["emission_facility"]["value"] == "yes"
    # 기억에서 채운 값을 이 건에서 고쳐도 다음 건에는 기억한 값이 들어간다
    assert reply(client, second, "emission_facility", "no").status_code == 200
    third = new_case(client)["case"]["id"]
    turn = run_answers(client, third, PP_SCRAP[:-1])
    facts = {f["key"]: f for f in turn["ui"]["board"]["facts"]}
    assert facts["emission_facility"]["value"] == "yes"


def test_unknown_blocks_and_cannot_confirm(client):
    cid = new_case(client)["case"]["id"]
    answers = PP_SCRAP[:3] + [("packaging_used", "unknown")]
    turn = run_answers(client, cid, answers)
    while turn["branch"] == "ASK_FACT":
        q = turn["ui"]["question"]
        turn = reply(client, cid, q["key"], typical(q)).json()
    assert turn["branch"] == "UNSUPPORTED"
    assert [p["key"] for p in turn["ui"]["board"]["pending"]] == ["packaging_used"]
    res = client.post(f"/internal/v1/cases/{cid}/confirm", headers=H)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "NOT_CONFIRMABLE"
    assert (
        client.get(f"/internal/v1/cases/{cid}", headers=H).json()["case"]["status"] == "NEEDS_INFO"
    )
    # 보드에서 답을 고치면 이어서 진행한다
    turn = reply(client, cid, "packaging_used", "no").json()
    assert turn["branch"] == "FINAL_REVIEW"


def test_group_expand_asks_items_one_by_one(client):
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, PP_SCRAP[:5])
    turn = reply(client, cid, "Q-CONTAMINATION", "expand").json()
    q = turn["ui"]["question"]
    assert (q["key"], q["unit"], q["group"]) == ("oil_presence", "fact", "Q-CONTAMINATION")
    turn = reply(client, cid, "oil_presence", "none").json()
    assert turn["ui"]["question"]["key"] == "residue"
    assert turn["ui"]["question"]["answered_items"][0]["key"] == "oil_presence"


def test_oil_without_document_is_designated_possible(client):
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, PP_SCRAP[:5])
    reply(client, cid, "Q-CONTAMINATION", "expand")
    reply(client, cid, "oil_presence", "present")
    reply(client, cid, "residue", "none")
    reply(client, cid, "chemical_itself", "no")
    turn = reply(client, cid, "oil_pct_evidenced", "unknown").json()
    turn = (
        run_answers(client, cid, [("law_exclusion", "none"), ("circular_recognized", "no")])
        if turn["branch"] == "ASK_FACT"
        else turn
    )
    assert turn["branch"] == "FINAL_REVIEW"
    r = turn["ui"]["result"]
    assert (r["outcome"], r["code"], r["category"]) == (
        "DESIGNATED_POSSIBLE",
        None,
        "DESIGNATED_POSSIBLE",
    )
    assert "성적서" in r["reason"]
    h = client.post(f"/internal/v1/cases/{cid}/confirm", headers=H).json()["handoff"]
    assert h["route_guidance"]["action"] == "NEEDS_TEST" and h["waste_code"] is None


def test_out_of_scope_hides_candidate_code(client):
    cid = new_case(client)["case"]["id"]
    turn = run_answers(client, cid, [("material", "aluminium"), ("input_form", "scrap")])
    while turn["branch"] == "ASK_FACT":
        q = turn["ui"]["question"]
        turn = reply(client, cid, q["key"], typical(q)).json()
    r = turn["ui"]["result"]
    assert (r["outcome"], r["code"]) == ("OUT_OF_SCOPE", None)
    assert "지원 예정" in r["conclusion"]


def test_can_circular_not_all_done_is_one_click(client):
    cid = new_case(client)["case"]["id"]
    turn = run_answers(client, cid, [("material", "aluminium"), ("input_form", "can")])
    seen = []
    while turn["branch"] == "ASK_FACT":
        q = turn["ui"]["question"]
        seen.append(q["key"])
        if q["key"] == "can_contents":
            turn = reply(client, cid, "can_contents", "food_beverage").json()
        elif q["key"] == "Q-CAN-CIRCULAR":
            assert q["options"][1]["kind"] == "expand"
            turn = reply(client, cid, "Q-CAN-CIRCULAR", "expand").json()
        else:
            turn = reply(client, cid, q["key"], typical(q)).json()
    assert seen.count("Q-CAN-CIRCULAR") == 1
    assert turn["ui"]["result"]["code"] == "51-29-03"
    # '아니요'가 실수였다면 보드에서 한 항목을 고칠 때 묶음을 다시 묻는다(나머지 모름이 남지 않음)
    turn = reply(client, cid, "can_designation.registered", "yes").json()
    q = turn["ui"]["question"]
    assert q["key"] == "Q-CAN-CIRCULAR"
    assert "can_designation.registered" not in q["facts"]
    turn = reply(client, cid, "Q-CAN-CIRCULAR", "none_all").json()
    while turn["branch"] == "ASK_FACT":
        q = turn["ui"]["question"]
        turn = reply(client, cid, q["key"], typical(q)).json()
    assert turn["ui"]["result"]["outcome"] == "CIRCULAR_RESOURCE"


def test_board_edit_offers_unknown(client):
    cid = new_case(client)["case"]["id"]
    turn = run_answers(client, cid, PP_SCRAP[:3])
    facts = {f["key"]: f for f in turn["ui"]["board"]["facts"]}
    kinds = [o["kind"] for o in facts["discharged"]["edit"]["options"]]
    assert kinds[-1] == "unknown" and kinds.count("unknown") == 1
    # 고치기에서 '모름'을 고르면 모름으로 기록된다(되돌리기 없이)
    turn = reply(client, cid, "discharged", "unknown").json()
    facts = {f["key"]: f for f in turn["ui"]["board"]["facts"]}
    assert facts["discharged"]["status"] == "DECLARED_UNKNOWN"


def test_retract_returns_fact_to_unasked(client):
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, [("material", "pp")])
    turn = reply(client, cid, "material", kind="retract").json()
    assert turn["ui"]["question"]["key"] == "material"


def test_text_message_is_logged_and_question_repeats(client):
    cid = new_case(client)["case"]["id"]
    res = client.post(
        f"/internal/v1/cases/{cid}/diagnosis/messages", json={"text": "PP예요"}, headers=H
    )
    assert res.status_code == 200
    assert res.json()["ui"]["question"]["key"] == "material"
    conv = client.get(f"/internal/v1/cases/{cid}", headers=H).json()["conversation"]
    assert [m["role"] for m in conv] == ["assistant", "user", "assistant"]


def test_validation_errors(client):
    cid = new_case(client)["case"]["id"]
    res = reply(client, cid, "material", "wood")
    assert res.status_code == 422
    assert res.json()["detail"]["details"]["problems"][0]["reason"] == "선택지 밖 값"
    res = reply(client, cid, "nope", "x")
    assert res.status_code == 422
    res = client.post(f"/internal/v1/cases/{cid}/diagnosis/messages", json={}, headers=H)
    assert res.status_code == 422


def test_confirmed_case_is_locked_until_reopen(client):
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, PP_SCRAP)
    client.post(f"/internal/v1/cases/{cid}/confirm", headers=H)
    res = reply(client, cid, "material", "pe")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "CASE_NOT_DIAGNOSABLE"
    again = client.post(f"/internal/v1/cases/{cid}/confirm", headers=H)
    assert again.json()["detail"]["code"] == "ALREADY_CONFIRMED"
    res = client.post(f"/internal/v1/cases/{cid}/reopen", json={"reason": "재질 확인"}, headers=H)
    assert res.status_code == 200
    assert res.json()["superseded_verdict"]["version"] == 1
    assert client.get(f"/internal/v1/cases/{cid}", headers=H).json()["handoff"] is None
    res = client.post(f"/internal/v1/cases/{cid}/confirm", headers=H)
    assert res.json()["verdict"]["version"] == 2


def test_code_mismatch(client):
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, PP_SCRAP)
    res = client.post(
        f"/internal/v1/cases/{cid}/confirm", json={"expected_code": "51-03-07"}, headers=H
    )
    assert res.status_code == 409 and res.json()["detail"]["code"] == "CODE_MISMATCH"


def test_auth_and_isolation(tmp_path):
    with make_client(tmp_path) as c:
        res = c.post("/internal/v1/cases", json={}, headers={"X-Company-Id": "co-1"})
        assert res.status_code == 401 and res.json()["detail"]["code"] == "AUTH_REQUIRED"
        res = c.post(
            "/internal/v1/cases", json={}, headers={"Authorization": f"Bearer {'test-token'}"}
        )
        assert res.status_code == 400 and res.json()["detail"]["code"] == "COMPANY_REQUIRED"
        cid = new_case(c)["case"]["id"]
        res = c.get(f"/internal/v1/cases/{cid}", headers=headers("co-2"))
        assert res.status_code == 404 and res.json()["detail"]["code"] == "CASE_NOT_FOUND"


def test_prod_without_token_is_closed(tmp_path):
    with make_client(tmp_path, token="", app_env="prod") as c:
        res = c.post("/internal/v1/cases", json={}, headers={"X-Company-Id": "co-1"})
        assert res.status_code == 401


def test_kb_changed_and_rebase(client):
    cid = new_case(client)["case"]["id"]
    db = client.app.state.db
    with db.sessions() as s:
        from app.persistence.models import Case

        s.get(Case, cid).kb_version = "old"
        s.commit()
    res = reply(client, cid, "material", "pp")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "KB_CHANGED"
    assert client.get(f"/internal/v1/cases/{cid}", headers=H).json()["case"]["kb_changed"] is True
    assert client.post(f"/internal/v1/cases/{cid}/rebase", headers=H).status_code == 200
    assert reply(client, cid, "material", "pp").status_code == 200


def test_list_and_paging(client):
    for _ in range(3):
        new_case(client)
    res = client.get("/internal/v1/cases?page=2&size=2", headers=H).json()
    assert res["pagingInfo"] == {
        "currentPageNumber": 2,
        "pageSize": 2,
        "totalCount": 3,
        "totalPages": 2,
    }
    assert len(res["items"]) == 1


def test_delete_company_data_is_idempotent(client):
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, PP_SCRAP)
    client.post(f"/internal/v1/cases/{cid}/confirm", headers=H)
    auth = {"Authorization": H["Authorization"]}
    first = client.delete("/internal/v1/companies/co-1/data", headers=auth).json()
    assert first["status"] == "DONE" and first["counts"]["cases"] == 1
    assert first["counts"]["company_facts"] == 1
    again = client.delete("/internal/v1/companies/co-1/data", headers=auth).json()
    assert again == first
    assert client.get(f"/internal/v1/cases/{cid}", headers=H).status_code == 404
    log = client.get("/internal/v1/companies/co-1/data/deletion", headers=auth).json()
    assert log["status"] == "DONE"


def test_catalog_and_health(client):
    facts = client.get("/internal/v1/catalog/facts", headers=H).json()
    keys = {f["key"] for f in facts}
    assert {"material", "input_form", "can_designation.registered"} <= keys
    assert client.get("/health").json()["status"] == "ok"


def test_recycling_types_in_handoff(client):
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, PP_SCRAP)
    h = client.post(f"/internal/v1/cases/{cid}/confirm", headers=H).json()["handoff"]
    r = h["recycling"]
    assert (r["contract"], r["status"], r["waste_code"]) == (
        "recycling-types-v1",
        "table_listed",
        "51-03-01",
    )
    assert r["case_id"] == cid and r["verdict_version"] == h["verdict_version"]
    assert r["as_of"] == h["timestamps"]["as_of"]
    assert r["types"]["free"][:2] == ["R-1", "R-2"]
    assert "R-8-1" in r["types"]["analysis"]
    assert r["source"]["url"].startswith("https://www.law.go.kr/")
    assert r["facility_permit_verified"] is False and r["version"] and r["checksum"]
    assert len(r["notes"]) == 4
    assert client.get(f"/internal/v1/cases/{cid}", headers=H).json()["recycling"] == r


def test_recycling_not_applicable_without_route(client):
    cid = new_case(client)["case"]["id"]
    turn = run_answers(client, cid, [("material", "aluminium"), ("input_form", "scrap")])
    while turn["branch"] == "ASK_FACT":
        q = turn["ui"]["question"]
        turn = reply(client, cid, q["key"], typical(q)).json()
    h = client.post(f"/internal/v1/cases/{cid}/confirm", headers=H).json()["handoff"]
    assert h["recycling"]["status"] == "not_applicable"


def test_group_pick_asks_only_picked_items(client):
    cid = new_case(client)["case"]["id"]
    turn = run_answers(client, cid, PP_SCRAP[:5])
    q = turn["ui"]["question"]
    assert q["key"] == "Q-CONTAMINATION" and q["allow_pick"] is True
    res = client.post(
        f"/internal/v1/cases/{cid}/diagnosis/messages",
        json={"quick_reply": {"key": "Q-CONTAMINATION", "kind": "some", "value": ["residue"]}},
        headers=H,
    )
    turn = res.json()
    q = turn["ui"]["question"]
    assert q["key"] == "residue"  # 세부 값이 여럿인 항목만 묻는다
    assert q["text"] == "어떤 내용물이 남아 있나요?"
    assert "none" not in [o["value"] for o in q["options"]]  # '남은 것 없음'은 뺀다
    facts = {f["key"]: f["value"] for f in turn["ui"]["board"]["facts"]}
    assert facts["oil_presence"] == "none" and facts["chemical_itself"] == "no"
    bad = client.post(
        f"/internal/v1/cases/{cid}/diagnosis/messages",
        json={"quick_reply": {"key": "Q-CONTAMINATION", "kind": "some", "value": ["material"]}},
        headers=H,
    )
    assert bad.status_code == 422


def test_group_pick_records_single_value_items_without_asking_again(client):
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, PP_SCRAP[:5])
    res = client.post(
        f"/internal/v1/cases/{cid}/diagnosis/messages",
        json={"quick_reply": {"key": "Q-CONTAMINATION", "kind": "some", "value": ["oil_presence"]}},
        headers=H,
    )
    turn = res.json()
    facts = {f["key"]: f["value"] for f in turn["ui"]["board"]["facts"]}
    assert facts["oil_presence"] == "present"  # 체크한 순간 '있음'으로 기록
    assert turn["branch"] == "REQUEST_EVIDENCE"  # 기름을 다시 묻지 않고 성적서로 넘어간다


def test_question_has_why_and_basis(client):
    turn = new_case(client)["turn"]
    q = turn["ui"]["question"]
    assert q["guide"]["reason"].startswith("재질에 따라")
    assert q["basis"] and all(b["ref"] and b["excerpt"] for b in q["basis"])


def test_law_exclusion_only_asks_radioactive_for_in_scope_solids(client):
    cid = new_case(client)["case"]["id"]
    turn = run_answers(client, cid, PP_SCRAP[:6])
    q = turn["ui"]["question"]
    assert q["key"] == "law_exclusion"
    assert q["text"] == "방사성 물질에 오염됐거나 그럴 가능성이 있나요?"
    assert [(o["value"], o["label"]) for o in q["options"] if o["kind"] == "value"] == [
        ("none", "아니요"),
        ("radioactive", "예"),
    ]


def test_material_change_drops_form_that_does_not_fit(client):
    cid = new_case(client)["case"]["id"]
    run_answers(client, cid, PP_SCRAP)
    turn = reply(client, cid, "material", "pet").json()  # PET에는 '자투리'가 없다
    assert turn["ui"]["question"]["key"] == "input_form"
    assert [o["value"] for o in turn["ui"]["question"]["options"] if o["kind"] == "value"] == [
        "flake",
        "bottle",
        "bale",
        "other",
    ]
    turn = reply(client, cid, "material", "pe").json()  # PE는 형태를 다시 고른 뒤라 유지
    form = next(f for f in turn["ui"]["board"]["facts"] if f["key"] == "material")
    assert form["value"] == "pe"


def test_board_hides_answers_that_no_longer_apply(client):
    cid = new_case(client)["case"]["id"]
    run_answers(
        client,
        cid,
        [("material", "aluminium"), ("input_form", "can"), ("can_contents", "food_beverage")],
    )
    turn = reply(client, cid, "input_form", "scrap").json()
    keys = [f["key"] for f in turn["ui"]["board"]["facts"]]
    assert "can_contents" not in keys
    form = next(f for f in turn["ui"]["board"]["facts"] if f["key"] == "input_form")
    assert [o["value"] for o in form["edit"]["options"]] == ["scrap", "can", "other"]


def test_discharged_is_assumed_and_editable(client):
    turn = new_case(client)["turn"]
    fact = next(f for f in turn["ui"]["board"]["facts"] if f["key"] == "discharged")
    assert (fact["value"], fact["source_type"], fact["editable"]) == ("yes", "ASSUMED", True)
    cid = turn["case_id"]
    turn = run_answers(client, cid, PP_SCRAP[:2] + [("discharged", "no")])
    assert turn["ui"]["result"]["outcome"] == "NOT_WASTE"
