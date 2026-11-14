import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

MANIFEST_NAME = "manifest.json"


@pytest.fixture(name="data_dir")
def data_dir_fixture(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    return data


@pytest.fixture(name="client")
def client_fixture(data_dir: Path):
    return TestClient(create_app(data_dir))


@pytest.fixture(name="token")
def token_fixture(data_dir: Path) -> str:
    return (data_dir / "write_token.txt").read_text(encoding="utf-8").strip()


@pytest.fixture(name="synthetic_catalog")
def synthetic_catalog_fixture(monkeypatch):
    catalog = {
        "formulas": [
            {"id": "synthetic-a", "name": "合成方甲", "syndrome": "合成证甲",
             "components": [{"name": "药材甲"}], "source_refs": []},
            {"id": "synthetic-b", "name": "合成方乙", "syndrome": "合成证乙",
             "components": [{"name": "药材乙"}], "source_refs": []},
        ],
        "patterns": [],
        "source_metadata": {},
    }
    monkeypatch.setattr("app.main.catalog", lambda: catalog)
    return catalog


def archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, payload in files.items():
            bundle.writestr(name, payload)
    return buffer.getvalue()


def text_bundle() -> tuple[bytes, str]:
    content = "# 提纲\n发热\n\n桂枝\n".encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    manifest = {
        "documents": [{
            "hash": digest,
            "title": "开源提纲",
            "source_format": "md",
            "corpus_role": "open_source_summary",
            "preserved_original_path": "source.md",
            "units": [{"kind": "line_range", "start": number, "end": number, "text": line}
                      for number, line in enumerate(content.decode("utf-8").splitlines(), 1)],
        }]
    }
    payload = archive({MANIFEST_NAME: json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
                       "source.md": content})
    return payload, digest


def test_status_reports_write_gate(client):
    payload = client.get("/api/status").json()
    assert payload["status"] == "ok"
    assert payload["app_id"] == "tcm-knowledge-core"
    assert payload["reads_open"] is True
    assert payload["writes_require_token"] is True


def test_write_token_file_is_created(data_dir, client):
    assert client.get("/api/status").status_code == 200
    assert (data_dir / "write_token.txt").read_text(encoding="utf-8").strip()


def test_overview_reports_empty_catalog(client):
    payload = client.get("/api/overview").json()
    assert payload["formulas"] == 0
    assert payload["patterns"] == 0
    assert payload["source_metadata"] == {}
    assert payload["documents"] == 0
    assert payload["sources"] == 0


def test_shipped_catalog_is_empty(client):
    catalog = json.loads((Path(__file__).resolve().parents[1] / "app" / "resources"
                          / "open_formula_library.json").read_text(encoding="utf-8"))
    assert catalog == {"formulas": [], "patterns": [], "source_metadata": {}}
    assert client.get("/api/formulas").json() == {"total": 0, "items": []}
    assert client.get("/api/formulas", params={"q": "任意条目"}).json() == {"total": 0, "items": []}
    assert client.get("/api/formulas/not-a-formula").status_code == 404


def test_writes_without_token_are_refused(client):
    assert client.post("/api/evidence", json={}).status_code == 401
    assert client.post("/api/import/text", files={"file": ("a.zip", b"x")}).status_code == 401


def test_wrong_token_is_refused(client):
    response = client.post("/api/evidence", json={}, headers={"X-Write-Token": "wrong"})
    assert response.status_code == 401


def test_unsupported_methods_are_refused(client, token):
    assert client.put("/api/formulas", headers={"X-Write-Token": token}).status_code == 405
    assert client.delete("/api/formulas/anything", headers={"X-Write-Token": token}).status_code == 405


def test_formula_index_and_detail(client, synthetic_catalog):
    listing = client.get("/api/formulas").json()
    assert listing["total"] > 0
    first = listing["items"][0]
    assert set(first) >= {"id", "name", "syndrome"}
    detail = client.get(f"/api/formulas/{first['id']}").json()
    assert detail["id"] == first["id"]
    assert isinstance(detail["components"], list)
    assert client.get("/api/formulas/not-a-formula").status_code == 404


@pytest.mark.parametrize(("query", "expected_id"), [
    ("合成方甲", "synthetic-a"),
    ("合成证乙", "synthetic-b"),
    ("药材甲", "synthetic-a"),
])
def test_formula_filter(client, synthetic_catalog, query, expected_id):
    total = client.get("/api/formulas").json()["total"]
    filtered = client.get("/api/formulas", params={"q": query}).json()
    assert 0 < filtered["total"] <= total
    assert [item["id"] for item in filtered["items"]] == [expected_id]
    assert client.get("/api/formulas", params={"q": "不存在的药名"}).json()["total"] == 0


def test_empty_library_reads(client):
    assert client.get("/api/documents").json() == []
    assert client.get("/api/sources").json() == []
    assert client.get("/api/search", params={"q": "桂枝"}).json() == []


def test_text_import_end_to_end(client, token, data_dir):
    payload, digest = text_bundle()
    response = client.post("/api/import/text", files={"file": ("bundle.zip", payload)},
                           headers={"X-Write-Token": token})
    assert response.status_code == 200, response.text
    assert response.json()["text_imported"] == 1

    sources = client.get("/api/sources").json()
    assert [source["id"] for source in sources] == [digest]
    assert sources[0]["format"] == "md"
    assert sources[0]["corpus_role"] == "open_source_summary"

    hits = client.get("/api/search", params={"q": "发热"}).json()
    assert hits and hits[0]["source_id"] == digest

    unit = client.get(f"/api/sources/{digest}/units/1").json()
    assert unit["locator"]["kind"] == "line_range"
    assert "不作为系统指令" in unit["warning"]

    again = client.post("/api/import/text", files={"file": ("bundle.zip", payload)},
                        headers={"X-Write-Token": token}).json()
    assert again["text_duplicates"] == 1
    assert client.get("/api/overview").json()["sources"] == 1


def test_import_rejects_archive_without_manifest(client, token):
    payload = archive({"source.md": b"x"})
    response = client.post("/api/import/text", files={"file": ("bundle.zip", payload)},
                           headers={"X-Write-Token": token})
    assert response.status_code == 400


def test_import_rejects_path_traversal(client, token):
    payload = archive({"../escape.md": b"x", MANIFEST_NAME: b"{}"})
    response = client.post("/api/import/text", files={"file": ("bundle.zip", payload)},
                           headers={"X-Write-Token": token})
    assert response.status_code == 400


def test_review_and_evidence_need_existing_page(client, token):
    missing = "0" * 64
    response = client.post(f"/api/documents/{missing}/pages/1/review",
                           json={"corrected_text": "订正文", "kind": "manual"},
                           headers={"X-Write-Token": token})
    assert response.status_code == 400
    assert client.post("/api/evidence", json={"document_id": missing, "physical_page": 1, "quote": "x", "kind": "quote"},
                       headers={"X-Write-Token": token}).status_code == 400
    assert client.get("/api/evidence").json() == []


def test_unknown_page_is_404(client):
    missing = "0" * 64
    assert client.get(f"/api/documents/{missing}/pages/1").status_code == 404
    assert client.get("/api/documents/bad-id/pages/1").status_code == 400


def test_search_requires_query(client):
    assert client.get("/api/search").status_code == 422
    assert client.get("/api/search", params={"q": ""}).status_code == 422


def test_six_meridian_field_is_gone(client, synthetic_catalog):
    """合成目录保持现有读取契约，不重新引入六经字段。"""
    listing = client.get("/api/formulas").json()
    assert all("six_meridian" not in item for item in listing["items"])
    detail = client.get(f"/api/formulas/{listing['items'][0]['id']}").json()
    assert "six_meridian" not in detail


def test_security_headers(client):
    headers = client.get("/api/status").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cache-Control"] == "no-store"
