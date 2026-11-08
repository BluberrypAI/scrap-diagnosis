"""골든 세트 평가.

uv run python scripts/eval.py --mock-extractor        # LLM 없이 엔진 회귀 (골든의 extract 사용)
uv run python scripts/eval.py                         # 실제 Azure OpenAI로 추출·응답
uv run python scripts/eval.py --only G-001 --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.golden import metrics, run_case  # noqa: E402
from app.agent.llm_client import make_client  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.rules.loader import load_kb  # noqa: E402

KB_DIRS = {"sample": ROOT / "data" / "sample", "real": ROOT / "data" / "real"}


def load_cases(path: Path) -> list[dict]:
    cases: list[dict] = []
    for p in sorted(path.glob("*.yaml")) if path.is_dir() else [path]:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        cases.extend(raw if isinstance(raw, list) else [raw])
    return cases


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(ROOT / "data" / "golden"))
    ap.add_argument("--mock-extractor", action="store_true")
    ap.add_argument(
        "--template-responder", action="store_true", help="응답 생성에 LLM을 쓰지 않음(템플릿)"
    )
    ap.add_argument("--only", action="append")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--report", help="결과 JSON 저장 경로")
    args = ap.parse_args()

    settings = get_settings()
    llm = None if args.mock_extractor and args.template_responder else make_client(settings)
    if not args.mock_extractor and llm is None:
        print("LLM 설정이 없습니다(.env). --mock-extractor로 실행하세요.")
        return 2
    responder = None if (args.template_responder or args.mock_extractor) else llm
    kbs = {}
    results = []
    for case in load_cases(Path(args.path)):
        if args.only and case["id"] not in args.only:
            continue
        kb_name = case.get("kb", "sample")
        kb = kbs.setdefault(kb_name, load_kb(KB_DIRS[kb_name]))
        res = run_case(
            case, kb, mock_extractor=args.mock_extractor, extractor_llm=llm, responder_llm=responder
        )
        results.append(res)
        mark = "PASS" if res.ok else "FAIL"
        print(
            f"{mark} {res.case_id} ({kb_name}) 결과={res.final_branch} {res.final_code or ''} "
            f"질문 {res.questions_asked}회"
        )
        for t in res.turns:
            if args.verbose or not t.ok:
                flag = "  " if t.ok else "!!"
                print(f"   {flag} {t.turn}. {t.input}")
                print(
                    f"        → {t.got['branch']} ask={t.got['ask_fact']} code={t.got['code']} "
                    f"docs={t.got['documents']} fail={t.got['failure_reason']}"
                    f" 추출 {t.extracted}/거부 {t.rejected}{' [템플릿]' if t.template else ''}"
                )
                if args.verbose:
                    print(f"        말: {t.got['message']}")
                for m in t.mismatches:
                    print(f"        ✗ {m}")
    m = metrics(results)
    print(json.dumps(m, ensure_ascii=False, indent=2))
    if args.report:
        Path(args.report).write_text(
            json.dumps(
                {"metrics": m, "results": [r.model_dump() for r in results]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
