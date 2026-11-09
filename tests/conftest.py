from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.domain.facts import Fact, FactStatus
from app.rules.loader import load_kb

DATA = Path(__file__).resolve().parents[1] / "data" / "sample"
REAL = Path(__file__).resolve().parents[1] / "data" / "real"
AS_OF = date(2026, 11, 8)
_T0 = datetime(2026, 11, 8, tzinfo=UTC)


def F(key, value, status=FactStatus.CLAIMED, t: int = 0, ref: str = "") -> Fact:  # noqa: N802
    return Fact(
        key=key, value=value, status=status, source_ref=ref, recorded_at=_T0 + timedelta(seconds=t)
    )


def facts(**kv) -> dict[str, Fact]:
    """facts(material="PP", oil_content_pct=(3, "EVIDENCED"))"""
    out = {}
    for k, v in kv.items():
        if isinstance(v, tuple):
            out[k] = F(k, v[0], FactStatus(v[1]))
        else:
            out[k] = F(k, v)
    return out


CLEAN = dict(pcb_related=False, hazardous_residue=False, toxic_chemical=False)


@pytest.fixture(scope="session")
def kb():
    return load_kb(DATA)


@pytest.fixture(scope="session")
def real_kb():
    return load_kb(REAL)


@pytest.fixture(scope="session", autouse=True)
def _drop_test_databases():
    """TEST_DATABASE_URL(PostgreSQL)로 돌릴 때 만든 테스트 DB를 끝나고 지운다."""
    from tests.dbutil import drop_all

    yield
    drop_all()
