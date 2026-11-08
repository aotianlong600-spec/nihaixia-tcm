import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import library_evidence

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "knowledge" / "knowledge.sqlite3"


def test_manifest_hashes_and_counts_match_generated_files():
    manifest = json.loads((ROOT / "library_evidence" / "formula_mentions_manifest.json").read_text(encoding="utf-8"))
    detail = manifest["files"]["formula_mentions.json"]
    payload = (ROOT / "library_evidence" / "formula_mentions.json").read_bytes()
    assert len(payload) == detail["bytes"]
    assert hashlib.sha256(payload).hexdigest() == detail["sha256"]
    if DB.is_file():
        assert manifest["source"]["database_sha256"] == hashlib.sha256(DB.read_bytes()).hexdigest()
    assert manifest["counts"]["formulas"] == 314
    assert manifest["counts"]["formulas_with_evidence"] == 274
    assert manifest["counts"]["mentions"] == 8992
    assert manifest["counts"]["evidence"] == 3763


@pytest.mark.skipif(not DB.is_file(), reason="Original corpus is supplied locally")
def test_every_quote_is_an_exact_hash_checked_source_substring():
    data = json.loads((ROOT / "library_evidence" / "formula_mentions.json").read_text(encoding="utf-8"))
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
    for formula in data["formulas"]:
        for evidence in formula["evidence"]:
            key = (evidence["source_id"], evidence["locator"])
            text = pages.get(key) if evidence["source_kind"] == "page" else units.get(key)
            assert text is not None, (formula["formula_name"], key)
            assert evidence["quote"] in text, (formula["formula_name"], key)
            assert hashlib.sha256(evidence["quote"].encode("utf-8")).hexdigest() == evidence["quote_sha256"]
            checked += 1
    assert checked == data["counts"]["evidence"]


@pytest.mark.skipif(not DB.is_file(), reason="Original corpus is supplied locally")
def test_composition_manifest_and_source_integrity():
    manifest = json.loads((ROOT / "library_evidence" / "formula_compositions_manifest.json").read_text(encoding="utf-8"))
    detail = manifest["files"]["formula_compositions.json"]
    payload = (ROOT / "library_evidence" / "formula_compositions.json").read_bytes()
    assert len(payload) == detail["bytes"]
    assert hashlib.sha256(payload).hexdigest() == detail["sha256"]
    assert manifest["counts"]["formulas_with_compositions"] >= 150
    assert manifest["counts"]["versions"] >= 200
    data = json.loads(payload)
    connection = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    pages = {
        (row["document_id"], f"physical_page:{row['physical_page']}"): row["raw_text"] or ""
        for row in connection.execute("SELECT document_id,physical_page,raw_text FROM pages")
    }
    checked = 0
    for formula in data["formulas"]:
        for version in formula["versions"]:
            text = pages[(version["source_id"], version["locator"])]
            assert version["block"] in text
            assert hashlib.sha256(version["block"].encode("utf-8")).hexdigest() == version["block_sha256"]
            assert version["composition_text"] in text
            if version["preparation_text"]:
                assert version["preparation_text"] in text
            for component in version["components"]:
                assert component["herb_text"]
                assert component["herb_raw"] in version["block"]
                if component["dose_raw"]:
                    assert component["dose_raw"] in version["block"]
                assert component["missing_dose"] is (component["dose"] is None)
                if not component["missing_dose"]:
                    assert component["unit"] and component["dose_text"]
            checked += 1
    assert checked == data["counts"]["versions"]


def test_formula_lookup_and_search():
    summary = library_evidence.summary()
    assert summary["review_status"] == "library_source"
    assert summary["formulas"] == 314
    detail = library_evidence.get_formula("guizhi_tang")
    assert detail["formula"]["name"] == "桂枝汤"
    assert detail["mention_count"] > 0
    assert detail["evidence"]
    assert all(item["quote"] and item["locator"] for item in detail["evidence"])
    assert detail["compositions"]
    assert any(item["components"] for item in detail["compositions"])
    assert library_evidence.get_formula("missing") is None
    found = library_evidence.search("四逆汤", limit=5)
    assert found["items"]
    assert any(item["formula_name"] == "四逆汤" for item in found["items"])
    assert library_evidence.search("不存在的词")["items"] == []


@pytest.fixture
def library_client(tmp_path):
    from app.main import create_app
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        client.get("/api/session")
        yield client


def test_library_evidence_api_routes(library_client):
    summary = library_client.get("/api/library/evidence/summary")
    assert summary.status_code == 200
    assert summary.json()["formulas"] == 314
    detail = library_client.get("/api/library/evidence/formulas/guizhi_tang")
    assert detail.status_code == 200
    assert detail.json()["formula"]["name"] == "桂枝汤"
    assert detail.json()["evidence"]
    assert detail.json()["compositions"]
    assert library_client.get("/api/library/evidence/formulas/missing").status_code == 404
    search = library_client.get("/api/library/evidence/search", params={"q": "四逆汤", "limit": 5})
    assert search.status_code == 200
    assert search.json()["items"]
