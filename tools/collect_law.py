"""법령 원문 수집: knowledge/law/targets.yaml → articles/*.json, manifest.yaml.

국가법령정보 OPEN API에서 현행본을 받아, targets.yaml에 적은 단위(조·항·호·목, 별표 항목,
분류번호 행, 문구 구간)만 저장한다. 원본 전체는 저장하지 않고, manifest.yaml에 원본 응답의
SHA-256과 다시 받을 때 필요한 식별자(일련번호·시행일)를 남긴다.

    uv run python tools/collect_law.py          # 수집(인증키: .env의 LAW_API_OC)

인증키는 요청에만 쓰고 파일·출력에 남기지 않는다.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
LAW_DIR = ROOT / "knowledge" / "law"
BASE = "https://www.law.go.kr/DRF"
PAUSE = 1.5  # 호출 간격(초). 짧은 시간에 많이 부르면 서버가 연결을 끊는다


class Api:
    def __init__(self, oc: str) -> None:
        self.oc = oc
        self.client = httpx.Client(timeout=60)

    def get(self, path: str, **params: str) -> str:
        params = {**params, "OC": self.oc, "type": "XML"}
        for attempt in range(5):
            try:
                r = self.client.get(f"{BASE}/{path}", params=params)
                r.raise_for_status()
                time.sleep(PAUSE)
                text = r.text
                if not text.lstrip().startswith("<?xml"):
                    raise RuntimeError(f"XML이 아닌 응답: {path} {params.get('target')}")
                return text.replace(self.oc, "***")
            except (httpx.HTTPError, RuntimeError) as e:
                if attempt == 4:
                    raise
                print(f"  다시 시도 {attempt + 1}: {type(e).__name__}", flush=True)
                time.sleep(5 * (attempt + 1))
        raise AssertionError("unreachable")


def clean(s: str | None) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s or "")
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def squash(s: str) -> str:
    """줄바꿈·연속 공백을 공백 하나로. 원문 대조는 공백을 무시하고 한다."""
    return re.sub(r"\s+", " ", s).strip()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- 조문 ---------------------------------------------------------------------------------


def _num(label: str, suffix: str, branch: str | None = None) -> str:
    """'1.' → 제1호, ('1.', '2') → 제1호의2, '①' → 제1항, '가.' → 가목.

    API는 가지번호(1의2의 '2')를 호가지번호·목가지번호 필드로 따로 준다.
    표기는 법령 인용 관례("제2조제2호의2")를 따른다.
    """
    label = label.strip()
    br = f"의{branch}" if branch and branch.strip() not in ("", "0") else ""
    if suffix == "항":
        circled = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
        n = circled.index(label[0]) + 1 if label and label[0] in circled else label
        return f"제{n}항{br}"
    if suffix == "호":
        return f"제{label.rstrip('.')}호{br}"
    return f"{label.rstrip('.')}목{br}"


def article_units(root: ET.Element) -> dict[str, dict]:
    """조문을 조·항·호·목 단위로 펼친다. 단위마다 자기와 하위 단위의 글을 모두 담는다."""
    units: dict[str, dict] = {}

    def add(uid: str, title: str, parts: list[str]) -> None:
        units[uid] = {"id": uid, "title": title, "text": "\n".join(p for p in parts if p)}

    for u in root.findall("./조문/조문단위"):
        if u.findtext("조문여부") != "조문":
            continue
        branch = u.findtext("조문가지번호")
        art = f"제{u.findtext('조문번호')}조" + (f"의{branch}" if branch and branch != "0" else "")
        title = u.findtext("조문제목") or ""
        art_text = [clean(u.findtext("조문내용"))]
        for p in u.findall("항"):
            plabel = p.findtext("항번호")
            pid = f"{art}{_num(plabel, '항')}" if plabel else art
            p_text = [clean(p.findtext("항내용"))]
            for h in p.findall("호"):
                hid = pid + _num(h.findtext("호번호") or "", "호", h.findtext("호가지번호"))
                h_text = [clean(h.findtext("호내용"))]
                for m in h.findall("목"):
                    mid = hid + _num(m.findtext("목번호") or "", "목", m.findtext("목가지번호"))
                    m_text = [clean(m.findtext("목내용"))]
                    add(mid, title, m_text)
                    h_text += m_text
                add(hid, title, h_text)
                p_text += h_text
            if plabel:
                add(pid, title, p_text)
            art_text += p_text
        add(art, title, art_text)
    return units


# ---- 별표 ---------------------------------------------------------------------------------

HO = re.compile(r"^(\d+(?:의\d+)?)\.\s")
MOK = re.compile(r"^([가-하])\.\s")
SEMOK = re.compile(r"^(\d+)\)\s")
CODE = re.compile(r"^(\d{2}-\d{2}(?:-\d{2})?)\s+(.*)$")


def annex_items(text: str) -> dict[str, dict]:
    """별표 글을 '제1호', '제1호가목', '제1호가목1)' 단위로 나눈다(하위 단위 글 포함).

    context는 상위 항목의 첫 줄(표제)이다. 예: 제1호가목1)의 context는
    ["1. 특정시설에서 발생되는 폐기물", "가. 폐합성 고분자화합물"].
    별표는 고정 폭으로 줄이 넘어가므로 줄 사이는 공백 하나로 잇는다(원문 대조는 공백 무시).
    """
    items: dict[str, list[str]] = {}
    heads: dict[str, list[str]] = {}
    ho = mok = semok = None
    ho_head = mok_head = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if m := HO.match(line):
            n, _, b = m.group(1).partition("의")
            ho, mok, semok = f"제{n}호" + (f"의{b}" if b else ""), None, None
            ho_head, mok_head = line, ""
            heads[ho] = []
        elif ho and (m := MOK.match(line)):
            mok, semok = f"{m.group(1)}목", None
            mok_head = line
            heads[ho + mok] = [ho_head]
        elif ho and mok and (m := SEMOK.match(line)):
            semok = f"{m.group(1)})"
            heads[ho + mok + semok] = [ho_head, mok_head]
        if not ho:
            continue
        for key in {ho, ho + (mok or ""), ho + (mok or "") + (semok or "")}:
            items.setdefault(key, []).append(line)
    return {
        k: {"text": squash(" ".join(v)), "context": [squash(h) for h in heads.get(k, [])]}
        for k, v in items.items()
    }


def annex_codes(text: str) -> dict[str, str]:
    """분류번호표: 'NN-NN(-NN) 명칭' 행. 줄이 넘어간 명칭은 이어 붙인다."""
    rows: dict[str, list[str]] = {}
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if m := CODE.match(line):
            cur = m.group(1)
            rows[cur] = [m.group(2)]
        elif cur and not HO.match(line) and not line.startswith(("※", "비고", "■")):
            rows[cur].append(line)
        else:
            cur = None
    return {k: squash(" ".join(v)) for k, v in rows.items()}


R_CODE = re.compile(r"R-\d+(?:-\d+)?")
TABLE_CODE = re.compile(r"^│\s*(\d{2}-\d{2}-\d{2})\s*│")


def annex_table_rows(text: str) -> dict[str, dict]:
    """재활용 가능 유형표(별표 4의3) 같은 상자 표의 분류번호 행.

    한 행은 '│분류번호│종류│재활용 유형│사전 분석·확인 필요 여부│'이고, 같은 분류번호 안에서
    '├'로 시작하는 안쪽 선이 하위 행(사전 분석 '해당 없음'과 '해당')을 나눈다.
    돌려주는 값: {분류번호: {name, groups: [{types, analysis}], text}}
    """
    rows: dict[str, dict] = {}
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if m := TABLE_CODE.match(line):
            cur = {"name": [], "groups": [{"types": [], "flag": []}]}
            rows[m.group(1)] = cur
        elif cur is None:
            continue
        elif line.startswith(("├", "└")):
            cur = None  # 다음 분류번호 행 전의 가로선
            continue
        if "├" in line:
            cur["groups"].append({"types": [], "flag": []})
            continue
        cells = [c.strip() for c in line.split("│")]
        if len(cells) < 6:
            continue
        cur["name"].append(cells[2])
        cur["groups"][-1]["types"].append(cells[3])
        cur["groups"][-1]["flag"].append(cells[4])
    out = {}
    for code, r in rows.items():
        groups = []
        for g in r["groups"]:
            types = R_CODE.findall(" ".join(g["types"]))
            flag = "".join(g["flag"]).replace(" ", "")
            groups.append({"types": types, "analysis": flag})
        name = "".join(r["name"])
        text = f"{code} {name} " + " ".join(
            f"[{', '.join(g['types'])} / 사전 분석·확인 {g['analysis'] or '표시 없음'}]"
            for g in groups
        )
        out[code] = {"name": name, "groups": groups, "text": squash(text)}
    return out


def recycling_types(groups: list[dict]) -> dict[str, list[str]]:
    """사전 분석·확인 필요 여부로 나눈 재활용 유형: free(해당 없음)·analysis(해당)·unmarked."""
    out: dict[str, list[str]] = {"free": [], "analysis": [], "unmarked": []}
    for g in groups:
        key = {"해당없음": "free", "해당": "analysis"}.get(g["analysis"], "unmarked")
        out[key] += [t for t in g["types"] if t not in out[key]]
    return out


def text_slice(text: str, start: str, end: str | None) -> str:
    """start 문구부터 다음 end 문구 직전까지(공백 차이는 무시)."""
    flat = squash(text)

    def pat(s: str) -> str:
        return r"\s*".join(map(re.escape, s.strip())) + (r"\s" if s.endswith(" ") else "")

    m = re.search(pat(start), flat)
    if not m:
        raise SystemExit(f"구간 시작 문구를 찾지 못함: {start}")
    if end is None:  # 끝 문구가 없으면 별표 끝까지
        return flat[m.start() :].strip()
    e = re.search(pat(end), flat[m.end() :])
    return flat[m.start() : m.end() + e.start()].strip() if e else flat[m.start() :]


def law_annexes(root: ET.Element) -> dict[str, dict]:
    out = {}
    for a in root.iter("별표단위"):
        if (a.findtext("별표구분") or "별표") != "별표":
            continue
        n = str(int(a.findtext("별표번호")))
        b = int(a.findtext("별표가지번호") or 0)
        key = f"별표{n}" + (f"의{b}" if b else "")
        out[key] = {"title": a.findtext("별표제목") or "", "text": clean(a.findtext("별표내용"))}
    return out


def pick_annex(spec: dict, annexes: dict[str, dict]) -> list[dict]:
    name = spec["annex"]
    if name not in annexes:
        raise SystemExit(f"별표 없음: {name}")
    a = annexes[name]
    if "items" in spec:
        items = annex_items(a["text"])
        missing = [i for i in spec["items"] if i not in items]
        if missing:
            raise SystemExit(f"{name} 항목을 찾지 못함: {missing}")
        return [
            {
                "id": f"{name}{i}",
                "title": a["title"],
                **({"context": items[i]["context"]} if items[i]["context"] else {}),
                "text": items[i]["text"],
            }
            for i in spec["items"]
        ]
    if "codes" in spec:
        rows = annex_codes(a["text"])
        got = [
            {"id": f"{name}/{c}", "title": a["title"], "text": f"{c} {t}"}
            for c, t in rows.items()
            if any(c.startswith(p) for p in spec["codes"])
        ]
        if not got:
            raise SystemExit(f"{name}에서 분류번호 행을 찾지 못함: {spec['codes']}")
        return got
    if "table_rows" in spec:
        rows = annex_table_rows(a["text"])
        missing = [c for c in spec["table_rows"] if c not in rows]
        if missing:
            raise SystemExit(f"{name}에서 표 행을 찾지 못함: {missing}")
        return [
            {
                "id": f"{name}/{c}",
                "title": a["title"],
                "text": rows[c]["text"],
                "recycling_types": recycling_types(rows[c]["groups"]),
            }
            for c in spec["table_rows"]
        ]
    if "slice" in spec:
        s = spec["slice"]
        text = text_slice(a["text"], s["from"], s.get("to"))
        return [{"id": f"{name}/{spec['id']}", "title": a["title"], "text": text}]
    return [{"id": name, "title": a["title"], "text": squash(a["text"])}]


# ---- 수집 ---------------------------------------------------------------------------------


def collect_law(api: Api, t: dict) -> tuple[dict, dict]:
    search = ET.fromstring(api.get("lawSearch.do", target="law", query=t["name"], display="100"))
    hits = [
        it
        for it in search.findall("law")
        if it.findtext("법령명한글") == t["name"] and it.findtext("현행연혁코드") == "현행"
    ]
    if len(hits) != 1:
        raise SystemExit(f"현행 법령을 하나로 찾지 못함: {t['name']} ({len(hits)}건)")
    mst = hits[0].findtext("법령일련번호")
    raw = api.get("lawService.do", target="law", MST=mst)
    root = ET.fromstring(raw)
    info = root.find("기본정보")
    arts = article_units(root)
    annexes = law_annexes(root)
    units: list[dict] = []
    for spec in t["units"]:
        if isinstance(spec, str):
            if spec not in arts:
                raise SystemExit(f"{t['name']} 단위 없음: {spec}")
            units.append(arts[spec])
        else:
            units += pick_annex(spec, annexes)
    meta = {
        "key": t["key"],
        "kind": "law",
        "name": t["name"],
        "law_type": info.findtext("법종구분"),
        "law_id": info.findtext("법령ID"),
        "mst": mst,
        "promulgation_no": info.findtext("공포번호"),
        "promulgation_date": info.findtext("공포일자"),
        "effective_date": info.findtext("시행일자"),
        "why": squash(t["why"]),
    }
    return meta, {
        "raw_sha256": sha256(raw),
        "refetch": {"target": "law", "MST": mst},
        "units": units,
    }


def collect_admin_rule(api: Api, t: dict) -> tuple[dict, dict]:
    search = ET.fromstring(api.get("lawSearch.do", target="admrul", query=t["name"], display="100"))
    hits = [
        it
        for it in search.findall("admrul")
        if it.findtext("행정규칙명") == t["name"] and it.findtext("현행연혁구분") == "현행"
    ]
    if len(hits) != 1:
        raise SystemExit(f"현행 행정규칙을 하나로 찾지 못함: {t['name']} ({len(hits)}건)")
    sid = hits[0].findtext("행정규칙일련번호")
    raw = api.get("lawService.do", target="admrul", ID=sid)
    root = ET.fromstring(raw)
    info = root.find("행정규칙기본정보")
    arts = {}
    for e in root.iter("조문내용"):
        text = clean(e.text)
        if m := re.match(r"(제\d+조(?:의\d+)?)\s*\(([^)]*)\)", text):
            arts[m.group(1)] = {"id": m.group(1), "title": m.group(2), "text": text}
    annexes = {}
    for a in root.iter("별표단위"):
        n = str(int(a.findtext("별표번호") or 0))
        b = int(a.findtext("별표가지번호") or 0)
        if (a.findtext("별표구분") or "별표") == "별표":
            annexes[f"별표{n}" + (f"의{b}" if b else "")] = {
                "title": a.findtext("별표제목") or "",
                "text": clean(a.findtext("별표내용")),
            }
    units: list[dict] = []
    for spec in t["units"]:
        if isinstance(spec, str):
            if spec not in arts:
                raise SystemExit(f"{t['name']} 조문 없음: {spec}")
            units.append(arts[spec])
        else:
            units += pick_annex(spec, annexes)
    meta = {
        "key": t["key"],
        "kind": "admin_rule",
        "name": t["name"],
        "rule_type": info.findtext("행정규칙종류"),
        "rule_serial": sid,
        "issued_no": info.findtext("발령번호"),
        "issued_date": info.findtext("발령일자"),
        "effective_date": info.findtext("시행일자"),
        "ministry": info.findtext("소관부처명"),
        "why": squash(t["why"]),
    }
    return meta, {
        "raw_sha256": sha256(raw),
        "refetch": {"target": "admrul", "ID": sid},
        "units": units,
    }


def collect_interpretation(api: Api, t: dict) -> tuple[dict, dict]:
    raw = api.get("lawService.do", target=t["target"], ID=t["id"])
    root = ET.fromstring(raw)
    fields = {e.tag: clean(e.text) for e in root.iter() if e.text and e.text.strip()}
    title = fields.get("안건명", "")
    date = fields.get("해석일자") or fields.get("회신일자") or ""
    units = [
        {"id": tag, "title": title, "text": fields[tag]}
        for tag in ("질의요지", "회답", "이유", "관련법령")
        if fields.get(tag)
    ]
    if not units:
        raise SystemExit(f"해석례 본문 없음: {t['key']}")
    meta = {
        "key": t["key"],
        "kind": "interpretation",
        "name": title,
        "source": "법제처 법령해석례" if t["target"] == "expc" else "기후에너지환경부 법령해석",
        "serial": t["id"],
        "case_no": fields.get("안건번호"),
        "interpreted_on": date,
        "authority": fields.get("해석기관명") or fields.get("회신기관명"),
        "why": squash(t["why"]),
    }
    return meta, {
        "raw_sha256": sha256(raw),
        "refetch": {"target": t["target"], "ID": t["id"]},
        "units": units,
    }


def main() -> None:
    load_dotenv(ROOT / ".env")
    oc = os.environ.get("LAW_API_OC", "").strip()
    if not oc:
        sys.exit("LAW_API_OC가 없습니다(.env)")
    targets = yaml.safe_load((LAW_DIR / "targets.yaml").read_text(encoding="utf-8"))
    api = Api(oc)
    out_dir = LAW_DIR / "articles"
    out_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    manifest = []
    jobs = (
        [(collect_law, t) for t in targets.get("laws", [])]
        + [(collect_admin_rule, t) for t in targets.get("admin_rules", [])]
        + [(collect_interpretation, t) for t in targets.get("interpretations", [])]
    )
    for fn, t in jobs:
        print(f"- {t['key']} {t.get('name', '')}", flush=True)
        meta, body = fn(api, t)
        doc = {**meta, "fetched_at": fetched_at, "units": body["units"]}
        (out_dir / f"{t['key']}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        manifest.append(
            {
                **{k: v for k, v in meta.items() if k != "why"},
                "fetched_at": fetched_at,
                "raw_sha256": body["raw_sha256"],
                "refetch": body["refetch"],
                "units": [u["id"] for u in body["units"]],
                "file": f"articles/{t['key']}.json",
            }
        )
        print(f"  {len(body['units'])}개 단위", flush=True)
    header = (
        "# 자동 생성: tools/collect_law.py — 직접 고치지 않는다.\n"
        "# raw_sha256은 받은 원본 응답(인증키 제거)의 해시다.\n"
        "# refetch의 식별자로 같은 버전을 다시 받아 대조한다.\n"
    )
    (LAW_DIR / "manifest.yaml").write_text(
        header + yaml.safe_dump({"documents": manifest}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"완료: 문서 {len(manifest)}개")


if __name__ == "__main__":
    main()
