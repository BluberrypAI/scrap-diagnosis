"""말 이해 오프라인 평가: 골든셋 상황 서술을 메모로 넣고 끝까지 문진한다.

    uv run python tools/eval_understand.py --mock          # AI 없이(빈 추출) 기준선, 비용 없음
    uv run python tools/eval_understand.py --oracle        # 골든 사실을 그대로 내는 가짜 추출기(상한선·지표 검증)
    uv run python tools/eval_understand.py                 # 실제 AI(.env의 LLM 설정, 비용 듦)
    uv run python tools/eval_understand.py --limit 10      # 앞 10건만
    uv run python tools/eval_understand.py --save          # 결과를 knowledge/cases/eval/에 저장

가상 사용자
- 첫 메모 = 골든 상황 서술(knowledge/cases/situations.yaml). 남은 질문은 골든 사실로 버튼 답
- 확인 카드(CONFIRM_GUESS): 제안 값이 골든과 같으면 '예', 다르면 '아니요'
- 서류 요청: 골든에 값이 있으면 서류를 올려 검수·적용, 없으면 '서류가 없어요'

지표
- 추출: 메모에서 기록·확인 제안한 사실 수, 골든과 같은 값(정답), 다른 값(오답), 골든에 값이 없는데 낸 값(지어냄)
  정밀도 = 정답 / (정답+오답+지어냄), 재현율 = 정답 / 골든에서 사용자가 답하는 사실 수
- 위험 오답: 지정폐기물 가능성을 지우는 값('해당 없음')을 골든과 다르게 낸 수(가장 중요, 0이어야 함)
- 결론 정확도(골든 기대 결과와 같은가), 버튼 수(메모 뒤 사용자가 누른 횟수), AI 호출 지연
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from fastapi.testclient import TestClient  # noqa: E402
from simulate_interview import golden, truth  # noqa: E402

from app.config import Settings  # noqa: E402
from app.engine.flow import norm  # noqa: E402
from app.interview import catalog as cat  # noqa: E402
from app.interview.guard import risky_clears  # noqa: E402
from app.llm.client import FakeLLMClient  # noqa: E402
from app.main import create_app  # noqa: E402

H = {"X-Company-Id": "eval"}
EMPTY = {"intent": "answer", "facts": [], "group_none_all": False, "question_text": None}


def situations() -> dict[str, str]:
    d = yaml.safe_load((ROOT / "knowledge/cases/situations.yaml").read_text(encoding="utf-8"))
    return {c["id"]: c["situation"] for c in d["cases"]}


class Runner:
    def __init__(self, client: TestClient):
        self.c = client

    def post(self, path, **kw):
        res = self.c.post(f"/internal/v1{path}", headers=self.h, **kw)
        if res.status_code >= 400:
            raise RuntimeError(f"{path} {res.status_code} {res.text[:300]}")
        return res.json()

    def reply(self, cid, qr):
        return self.post(f"/cases/{cid}/diagnosis/messages", json={"quick_reply": qr})

    def evidence(self, cid, turn, facts):
        keys = [k for d in turn["ui"]["requested_documents"] for k in d["facts"]]
        values = {k: truth(facts, k) for k in keys if truth(facts, k) is not None}
        if not values:
            return self.post(f"/cases/{cid}/diagnosis/messages", json={"text": "서류가 없어요"})
        up = self.post(
            f"/cases/{cid}/documents",
            files={"file": ("values.txt", b"eval", "text/plain")},
            data={"facts": json.dumps(values)},
        )
        doc = up["document"]
        body = {
            "values": [
                {"value_id": v["id"], "document_version": doc["version"], "reviewer": "eval"}
                for v in up["values"]
            ]
        }
        return self.post(f"/cases/{cid}/documents/{doc['id']}/values/apply", json=body)

    def step(self, cid, turn, facts):
        if turn["branch"] == "REQUEST_EVIDENCE":
            return self.evidence(cid, turn, facts)
        q = turn["ui"]["question"]
        if q["key"].startswith("confirm:"):
            fact = q["key"].split(":", 1)[1]
            proposed = next(o["value"] for o in q["options"] if o["kind"] == "value")
            if norm(truth(facts, fact)) == norm(proposed):
                return self.reply(cid, {"key": q["key"], "kind": "value", "value": proposed})
            return self.reply(cid, {"key": q["key"], "kind": "expand"})
        if q["unit"] == "group":
            none_all = next(o for o in q["options"] if o["kind"] == "none_all")
            values = {f: norm(truth(facts, f)) for f in q["facts"]}
            kind = (
                "none_all"
                if all(values[f] == v for f, v in none_all["value"].items())
                else "expand"
            )
            return self.reply(cid, {"key": q["key"], "kind": kind})
        value = norm(truth(facts, q["key"]))
        if value is None or value == "unknown":
            return self.reply(cid, {"key": q["key"], "kind": "unknown"})
        return self.reply(cid, {"key": q["key"], "kind": "value", "value": value})

    def run(self, gid, facts, memo, n):
        self.h = {**H, "X-Company-Id": f"eval-{n}"}
        created = self.post("/cases", json={"memo": memo})
        cid, turn = created["case"]["id"], created["turn"]
        clicks = 0
        # 묻지 않는 기본값(가정)이 실제와 다르면 판정 보드에서 고친다(한 번 누름)
        for a in self.c.app.state.kb.plan.assume:
            for k, v in a["set"].items():
                t = norm(truth(facts, k))
                if t is not None and str(t) != str(v):
                    turn = self.reply(cid, {"key": k, "kind": "value", "value": t})
                    clicks += 1
        for _ in range(60):
            if turn["branch"] not in ("ASK_FACT", "REQUEST_EVIDENCE"):
                break
            turn = self.step(cid, turn, facts)
            clicks += 1
        trace = self.c.get(f"/internal/v1/cases/{cid}/trace", headers=self.h).json()
        return cid, turn, clicks, trace


def memo_proposals(trace) -> list[tuple[str, object]]:
    """메모 턴에서 기록하거나 확인 제안한 (사실, 값)."""
    events = trace["events"]
    first_turn = events[0]["turn_id"] if events else None
    und = next(
        (e for e in events if e["kind"] == "UNDERSTAND" and e["turn_id"] == first_turn), None
    )
    if und is None:
        return []
    out = []
    keys = set(und["payload"].get("accepted") or []) | set(und["payload"].get("confirm") or [])
    for f in trace["facts"]:
        if f["turn_id"] == first_turn and f["fact"] in und["payload"].get("accepted", []):
            out.append((f["fact"], f["value"] if f["status"] != "DECLARED_UNKNOWN" else "unknown"))
    for k in und["payload"].get("confirm") or []:
        out.append((k, und["payload"].get("confirm_values", {}).get(k)))
    return [(k, v) for k, v in out if k in keys]


def oracle(name: str, user: str, current: dict) -> dict:
    """메모에는 골든의 사용자 답 사실을 단정형으로 낸다(근거 문구는 메모 앞부분). 나머지 말은 빈 추출."""
    if name != "extract":
        return {}
    said = json.loads(user)["사용자 말"]
    if said != current.get("memo"):
        return EMPTY
    catalog = current["catalog"]
    facts = []
    for p in cat.all_paths(catalog):
        s = cat.spec(catalog, p) or {}
        v = truth(current["facts"], p)
        if s.get("source") != "user" or v is None or isinstance(v, dict):
            continue
        facts.append({"key": p, "value": str(norm(v)), "certainty": "stated", "quote": said[:6]})
    return {**EMPTY, "facts": facts}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="AI 없이(빈 추출) 기준선")
    ap.add_argument("--oracle", action="store_true", help="골든 사실을 그대로 내는 가짜 추출기")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp())
    settings = Settings(database_url=f"sqlite:///{tmp / 'eval.db'}", engine_service_token="")
    fake = args.mock or args.oracle
    if fake:
        settings = settings.model_copy(update={"llm_provider": "off"})
    elif not settings.llm_enabled:
        sys.exit(
            "실제 AI 설정이 없습니다(.env의 LLM_PROVIDER=azure, AZURE_OPENAI_*). --mock으로 실행하세요"
        )
    app = create_app(settings)
    current: dict = {}
    if args.mock:
        app.state.llm = FakeLLMClient(default=lambda name, s, u: EMPTY if name == "extract" else {})
    elif args.oracle:
        app.state.llm = FakeLLMClient(default=lambda name, s, u: oracle(name, u, current))
    situ = situations()
    risky = risky_clears(app.state.kb)
    catalog = app.state.kb.plan.catalog
    user_facts = [
        p for p in cat.all_paths(catalog) if (cat.spec(catalog, p) or {}).get("source") == "user"
    ]
    rows = []
    with TestClient(app) as client:
        runner = Runner(client)
        cases = golden()[: args.limit or None]
        for n, (gid, facts, expected) in enumerate(cases):
            current.update(facts=facts, memo=situ[gid], catalog=catalog)
            cid, turn, clicks, trace = runner.run(gid, facts, situ[gid], n)
            if turn["branch"] == "UNSUPPORTED":
                got = ("INSUFFICIENT_INFO", None, ())
            else:
                last = trace["events"][-1]["result"] or {}
                got = (
                    turn["verdict"]["outcome"],
                    last.get("code"),
                    tuple(sorted(turn["verdict"]["flags"])),
                )
            correct = wrong = made_up = risky_wrong = 0
            for k, v in memo_proposals(trace):
                g = truth(facts, k)
                if g is None:
                    made_up += 1
                elif norm(g) == norm(v):
                    correct += 1
                else:
                    wrong += 1
                    risky_wrong += k in risky and str(v) == risky[k]
            known = sum(1 for p in user_facts if truth(facts, p) not in (None,))
            latency = [
                e["payload"].get("latency_ms", 0) for e in trace["events"] if e["kind"] == "LLM"
            ]
            rows.append(
                {
                    "id": gid,
                    "ok": got == expected,
                    "expected": list(expected),
                    "got": list(got),
                    "clicks": clicks,
                    "correct": correct,
                    "wrong": wrong,
                    "made_up": made_up,
                    "risky_wrong": risky_wrong,
                    "golden_user_facts": known,
                    "llm_latency_ms": latency,
                }
            )
            print(
                f"{gid} {'ok' if got == expected else 'NG'} clicks={clicks} memo +{correct}/-{wrong}/?{made_up}",
                flush=True,
            )
    proposed = sum(r["correct"] + r["wrong"] + r["made_up"] for r in rows)
    lat = [x for r in rows for x in r["llm_latency_ms"]]
    summary = {
        "mode": "mock" if args.mock else "oracle" if args.oracle else "azure",
        "model": getattr(app.state.llm, "model", None),
        "prompt_version": settings.prompt_version,
        "cases": len(rows),
        "verdict_accuracy": sum(r["ok"] for r in rows) / len(rows),
        "clicks_mean": statistics.mean(r["clicks"] for r in rows),
        "extract_precision": (sum(r["correct"] for r in rows) / proposed) if proposed else None,
        "extract_recall": sum(r["correct"] for r in rows)
        / max(1, sum(r["golden_user_facts"] for r in rows)),
        "wrong": sum(r["wrong"] for r in rows),
        "made_up": sum(r["made_up"] for r in rows),
        "risky_wrong": sum(r["risky_wrong"] for r in rows),
        "llm_latency_ms_median": statistics.median(lat) if lat else None,
        "llm_latency_ms_max": max(lat) if lat else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.save:
        out = (
            ROOT
            / "knowledge/cases/eval"
            / f"understand-{summary['mode']}-{datetime.now():%Y%m%d-%H%M}.json"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
