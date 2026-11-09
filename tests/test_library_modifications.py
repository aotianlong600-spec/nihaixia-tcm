import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import library_modifications

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "knowledge" / "knowledge.sqlite3"


@pytest.mark.skipif(not DB.is_file(), reason="Original corpus is supplied locally")
def test_manifest_and_rule_source_integrity():
    manifest = json.loads((ROOT / "library_evidence" / "modifications_manifest.json").read_text(encoding="utf-8"))
    detail = manifest["files"]["modifications.json"]
    payload = (ROOT / "library_evidence" / "modifications.json").read_bytes()
    assert len(payload) == detail["bytes"]
    assert hashlib.sha256(payload).hexdigest() == detail["sha256"]
    assert manifest["counts"]["rules"] == 21
    assert manifest["counts"]["formulas"] == 8
    data = json.loads(payload)
    connection = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    pages = {
        (row["document_id"], f"physical_page:{row['physical_page']}"): row["raw_text"] or ""
        for row in connection.execute("SELECT document_id,physical_page,raw_text FROM pages")
    }
    for rule in data["rules"]:
        source = rule["source"]
        text = pages[(source["document_id"], source["locator"])]
        assert source["quote"] in text
        assert hashlib.sha256(source["quote"].encode("utf-8")).hexdigest() == source["quote_sha256"]
        assert rule["condition"].startswith("若")
        assert rule["actions"]


def test_known_xiaochaihu_rules():
    summary = library_modifications.summary()
    assert summary["rules"] == 21
    rules = library_modifications.for_formula("xiaochaihu_tang")
    assert rules
    conditions = {rule["condition"] for rule in rules}
    assert any("渴" in condition for condition in conditions)
    thirst = next(rule for rule in rules if "渴" in rule["condition"])
    actions = {(action["action"], action["herb"]) for action in thirst["actions"]}
    assert ("remove", "半夏") in actions
    assert ("add", "人参") in actions
    found = library_modifications.search("柴胡", limit=20)
    assert found["items"]


def test_rules_are_verified_against_the_current_library_page():
    formula_id = "xiao_qinglong_tang"
    rules = library_modifications.for_formula(formula_id)
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE documents(id TEXT PRIMARY KEY,title TEXT)")
    conn.execute("CREATE TABLE pages(document_id TEXT,physical_page INTEGER,raw_text TEXT,corrected_text TEXT,ocr_text TEXT)")
    pages = {}
    for rule in rules:
        source = rule["source"]
        page = int(source["locator"].split(":")[1])
        conn.execute("INSERT OR IGNORE INTO documents VALUES(?,?)", (source["document_id"], source["source_title"]))
        pages.setdefault((source["document_id"], page), []).append(source["quote"])
    for (document_id, page), quotes in pages.items():
        conn.execute("INSERT INTO pages VALUES(?,?,?,?,?)", (document_id, page, "\n".join(quotes), None, None))
    verified, rejected = library_modifications.verified_for_formula(conn, formula_id)
    assert len(verified) == len(rules) and not rejected
    assert all(rule["source"]["verification"] == library_modifications.VERIFIED for rule in verified)
    source = rules[0]["source"]
    page = int(source["locator"].split(":")[1])
    conn.execute("UPDATE pages SET raw_text='removed' WHERE document_id=? AND physical_page=?", (source["document_id"], page))
    verified, rejected = library_modifications.verified_for_formula(conn, formula_id)
    missing_page = sum(rule["source"]["locator"] == source["locator"] for rule in rules)
    assert len(verified) == len(rules) - missing_page
    assert len(rejected) == missing_page
    assert all(item["reason"] == "quote_not_on_source_page" for item in rejected)


@pytest.fixture
def modifications_client(tmp_path):
    from app.main import create_app
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        client.get("/api/session")
        yield client


def test_library_modification_api_routes(modifications_client):
    summary = modifications_client.get("/api/library/modifications/summary")
    assert summary.status_code == 200
    assert summary.json()["rules"] == 21
    rules = modifications_client.get("/api/library/modifications", params={"formula_id": "xiaochaihu_tang"})
    assert rules.status_code == 200 and rules.json()["items"]
    formula_rules = modifications_client.get("/api/library/modifications/formulas/xiaochaihu_tang")
    assert formula_rules.status_code == 200 and formula_rules.json()["items"]
    detail = modifications_client.get("/api/library/evidence/formulas/xiaochaihu_tang")
    assert detail.status_code == 200
    assert detail.json()["modifications"]
