"""웹 세션 검사는 실제 문진 저장소를 건드리지 않는다."""
import pytest


@pytest.fixture(autouse=True)
def isolated_web_state(monkeypatch, tmp_path):
    import wastecalc.web.app as web

    monkeypatch.setattr(web, "SESSION_DB", tmp_path / "sessions.sqlite3", raising=False)
    monkeypatch.setattr(web, "SESSIONS", {})
