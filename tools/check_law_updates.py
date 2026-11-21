"""추적 중인 법령·행정규칙의 변경을 감지하고 선택적으로 Discord에 알린다.

법령 스냅샷이나 판정 규칙은 수정하지 않는다. 현재 ``manifest.yaml``과 공식
국가법령정보센터의 공개 최신본 페이지를 비교해 변경 사실만 보고한다.

    uv run python tools/check_law_updates.py
    uv run python tools/check_law_updates.py --notify-discord --report report.json

필요한 환경변수:
- DISCORD_WEBHOOK_URL: ``--notify-discord`` 사용 시 Discord 웹훅
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
LAW_DIR = ROOT / "knowledge" / "law"
DISCORD_LIMIT = 2000
PUBLIC_BASE = "https://www.law.go.kr"


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


class PublicLawClient:
    """인증 없이 공개되는 국가법령정보센터 최신본 페이지를 조회한다."""

    def __init__(self) -> None:
        self.client = httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "BlueberrypAI-law-change-alert/1.0"},
        )

    def current_metadata(self, baseline: dict) -> dict:
        category = "법령" if baseline["kind"] == "law" else "행정규칙"
        response = self.client.get(f"{PUBLIC_BASE}/{category}/{baseline['name']}")
        response.raise_for_status()
        return parse_current_metadata(response.text, baseline)


def _hidden_value(page: str, element_id: str) -> str:
    pattern = (
        rf'<input\b(?=[^>]*\bid=["\']{re.escape(element_id)}["\'])'
        r'(?=[^>]*\bvalue=["\']([^"\']*)["\'])[^>]*>'
    )
    match = re.search(pattern, page, flags=re.IGNORECASE)
    return html.unescape(match.group(1)).strip() if match else ""


def _compact_date(value: str) -> str:
    return "".join(part.zfill(2) for part in value.split("."))


def parse_current_metadata(page: str, baseline: dict) -> dict:
    """공개 최신본 페이지에서 비교에 필요한 식별자와 시행일만 읽는다."""
    is_law = baseline["kind"] == "law"
    version_field = "mst" if is_law else "rule_serial"
    version = _hidden_value(page, "lsiSeq" if is_law else "admRulSeq")
    actual_name = _hidden_value(page, "lsNm" if is_law else "admNm")
    if not version or actual_name != baseline["name"]:
        raise RuntimeError(f"최신본 페이지 확인 실패: {baseline['name']}")

    effective_match = re.search(r"\[시행\s+(\d{4}\.\s*\d{1,2}\.\s*\d{1,2})\.\]", page)
    effective_date = (
        _compact_date(re.sub(r"\s+", "", effective_match.group(1))) if effective_match else ""
    )
    return {
        "key": baseline["key"],
        "kind": baseline["kind"],
        "name": actual_name,
        version_field: version,
        "effective_date": effective_date,
    }


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


def detect_changes(client: PublicLawClient, law_dir: Path = LAW_DIR) -> list[LawChange]:
    """추적 중인 법령·행정규칙의 공개 최신본 버전을 저장된 기준값과 비교한다."""
    manifest = yaml.safe_load((law_dir / "manifest.yaml").read_text(encoding="utf-8"))
    changes: list[LawChange] = []
    tracked = [item for item in manifest["documents"] if item["kind"] in {"law", "admin_rule"}]
    for saved in tracked:
        current = client.current_metadata(saved)
        if _version(saved) == _version(current):
            continue
        changes.append(
            LawChange(
                key=saved["key"],
                name=saved["name"],
                kind=saved["kind"],
                previous_version=_version(saved),
                current_version=_version(current),
                previous_effective_date=str(saved.get("effective_date") or ""),
                current_effective_date=str(current.get("effective_date") or ""),
                version_changed=True,
                source_changed=False,
                tracked_units_changed=False,
            )
        )
    return changes


def discord_message(changes: list[LawChange], run_url: str | None = None) -> str:
    lines = [f"⚖️ 추적 법령 변경 감지: {len(changes)}건"]
    for change in changes:
        impact = "사용 조문 변경" if change.tracked_units_changed else "법령 버전 변경"
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
    changes = detect_changes(PublicLawClient())
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
