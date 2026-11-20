"""골든셋 98건을 HTTP API로 끝까지 문진한다(가상 사용자는 골든 사실을 안다).

엔진 단독(tools/simulate_interview.py)과 같은 결론이 나와야 한다.
묶음 질문은 화면처럼 '모두 해당 없음' 또는 '펼치기 → 항목별 답'으로,
캔 순환자원 묶음은 '모두 마침' 또는 '아니요'로 답한다.
"""

import json
import sys
from pathlib import Path

from conftest import headers

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from simulate_interview import golden, truth  # noqa: E402

from app.engine.flow import norm  # noqa: E402


def evidence_turn(client, cid, turn, facts, h):
    """서류 요청: 골든 사실에 값이 있으면 서류를 올려 검수·적용하고, 없으면 '서류가 없어요'."""
    keys = [k for d in turn["ui"]["requested_documents"] for k in d["facts"]]
    values = {k: truth(facts, k) for k in keys if truth(facts, k) is not None}
    base = f"/internal/v1/cases/{cid}"
    if not values:
        res = client.post(f"{base}/diagnosis/messages", json={"text": "서류가 없어요"}, headers=h)
        assert res.status_code == 200, res.text
        return res.json()
    up = client.post(
        f"{base}/documents",
        files={"file": ("values.txt", b"manual", "text/plain")},
        data={"facts": json.dumps(values)},
        headers=h,
    )
    assert up.status_code == 201, up.text
    doc = up.json()["document"]
    body = {
        "values": [
            {"value_id": v["id"], "document_version": doc["version"], "reviewer": "golden"}
            for v in up.json()["values"]
        ]
    }
    res = client.post(f"{base}/documents/{doc['id']}/values/apply", json=body, headers=h)
    assert res.status_code == 200, res.text
    return res.json()


def answer_turn(client, cid, turn, facts, h):
    if turn["branch"] == "REQUEST_EVIDENCE":
        return evidence_turn(client, cid, turn, facts, h)
    q = turn["ui"]["question"]
    url = f"/internal/v1/cases/{cid}/diagnosis/messages"

    def send(qr):
        res = client.post(url, json={"quick_reply": qr}, headers=h)
        assert res.status_code == 200, res.text
        return res.json()

    if q["unit"] == "group":
        none_all = next(o for o in q["options"] if o["kind"] == "none_all")
        values = {f: norm(truth(facts, f)) for f in q["facts"]}
        if all(values[f] == v for f, v in none_all["value"].items()):
            return send({"key": q["key"], "kind": "none_all"})
        return send({"key": q["key"], "kind": "expand"})
    value = norm(truth(facts, q["key"]))
    if value is None or value == "unknown":
        return send({"key": q["key"], "kind": "unknown"})
    return send({"key": q["key"], "kind": "value", "value": value})


def test_golden_cases_through_api(client):
    failures = []
    for i, (gid, facts, expected) in enumerate(golden()):
        h = headers(f"golden-{i}")  # 건마다 새 기업(회사 기억 없음)
        res = client.post("/internal/v1/cases", json={}, headers=h)
        cid, turn = res.json()["case"]["id"], res.json()["turn"]
        # 묻지 않는 기본값(가정)이 실제와 다르면 판정 보드에서 고친다
        for a in client.app.state.kb.plan.assume:
            for k, v in a["set"].items():
                t = norm(truth(facts, k))
                if t is not None and str(t) != str(v):
                    turn = client.post(
                        f"/internal/v1/cases/{cid}/diagnosis/messages",
                        json={"quick_reply": {"key": k, "kind": "value", "value": t}},
                        headers=h,
                    ).json()
        for _ in range(40):
            if turn["branch"] not in ("ASK_FACT", "REQUEST_EVIDENCE"):
                break
            turn = answer_turn(client, cid, turn, facts, h)
        v = turn["verdict"]
        if turn["branch"] == "UNSUPPORTED":
            got = ("INSUFFICIENT_INFO", None, ())
        else:
            trace = client.get(f"/internal/v1/cases/{cid}/trace", headers=h).json()
            last = trace["events"][-1]["result"]
            got = (v["outcome"], last["code"], tuple(sorted(v["flags"])))
        if got != expected:
            failures.append((gid, expected, got))
    assert not failures, failures
