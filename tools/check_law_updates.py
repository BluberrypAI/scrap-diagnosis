"""추적 중인 법령·행정규칙의 변경을 감지하고 선택적으로 Discord에 알린다.

법령 스냅샷이나 판정 규칙은 수정하지 않는다. 현재 ``manifest.yaml``과 공식
국가법령정보 OPEN API 응답을 비교해 변경 사실만 보고한다.

    uv run python tools/check_law_updates.py
    uv run python tools/check_law_updates.py --notify-discord --report report.json

필요한 환경변수:
- LAW_API_OC: 국가법령정보 OPEN API 인증값
- DISCORD_WEBHOOK_URL: ``--notify-discord`` 사용 시 Discord 웹훅
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import load_dotenv

try:  # 직접 실행과 pytest import를 모두 지원한다.
    from collect_law import Api, collect_admin_rule, collect_law
except ModuleNotFoundError:  # pragma: no cover - 실행 위치에 따른 import 차이
    from tools.collect_law import Api, collect_admin_rule, collect_law

ROOT = Path(__file__).resolve().parents[1]
LAW_DIR = ROOT / "knowledge" / "law"
DISCORD_LIMIT = 2000


@dataclass(frozen=True)
class LawChange:
    key: str
    name: str
    kind: str
    previous_version: str
    current_version: str
    previous_effective_date: str
    current_effective_date: str
    version_changed: bool
    source_changed: bool
    tracked_units_changed: bool


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _version(meta: dict) -> str:
    if meta.get("kind") == "law":
        return str(meta.get("mst") or "")
    return str(meta.get("rule_serial") or "")


def compare_document(
    baseline_meta: dict,
    baseline_units: list[dict],
    current_meta: dict,
    current_body: dict,
) -> LawChange | None:
    """한 문서의 버전·전체 원문·추적 단위 변경 여부를 비교한다."""
    version_changed = _version(baseline_meta) != _version(current_meta)
    source_changed = baseline_meta.get("raw_sha256") != current_body.get("raw_sha256")
    tracked_units_changed = _fingerprint(baseline_units) != _fingerprint(current_body["units"])
    if not (version_changed or source_changed or tracked_units_changed):
        return None
    return LawChange(
        key=current_meta["key"],
        name=current_meta["name"],
        kind=current_meta["kind"],
        previous_version=_version(baseline_meta),
        current_version=_version(current_meta),
        previous_effective_date=str(baseline_meta.get("effective_date") or ""),
        current_effective_date=str(current_meta.get("effective_date") or ""),
        version_changed=version_changed,
        source_changed=source_changed,
        tracked_units_changed=tracked_units_changed,
    )


def detect_changes(api: Api, law_dir: Path = LAW_DIR) -> list[LawChange]:
    """targets의 법령·행정규칙을 재조회하되 저장된 파일은 변경하지 않는다."""
    targets = yaml.safe_load((law_dir / "targets.yaml").read_text(encoding="utf-8"))
    manifest = yaml.safe_load((law_dir / "manifest.yaml").read_text(encoding="utf-8"))
    baseline = {item["key"]: item for item in manifest["documents"]}
    changes: list[LawChange] = []
    jobs = [(collect_law, item) for item in targets.get("laws", [])] + [
        (collect_admin_rule, item) for item in targets.get("admin_rules", [])
    ]
    for fetch, target in jobs:
        saved = baseline[target["key"]]
        article = json.loads((law_dir / saved["file"]).read_text(encoding="utf-8"))
        current_meta, current_body = fetch(api, target)
        change = compare_document(saved, article["units"], current_meta, current_body)
        if change:
            changes.append(change)
    return changes


def discord_message(changes: list[LawChange], run_url: str | None = None) -> str:
    lines = [f"⚖️ 추적 법령 변경 감지: {len(changes)}건"]
    for change in changes:
        impact = "사용 조문 변경" if change.tracked_units_changed else "법령 버전/원문 변경"
        effective = change.current_effective_date or "미확인"
        lines.extend(
            [
                "",
                f"• {change.name} ({impact})",
                f"  버전: {change.previous_version or '-'} → {change.current_version or '-'}",
                f"  시행일: {effective}",
            ]
        )
    lines.extend(["", "자동 반영하지 않았습니다. 법령 diff와 회귀 검토가 필요합니다."])
    if run_url:
        lines.append(f"실행 기록: {run_url}")
    message = "\n".join(lines)
    if len(message) > DISCORD_LIMIT:
        suffix = f"\n\n외 {len(changes)}건 포함 · 실행 기록에서 확인하세요."
        message = message[: DISCORD_LIMIT - len(suffix)] + suffix
    return message


def notify_discord(webhook: str, message: str) -> None:
    try:
        response = httpx.post(webhook, json={"content": message}, timeout=20)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        # HTTPX 예외에는 요청 URL이 포함될 수 있으므로 웹훅 비밀 경로를 로그에 남기지 않는다.
        raise RuntimeError(f"Discord 알림 전송 실패: {type(exc).__name__}") from None


def report_payload(changes: list[LawChange]) -> dict:
    return {
        "changed": bool(changes),
        "count": len(changes),
        "changes": [asdict(c) for c in changes],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notify-discord", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    oc = os.getenv("LAW_API_OC", "").strip()
    if not oc:
        sys.exit("LAW_API_OC가 없습니다")

    changes = detect_changes(Api(oc))
    payload = report_payload(changes)
    if args.report:
        args.report.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    if not changes:
        print("추적 중인 법령 변경 없음")
        return

    message = discord_message(changes, os.getenv("GITHUB_RUN_URL"))
    print(message)
    if args.notify_discord:
        webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        if not webhook:
            sys.exit("DISCORD_WEBHOOK_URL이 없습니다")
        notify_discord(webhook, message)


if __name__ == "__main__":
    main()
