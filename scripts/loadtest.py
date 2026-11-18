"""동기 vs 비동기 서버 부하 테스트 (진단 한 턴 모사, 실제 LLM/DB 없음).

한 턴 = 실제 run_engine(data/real, CPU) + LLM 대기 L초(sleep) + DB 대기 3ms x2(sleep 모사).
설정(모드):
  sync        : sync def 엔드포인트 (anyio 스레드풀 기본 40)
  sync200     : 위와 같으나 스레드풀 200
  async       : async def + CPU는 anyio.to_thread.run_sync (기본 40 스레드), 대기는 asyncio.sleep
  async_inline: async def + CPU를 이벤트 루프에서 직접 실행 (함정 시연)

실행: PYTHONIOENCODING=utf-8 uv run python scripts/loadtest.py            # 전체 매트릭스
      uv run python scripts/loadtest.py --heavy                             # 빈 세션(CPU ~0.2s/턴)
      uv run python scripts/loadtest.py --quick                             # N=20,50만, L=3
      uv run python scripts/loadtest.py --serve sync --port 8123 --latency 3  # (내부용) 서버만
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import statistics
import subprocess
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

AS_OF = date(2026, 11, 8)
DB_SLEEP = 0.003  # aiosqlite 미설치 -> DB는 3ms 대기로 모사 (읽기 1회 + 쓰기 1회)
HEAVY = os.environ.get("LOADTEST_HEAVY") == "1"  # 빈 세션(첫 질문, ~0.2s CPU) 사용
MODES = ["sync", "sync200", "async", "async_inline"]

# 대표 사실 집합: 중반 턴 (소재/배출 정보 일부 확정)
FACTS = dict(
    material="pp",
    emission_facility=True,
    material_fate="released",
    circular_resource_recognized=False,
    law_exclusion="none",
    designated_residue=False,
    oil_presence="none",
    pcb_possible=False,
    toxic_chemical_discard=False,
)


def _make_fact(key, value):
    from app.domain.facts import Fact, FactStatus

    return Fact(
        key=key,
        value=value,
        status=FactStatus.CLAIMED,
        source_ref="",
        recorded_at=datetime(2026, 11, 8, tzinfo=UTC),
    )


def _load_kb():
    from app.rules.loader import load_kb

    return load_kb(str(ROOT / "data" / "real"), "rules/tables")


def _engine_once(kb):
    from app.agent.router import SessionState, run_engine
    from app.domain.facts import FactStore

    facts = [] if HEAVY else [_make_fact(k, v) for k, v in FACTS.items()]
    return run_engine(kb, FactStore(facts), SessionState(), AS_OF)


# ---------------------------------------------------------------- 서버
def serve(mode: str, port: int, latency: float) -> None:
    from contextlib import asynccontextmanager

    import anyio.to_thread
    import uvicorn
    from fastapi import FastAPI

    kb = _load_kb()
    _engine_once(kb)  # 워밍업

    @asynccontextmanager
    async def lifespan(_app):
        if mode == "sync200":
            anyio.to_thread.current_default_thread_limiter().total_tokens = 200
        yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"ok": True}

    if mode in ("sync", "sync200"):

        @app.post("/turn")
        def turn():
            time.sleep(DB_SLEEP)  # DB read
            _engine_once(kb)  # CPU
            time.sleep(latency)  # LLM
            time.sleep(DB_SLEEP)  # DB write
            return {"ok": True}

    else:
        inline = mode == "async_inline"

        @app.post("/turn")
        async def turn():
            await asyncio.sleep(DB_SLEEP)
            if inline:
                _engine_once(kb)
            else:
                await anyio.to_thread.run_sync(_engine_once, kb)
            await asyncio.sleep(latency)
            await asyncio.sleep(DB_SLEEP)
            return {"ok": True}

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


# ---------------------------------------------------------------- 클라이언트
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(p * (len(xs) - 1)))]


async def _fire(port: int, n: int) -> dict:
    import httpx

    url = f"http://127.0.0.1:{port}/turn"
    lat: list[float] = []
    errors = 0
    async with httpx.AsyncClient(
        timeout=300, limits=httpx.Limits(max_connections=None, max_keepalive_connections=None)
    ) as c:
        await c.post(url)  # 워밍업

        async def one():
            nonlocal errors
            t = time.perf_counter()
            try:
                r = await c.post(url)
                if r.status_code != 200:
                    errors += 1
                    return
                lat.append(time.perf_counter() - t)
            except Exception:
                errors += 1

        t0 = time.perf_counter()
        await asyncio.gather(*[one() for _ in range(n)])
        total = time.perf_counter() - t0
    return dict(
        total=total,
        tps=len(lat) / total if total else 0.0,
        p50=statistics.median(lat) if lat else float("nan"),
        p95=_pct(lat, 0.95) if lat else float("nan"),
        errors=errors,
    )


def run_config(mode: str, n_list: list[int], latency: float) -> list[tuple]:
    import httpx

    port = _free_port()
    env = dict(os.environ, PYTHONIOENCODING="utf-8", LOADTEST_HEAVY="1" if HEAVY else "0")
    proc = subprocess.Popen(
        [sys.executable, __file__, "--serve", mode, "--port", str(port), "--latency", str(latency)],
        env=env,
        cwd=ROOT,
    )
    rows = []
    try:
        for _ in range(100):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                    break
            except Exception:
                time.sleep(0.3)
        else:
            raise RuntimeError("server did not start")
        for n in n_list:
            r = asyncio.run(_fire(port, n))
            rows.append((mode, latency, n, r))
            print(
                f"{mode:13s} L={latency:<3g} N={n:<4d} total={r['total']:6.2f}s "
                f"tps={r['tps']:6.2f} p50={r['p50']:6.2f} p95={r['p95']:6.2f} err={r['errors']}",
                flush=True,
            )
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return rows


def measure_prompt() -> None:
    from app.agent.extractor import build_system_prompt, build_user_prompt
    from app.agent.router import SessionState, run_engine
    from app.domain.facts import FactStore

    kb = _load_kb()
    store = FactStore([_make_fact(k, v) for k, v in FACTS.items()])
    step = _engine_once(kb)
    t0 = time.perf_counter()
    for _ in range(20):
        _engine_once(kb)
    cpu = (time.perf_counter() - t0) / 20
    t1 = time.perf_counter()
    run_engine(kb, FactStore(), SessionState(), AS_OF)
    first = time.perf_counter() - t1
    user = build_user_prompt(
        kb,
        "PP 사출 불량품입니다",
        effective=store.effective(),
        last_question=step.decision.question,
        recent=[{"role": "user", "text": "PP 사출 불량품입니다"}] * 6,
    )
    print(
        f"run_engine CPU (대표 사실 집합) 평균 {cpu * 1000:.1f} ms; "
        f"빈 세션 첫 호출 {first * 1000:.0f} ms"
    )
    system = build_system_prompt(kb)
    print(f"extractor user prompt {len(user)} chars, system prompt {len(system)} chars")
    print(f"입력 토큰 추정(chars/2): {(len(user) + len(system)) // 2}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", choices=MODES)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--latency", type=float, default=3.0)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--heavy", action="store_true", help="CPU 무거운 첫 질문(빈 세션)로 측정")
    ap.add_argument("--skip-prompt", action="store_true")
    a = ap.parse_args()
    if a.heavy:
        global HEAVY
        HEAVY = True
        os.environ["LOADTEST_HEAVY"] = "1"
    if a.serve:
        serve(a.serve, a.port, a.latency)
        return
    if not a.skip_prompt and not HEAVY:
        measure_prompt()
    ns = [20, 50] if a.quick else [20, 50, 100, 200]
    if HEAVY:
        ns = [50, 100]
    all_rows: list[tuple] = []
    for mode in MODES:
        all_rows += run_config(mode, ns, 3.0)
    if not a.quick and not HEAVY:
        for mode in MODES:
            all_rows += run_config(mode, [200], 1.0)
    print("\n| 모드 | L(s) | N | 총 시간(s) | 처리량(턴/s) | p50(s) | p95(s) | 오류 |")
    print("|---|---|---|---|---|---|---|---|")
    for mode, lat, n, r in all_rows:
        print(
            f"| {mode} | {lat:g} | {n} | {r['total']:.2f} | {r['tps']:.2f} | {r['p50']:.2f} "
            f"| {r['p95']:.2f} | {r['errors']} |"
        )


if __name__ == "__main__":
    main()
