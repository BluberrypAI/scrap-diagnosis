"""실제 AI(Azure)로 문진 한 턴의 지연을 잰다. 서버 → 엔진 타임아웃을 정할 때 쓴다.

    uv run python scripts/turn_latency.py --runs 3
    uv run python scripts/turn_latency.py --db postgresql+psycopg://wd:wd@localhost:55432/waste_diagnosis

턴마다 전체 시간과 그 안의 AI 호출(추출·응답) 시간을 Trace의 LLM 기록에서 뽑아 낸다.
LLM 설정은 .env(값은 출력하지 않는다). DB는 기본 임시 SQLite.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

# 자유 입력 위주의 PP 문진(추출·응답 AI를 모두 탄다). 마지막은 묶음 질문 버튼.
SCRIPT: list[str | dict] = [
    "PP 사출 공정에서 나온 스크랩이에요",
    "고체 덩어리예요",
    "기름이나 약품은 안 묻었어요",
    {"key": "scope_screen", "kind": "none_all"},
]


def _calls(trace: dict, index: int) -> list[dict]:
    """index번째 대화 턴(Trace 행 중 llm_calls를 가진 턴)의 AI 호출 기록."""
    turns = [t for t in trace["sessions"][0]["turns"] if "llm_calls" in t["payload"]]
    if index >= len(turns):
        return []
    return turns[index]["payload"]["llm_calls"] or []


def _tokens(c: dict) -> tuple[int, int, int, int]:
    """(입력, 캐시 적중 입력, 출력, 그중 추론) 토큰."""
    u = c.get("usage") or {}
    pin = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    rsn = (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
    return u.get("prompt_tokens") or 0, pin, u.get("completion_tokens") or 0, rsn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--db", default=None)
    efforts = ["minimal", "low", "medium", "high"]
    ap.add_argument("--extract-effort", choices=efforts, default=None)
    ap.add_argument("--respond-effort", choices=efforts, default=None)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    db = args.db or f"sqlite:///{(Path(tempfile.mkdtemp()) / 'lat.db').as_posix()}"
    over = {
        k: v
        for k, v in {
            "extract_reasoning_effort": args.extract_effort,
            "respond_reasoning_effort": args.respond_effort,
        }.items()
        if v
    }
    settings = Settings(database_url=db, db_create_all=True, app_env="dev", **over)
    if not settings.llm_enabled:
        sys.exit("LLM 설정이 없습니다(.env의 LLM_PROVIDER=azure 등)")
    app = create_app(settings)
    rows: list[tuple[str, float, list[dict]]] = []
    with TestClient(app) as c:
        co = c.post("/companies", json={"name": "지연 측정", "profile": {}}).json()
        h = {"X-Company-Id": co["id"]}
        for run in range(args.runs):
            t = time.perf_counter()
            r = c.post("/cases", json={"memo": SCRIPT[0]}, headers=h)
            r.raise_for_status()
            first = time.perf_counter() - t
            cid = r.json()["case"]["id"]
            timings = [("생성+첫 메모", first, 0)]
            for i, step in enumerate(SCRIPT[1:], start=1):
                body = {"quick_reply": step} if isinstance(step, dict) else {"text": step}
                t = time.perf_counter()
                r = c.post(f"/cases/{cid}/diagnosis/messages", json=body, headers=h)
                r.raise_for_status()
                label = "버튼" if isinstance(step, dict) else "자유 입력"
                timings.append((f"{label} {i}", time.perf_counter() - t, i))
            trace = c.get(f"/cases/{cid}/trace", headers=h).json()
            for label, sec, seq in timings:
                rows.append((label, sec, _calls(trace, seq)))
            print(f"run {run + 1}: 마지막 분기 {r.json()['branch']}")

    print("\n| 턴 | 전체(s) | AI 호출(ms) |\n|---|---|---|")
    for label, sec, calls in rows:
        ms = ", ".join(f"{c.get('name')} {c.get('latency_ms', 0)}" for c in calls)
        print(f"| {label} | {sec:.2f} | {ms or '-'} |")
    effort = f"추출 {args.extract_effort or '기본'}, 응답 {args.respond_effort or '기본'}"
    print(f"\n추론 강도: {effort}")
    print("| 호출 | 횟수 | 평균(ms) | 입력 | 캐시 적중 | 출력 | 그중 추론 | 오류 |")
    print("|---|---|---|---|---|---|---|---|")
    for name in ("extract", "respond"):
        cs = [c for _, _, calls in rows for c in calls if c.get("name") == name]
        if not cs:
            continue
        inp, hit, out, rsn = (sum(x) for x in zip(*(_tokens(c) for c in cs), strict=True))
        avg = statistics.mean(c.get("latency_ms", 0) for c in cs)
        err = sum(1 for c in cs if c.get("error"))
        print(f"| {name} | {len(cs)} | {avg:.0f} | {inp} | {hit} | {out} | {rsn} | {err} |")
    secs = sorted(s for _, s, _ in rows)
    p95 = secs[min(len(secs) - 1, int(round(0.95 * (len(secs) - 1))))]
    med = statistics.median(secs)
    print(f"\n턴 {len(secs)}개: 중앙값 {med:.2f}s, p95 {p95:.2f}s, 최대 {secs[-1]:.2f}s")


if __name__ == "__main__":
    main()
