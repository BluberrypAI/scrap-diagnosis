"""골든 데이터셋 Step 3: 외부 레이블 후보 수집(판례·법령해석례·부처 해석).

    uv run python tools/collect_external_cases.py   # knowledge/cases/external/candidates.yaml

법원·법제처·기후에너지환경부가 판단한 사건 중 우리 범위(폐기물 해당 여부, 사업장·지정 여부,
합성수지·금속캔 분류)와 관련 있을 만한 것을 모은다. 여기서는 후보만 모으고, 골든셋에 넣을지는
사람이 본문을 보고 정한다(screening).

출발 목록: 키워드 검색 + scrap-route data/config/legal_scope.json의 폐기물 판례 사건번호.
"""

from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_law import Api, clean, squash  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "knowledge" / "cases" / "external" / "candidates.yaml"

KEYWORDS = [
    "폐기물 해당",
    "폐기물에 해당",
    "폐합성수지",
    "합성수지",
    "지정폐기물",
    "사업장폐기물",
    "폐유",
    "금속캔",
    "재활용 원료",
    "순환자원",
]
# scrap-route data/config/legal_scope.json의 판례 사건번호(폐기물 정의·재활용 관련)
SEED_CASES = [
    "2023두62830",
    "97도1189",
    "97도1575",
    "2005도7281",
    "2002도3116",
    "2009두6681",
    "2011도9549",
    "2019두43474",
    "2022노3095",
    "2001도70",
    "2002도6081",
    "2017도9582",
]
SOURCES = {
    "prec": {"item": "prec", "id": "판례일련번호", "title": "사건명", "date": "선고일자"},
    "expc": {"item": "expc", "id": "법령해석례일련번호", "title": "안건명", "date": "회신일자"},
    "meCgmExpc": {"item": None, "id": "법령해석일련번호", "title": "안건명", "date": "해석일자"},
}
RELEVANT = re.compile(r"폐기물|합성수지|폐유|금속캔|순환자원|재활용")


def search(api: Api, target: str, query: str) -> list[dict]:
    text = api.get("lawSearch.do", target=target, query=query, display="100")
    root = ET.fromstring(text)
    return [{c.tag: (c.text or "").strip() for c in it} for it in root if len(it)]


def body(api: Api, target: str, sid: str) -> dict:
    root = ET.fromstring(api.get("lawService.do", target=target, ID=sid))
    return {e.tag: clean(e.text) for e in root.iter() if e.text and e.text.strip()}


def main() -> None:
    load_dotenv(ROOT / ".env")
    api = Api(os.environ["LAW_API_OC"])
    found: dict[tuple[str, str], dict] = {}
    for target, meta in SOURCES.items():
        queries = KEYWORDS + (SEED_CASES if target == "prec" else [])
        for q in queries:
            try:
                rows = search(api, target, q)
            except Exception as e:  # 미승인 API는 XML이 아닌 응답을 준다
                print(f"  {target} 검색 실패({q}): {type(e).__name__}")
                break
            for r in rows:
                title = r.get(meta["title"], "")
                if not RELEVANT.search(title) and q not in SEED_CASES:
                    continue
                k = (target, r.get(meta["id"], ""))
                found.setdefault(
                    k,
                    {
                        "target": target,
                        "id": k[1],
                        "title": title,
                        "date": r.get(meta["date"]),
                        "queries": [],
                    },
                )
                found[k]["queries"].append(q)
    out = []
    for (target, sid), item in sorted(found.items()):
        b = body(api, target, sid)
        summary = b.get("판결요지") or b.get("회답") or b.get("판시사항") or ""
        out.append(
            {
                **item,
                "case_no": b.get("사건번호") or b.get("안건번호"),
                "summary": squash(summary)[:1200],
                "screening": None,
            }
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "# Step 3 외부 레이블 후보. screening에 include/exclude와 사유를 적는다.\n"
        + yaml.safe_dump({"candidates": out}, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
        newline="\n",
    )
    print(f"후보 {len(out)}건 → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
