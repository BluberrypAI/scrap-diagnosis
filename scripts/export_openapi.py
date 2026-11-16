"""OpenAPI 명세를 docs/api/openapi.json으로 내보낸다(결정적 출력).

실행: `uv run python scripts/export_openapi.py` (--check: 저장된 파일과 같은지만 확인)
KB·LLM·DB 없이 라우트 정의만으로 만든다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "api" / "openapi.json"


def build_spec() -> dict:
    sys.path.insert(0, str(ROOT))
    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        database_url="sqlite://", llm_provider="off", kb_dir=ROOT / "data" / "sample"
    )
    return create_app(settings).openapi()


def render() -> str:
    return json.dumps(build_spec(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("openapi.json 최신" if same else "openapi.json이 코드와 다릅니다")
        return 0 if same else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
