"""개발자용 규칙 그래프 API(/dev/rules): 전체 구조 한 장, 소재별 흐름, prod 차단."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.dev_rules import build_graph, build_overview
from tests.api_support import build_app, fake_llm


def test_overview_has_common_stages_groups_and_law_items(real_kb):
    o = build_overview(real_kb)
    m = o.mermaid
    for node in ("S0", "S1", "S2", "GROUPS", "COMMONLAW", "L1", "L2", "L3", "DES", "GEN", "INT"):
        assert node in m, node
    assert o.stats["materials"] == len(real_kb.tables)
    assert o.nodes["G_sludge"].detail  # 소재 분류를 누르면 소재 목록
    assert any("S3-6" in d for d in o.nodes["L6"].detail)  # 법 조항을 누르면 원본 규칙
    assert "G_sludge -->" in m and "L1" in m  # 오니는 제1호로 이어진다


def test_table_graph_groups_generated_rules(real_kb):
    g = build_graph(real_kb, "pp")
    oil = next(r for b in g.bands for r in b.rules if r.source_rule == "S3-6-OIL-5PCT")
    assert len(oil.outcomes) > 1  # 번호만 다른 생성 규칙을 노드 하나로
    assert g.bands[0].label.startswith("①")


def test_dev_rules_api_and_prod_block(kb, tmp_path, monkeypatch):
    app = build_app(kb, tmp_path / "d.db", fake_llm())
    c = TestClient(app)
    assert c.get("/dev/rules/overview").status_code == 200
    assert c.get("/dev/rules/tables").json()
    assert c.get("/dev/rules/tables/nope").status_code == 404
    app.state.container.settings.app_env = "prod"
    r = c.get("/dev/rules/overview")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "ENDPOINT_DISABLED"
