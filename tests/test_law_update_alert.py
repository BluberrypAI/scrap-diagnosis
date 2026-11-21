import json

import httpx
import pytest

from tools import check_law_updates
from tools.check_law_updates import LawChange, compare_document, discord_message, report_payload


def meta(*, mst="100", effective="20260101"):
    return {
        "key": "ACT-WASTE",
        "kind": "law",
        "name": "폐기물관리법",
        "mst": mst,
        "effective_date": effective,
        "raw_sha256": "source-a",
    }


def body(*, source="source-a", text="제2조 내용"):
    return {
        "raw_sha256": source,
        "units": [{"id": "제2조", "title": "정의", "text": text}],
    }


def test_unchanged_document_returns_none():
    current = meta()
    assert compare_document(meta(), body()["units"], current, body()) is None


def test_version_change_is_reported_even_when_tracked_units_are_same():
    change = compare_document(meta(), body()["units"], meta(mst="101"), body(source="source-b"))

    assert change is not None
    assert change.version_changed is True
    assert change.source_changed is True
    assert change.tracked_units_changed is False


def test_tracked_unit_change_is_marked_as_impacting_used_content():
    change = compare_document(meta(), body()["units"], meta(), body(text="바뀐 제2조 내용"))

    assert change is not None
    assert change.version_changed is False
    assert change.tracked_units_changed is True


def test_discord_message_and_json_report_do_not_contain_secrets():
    change = LawChange(
        key="ACT-WASTE",
        name="폐기물관리법",
        kind="law",
        previous_version="100",
        current_version="101",
        previous_effective_date="20260101",
        current_effective_date="20270101",
        version_changed=True,
        source_changed=True,
        tracked_units_changed=False,
    )

    message = discord_message([change], "https://github.test/actions/1")
    payload = report_payload([change])

    assert "폐기물관리법" in message
    assert "자동 반영하지 않았습니다" in message
    assert len(message) <= 2000
    assert json.loads(json.dumps(payload))["changed"] is True
    assert "webhook" not in json.dumps(payload).lower()


def test_discord_failure_does_not_expose_webhook(monkeypatch):
    webhook = "https://discord.test/api/webhooks/secret-token"

    def fail(*args, **kwargs):
        request = httpx.Request("POST", webhook)
        raise httpx.ConnectError("failed", request=request)

    monkeypatch.setattr(check_law_updates.httpx, "post", fail)

    with pytest.raises(RuntimeError) as raised:
        check_law_updates.notify_discord(webhook, "message")

    assert "secret-token" not in str(raised.value)
