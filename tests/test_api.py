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


def test_overview_reports_curated_brain_catalog(client):
    payload = client.get("/api/overview").json()
    assert payload["formulas"] >= 299
    assert payload["herbs"] > 0
    assert payload["documents"] == 0
    assert payload["sources"] == 0
    assert "acupuncture_summary" in payload
    assert "bencao_summary" in payload
    assert "neijing_summary" in payload


def test_formula_index_detail_and_filter(client):
    listing = client.get("/api/formulas", params={"page_size": 20}).json()
    assert listing["total"] >= 299
    assert len(listing["items"]) == 20
    first = listing["items"][0]
    assert set(first) >= {"id", "name", "six_meridian", "book"}

    detail = client.get(f"/api/formulas/{first['id']}").json()
    assert detail["id"] == first["id"]
    assert isinstance(detail["ingredients"], list)

    guizhi = client.get("/api/formulas", params={"q": "桂枝汤"}).json()
    assert guizhi["total"] >= 1
    assert any("桂枝汤" in item["name"] for item in guizhi["items"])
    assert client.get("/api/formulas", params={"q": "不存在的虚构方名xyz"}).json()["total"] == 0
    assert client.get("/api/formulas/not-a-formula").status_code == 404


def test_stage5_library_and_frontend_shell(client):
    lib = client.get("/api/library/books").json()
    assert lib["total"] == 17

    composed = client.get("/api/stage5/compose", params={"q": "发热 恶风 自汗"}).json()
    assert composed["candidate_formulas"]

    grounded = client.get("/api/stage5/ground", params={"q": "少阳 往来寒热"}).json()
    assert grounded["verified_citations"]

    html = client.get("/")
    assert html.status_code == 200
    assert "倪师AI开方" in html.text
    assert 'src="/ni_ai.js"' in html.text

    js = client.get("/ni_ai.js")
    assert js.status_code == 200
    assert "/api/ai/chat/stream" in js.text


def test_writes_without_token_are_refused(client):
    assert client.post("/api/evidence", json={}).status_code == 401
    assert client.post("/api/import/text", files={"file": ("a.zip", b"x")}).status_code == 401


def test_wrong_token_is_refused(client):
    response = client.post("/api/evidence", json={}, headers={"X-Write-Token": "wrong"})
    assert response.status_code == 401


def test_unsupported_methods_are_refused(client, token):
    assert client.put("/api/formulas", headers={"X-Write-Token": token}).status_code == 405
    assert client.delete("/api/formulas/anything", headers={"X-Write-Token": token}).status_code == 405


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


def test_security_headers(client):
    headers = client.get("/api/status").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cache-Control"] == "no-store"


def test_bencao_entries_include_detail_batch_and_frontend_stream(client):
    res = client.get("/api/bencao/entries", params={"include_detail": "true", "page_size": 50})
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 385
    assert len(payload["items"]) == 50
    first = payload["items"][0]
    for field in (
        "classic_original",
        "properties",
        "historical_commentaries",
        "ni_haixia_annotations",
        "processing_and_compatibility",
        "formula_usages",
    ):
        assert field in first

    from app.static_dispatch import dispatch_request

    static_env = json.loads(
        dispatch_request("/api/bencao/entries?include_detail=true&page_size=50", "GET", "")
    )
    assert static_env["status"] == 200
    assert len(static_env["body"]["items"]) == 50
    assert "classic_original" in static_env["body"]["items"][0]

    html_src = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
    bencao_js = (Path(__file__).resolve().parents[1] / "web" / "bencao.js").read_text(encoding="utf-8")
    assert 'id="bc-continuous-mode"' in html_src
    assert "renderHerbBookEntryHtml" in bencao_js
    assert "renderContinuousCatalogStream" in bencao_js
