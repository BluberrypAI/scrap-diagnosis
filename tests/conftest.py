"""웹 세션 검사는 실제 문진 저장소를 건드리지 않는다.

법령 원문(sources/raw)은 용량 때문에 저장소에 넣지 않는다. 원문이 없으면 원문 대조 테스트는 건너뛴다
(원문을 받아 둔 로컬에서만 돈다 — rules/sources.yaml의 경로·해시로 같은 파일인지 확인).
"""
from pathlib import Path

import pytest

try:
    import fitz

    _fitz_open = fitz.open

    def _open_or_skip(path=None, *args, **kwargs):
        if isinstance(path, (str, Path)) and not Path(path).exists():
            pytest.skip(f"법령 원문 파일이 없음(저장소에 넣지 않음): {Path(path).name}")
        return _fitz_open(path, *args, **kwargs)

    fitz.open = _open_or_skip
except ImportError:  # pragma: no cover
    pass


@pytest.fixture(autouse=True)
def isolated_web_state(monkeypatch, tmp_path):
    import wastecalc.web.app as web

    monkeypatch.setattr(web, "SESSION_DB", tmp_path / "sessions.sqlite3", raising=False)
    monkeypatch.setattr(web, "SESSIONS", {})
