import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import library_signs

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "knowledge" / "knowledge.sqlite3"


@pytest.mark.skipif(not DB.is_file(), reason="Original corpus is supplied locally")
def test_manifest_and_evidence_source_integrity():
    manifest = json.loads((ROOT / "library_evidence" / "sign_terms_manifest.json").read_text(encoding="utf-8"))
    detail = manifest["files"]["sign_terms.json"]
    payload = (ROOT / "library_evidence" / "sign_terms.json").read_bytes()
    assert len(payload) == detail["bytes"]
    assert hashlib.sha256(payload).hexdigest() == detail["sha256"]
    assert manifest["counts"]["terms"] == 129
    assert manifest["counts"]["with_evidence"] == 115
    assert manifest["counts"]["mentions"] == 19224
    data = json.loads(payload)
    connection = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    pages = {
        (row["document_id"], f"physical_page:{row['physical_page']}"): row["raw_text"] or ""
        for row in connection.execute("SELECT document_id,physical_page,raw_text FROM pages")
    }
    units = {
        (row["source_id"], row["locator"]): row["raw_text"] or ""
        for row in connection.execute("SELECT source_id,locator,raw_text FROM source_units")
    }
    checked = 0
    for term in data["terms"]:
        for evidence in term["evidence"]:
            key = (evidence["source_id"], evidence["locator"])
            text = pages.get(key) if evidence["source_kind"] == "page" else units.get(key)
            assert text is not None
            assert evidence["quote"] in text
            assert hashlib.sha256(evidence["quote"].encode("utf-8")).hexdigest() == evidence["sha256"]
            checked += 1
    assert checked > 0


def test_known_terms_and_search():
    summary = library_signs.summary()
    assert summary["terms"] == 129
    assert summary["with_evidence"] == 115
    term = library_signs.get_term("quan_shen_pa_leng")
    assert term["term"]
    assert term["mention_count"] > 0
    assert term["evidence"]
    assert library_signs.get_term("不存在") is None
    found = library_signs.search("怕冷", limit=20)
    assert found["items"]


@pytest.fixture
def signs_client(tmp_path):
    from app.main import create_app
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        client.get("/api/session")
        yield client


def test_library_sign_api_routes(signs_client):
    summary = signs_client.get("/api/library/signs/summary")
    assert summary.status_code == 200
    assert summary.json()["terms"] == 129
    search = signs_client.get("/api/library/signs", params={"q": "怕冷", "limit": 5})
    assert search.status_code == 200 and search.json()["items"]
    detail = signs_client.get("/api/library/signs/quan_shen_pa_leng")
    assert detail.status_code == 200
    assert detail.json()["evidence"]
    assert signs_client.get("/api/library/signs/不存在").status_code == 404
