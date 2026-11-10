from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(name="client")
def client_fixture(tmp_path: Path):
    return TestClient(create_app(tmp_path / "data"))


def test_status_is_read_only(client):
    payload = client.get("/api/status").json()
    assert payload["status"] == "ok"
    assert payload["read_only"] is True
    assert payload["app_id"] == "tcm-knowledge-core"


def test_overview_reports_catalog(client):
    payload = client.get("/api/overview").json()
    assert payload["formulas"] > 0
    assert payload["patterns"] > 0
    assert payload["documents"] == 0
    assert payload["sources"] == 0


def test_writes_are_refused(client):
    assert client.post("/api/status").status_code == 405
    assert client.delete("/api/formulas/anything").status_code == 405


def test_formula_index_and_detail(client):
    listing = client.get("/api/formulas").json()
    assert listing["total"] > 0
    first = listing["items"][0]
    assert set(first) >= {"id", "name", "syndrome"}
    detail = client.get(f"/api/formulas/{first['id']}").json()
    assert detail["id"] == first["id"]
    assert isinstance(detail["components"], list)
    assert client.get("/api/formulas/not-a-formula").status_code == 404


def test_formula_filter_by_component(client):
    total = client.get("/api/formulas").json()["total"]
    filtered = client.get("/api/formulas", params={"q": "桂枝"}).json()
    assert 0 < filtered["total"] <= total
    assert client.get("/api/formulas", params={"q": "不存在的药名"}).json()["total"] == 0


def test_empty_library_reads(client):
    assert client.get("/api/documents").json() == []
    assert client.get("/api/sources").json() == []
    assert client.get("/api/search", params={"q": "桂枝"}).json() == []


def test_unknown_page_is_404(client):
    missing = "0" * 64
    assert client.get(f"/api/documents/{missing}/pages/1").status_code == 404
    assert client.get("/api/documents/bad-id/pages/1").status_code == 400


def test_search_requires_query(client):
    assert client.get("/api/search").status_code == 422
    assert client.get("/api/search", params={"q": ""}).status_code == 422


def test_security_headers(client):
    headers = client.get("/api/status").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cache-Control"] == "no-store"
