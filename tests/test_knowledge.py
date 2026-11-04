import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pypdfium2
import pytest

from app import knowledge


@pytest.fixture
def store(tmp_path):
    conn = sqlite3.connect(tmp_path / "clinical.sqlite3")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    knowledge.init_knowledge(conn, tmp_path / "data")
    yield conn, tmp_path / "data"
    conn.close()


def make_audit(tmp_path, texts=("太阳病，桂枝湯主之。生薑三兩。", "第二页原文。"), filename="伤寒论.pdf"):
    source = tmp_path / filename
    with pypdfium2.PdfDocument.new() as pdf:
        for _ in texts:
            pdf.new_page(595, 842)
        pdf.save(source)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    pages = tmp_path / "pages.json"
    pages.write_text(json.dumps([{"physical_page": i, "text": text} for i, text in enumerate(texts, 1)], ensure_ascii=False), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"method": "test original extraction", "documents": [{
        "filename": filename, "preserved_copy_path": str(source), "pages_json_path": str(pages),
        "source_sha256": sha, "copy_sha256": sha, "physical_pages": len(texts),
        "extracted_pages": len(texts), "empty_text_pages": [], "low_text_pages_under_50": [], "extraction_errors": [],
    }]}, ensure_ascii=False), encoding="utf-8")
    return manifest, source, sha


def imported(store, tmp_path, **kwargs):
    manifest, source, sha = make_audit(tmp_path, **kwargs)
    result = knowledge.import_audit(*store, manifest)
    return sha, source, result


def review(conn, sha, corrected_text="太阳病，桂枝汤主之。生姜三两。"):
    return knowledge.review_page(conn, sha, 1, {"corrected_text": corrected_text, "kind": "classic", "reviewer": "审核医师", "note": "逐字对照", "printed_page": "I"})


def test_hash_identity_deduplicates_and_preserves_registered_original(store, tmp_path):
    sha, source, result = imported(store, tmp_path)
    assert result["imported"] == 1
    assert result["physical_pages"] == 2
    again = knowledge.import_pdf(*store, source, title="不能覆盖初次登记")
    assert again["duplicate"] is True
    docs = knowledge.list_documents(store[0])
    assert len(docs) == 1
    assert docs[0]["id"] == sha == docs[0]["sha256"]
    assert docs[0]["reviewed_pages"] == 0
    assert docs[0]["status"] == "pending"
    assert knowledge.document_path(*store, sha).read_bytes() == source.read_bytes()
    assert knowledge.document_path(*store, sha).name == sha + ".pdf"
    assert str(tmp_path) not in json.dumps(docs)


def test_audit_import_is_pending_and_preserves_raw_text(store, tmp_path):
    sha, _, _ = imported(store, tmp_path)
    page = knowledge.get_page(store[0], sha, 1)
    assert page["raw_text"] == "太阳病，桂枝湯主之。生薑三兩。"
    assert page["corrected_text"] is None
    assert page["review_status"] == "pending"
    assert page["printed_page"] is None
    assert knowledge.import_audit(*store, tmp_path / "manifest.json")["duplicates"] == 1


@pytest.mark.parametrize("query", ["桂枝", "桂枝汤", "桂枝湯", "生姜", "生薑", "（桂枝汤）", "桂 枝 汤"])
def test_chinese_short_search_normalizes_only_derived_text(store, tmp_path, query):
    sha, _, _ = imported(store, tmp_path)
    hits = knowledge.search(store[0], query, document_id=sha)
    assert len(hits) == 1
    assert hits[0]["physical_page"] == 1
    assert "桂枝湯" in hits[0]["snippet"]
    assert hits[0]["review_status"] == "pending"
    assert hits[0]["pdf_url"] == f"/api/documents/{sha}/pdf#page=1"


@pytest.mark.parametrize("query", ["", "()[]，%_\"'", "' OR 1=1 --"])
def test_punctuation_and_sql_are_plain_search_input(store, tmp_path, query):
    imported(store, tmp_path)
    assert knowledge.search(store[0], query) == []


def test_search_rejects_unbounded_inputs(store, tmp_path):
    imported(store, tmp_path)
    for kwargs in ({"query": "桂" * 257}, {"query": "桂枝", "limit": 0}, {"query": "桂枝", "limit": 101}, {"query": 1}, {"query": "桂枝", "document_id": "../escape"}):
        with pytest.raises(ValueError):
            knowledge.search(store[0], **kwargs)


def test_get_page_bounds_and_identifiers(store, tmp_path):
    sha, _, _ = imported(store, tmp_path)
    for page in (0, -1, 3, 10 ** 100, -(10 ** 100)):
        assert knowledge.get_page(store[0], sha, page) is None
    assert knowledge.get_page(store[0], "a" * 64, 1) is None
    for document_id, page in (("../escape", 1), (sha, "1"), (sha, True)):
        with pytest.raises(ValueError):
            knowledge.get_page(store[0], document_id, page)


def test_evidence_requires_review_and_exact_contiguous_quote(store, tmp_path):
    sha, _, _ = imported(store, tmp_path)
    payload = {"document_id": sha, "physical_page": 1, "quote": "桂枝汤主之", "kind": "classic", "reviewer": "审核医师"}
    with pytest.raises(ValueError):
        knowledge.create_evidence(store[0], payload)
    review(store[0], sha)
    for quote in ("编造的引文", "桂枝汤生姜", "", " "):
        with pytest.raises(ValueError):
            knowledge.create_evidence(store[0], {**payload, "quote": quote})
    evidence = knowledge.create_evidence(store[0], payload)
    assert evidence["quote"] == "桂枝汤主之"
    assert evidence["sha256"] == sha
    assert evidence["source_type"] == "corrected"
    assert evidence["start"] == 4
    assert evidence["end"] == 9
    assert evidence["raw_text"] == "太阳病，桂枝湯主之。生薑三兩。"
    assert evidence["corrected_text"] == "太阳病，桂枝汤主之。生姜三两。"
    assert evidence["physical_page"] == 1
    assert evidence["printed_page"] == "I"
    assert knowledge.get_evidence(store[0], evidence["id"]) == evidence
    assert knowledge.list_evidence(store[0]) == [evidence]
    assert knowledge.get_evidence(store[0], "missing") is None
    review(store[0], sha, "另一版订正文。")
    assert knowledge.get_evidence(store[0], evidence["id"]) == evidence


def test_review_keeps_raw_and_updates_search_and_document_counts(store, tmp_path):
    sha, _, _ = imported(store, tmp_path)
    page = review(store[0], sha, "确证订正文本，麻黄汤。")
    assert page["raw_text"] == "太阳病，桂枝湯主之。生薑三兩。"
    assert page["review_status"] == "verified"
    assert page["kind"] == "classic"
    assert knowledge.list_documents(store[0])[0]["reviewed_pages"] == 1
    assert knowledge.search(store[0], "麻黄")[0]["physical_page"] == 1
    assert knowledge.search(store[0], "桂枝") == []
    with pytest.raises(ValueError):
        review(store[0], sha, "")
    with pytest.raises(ValueError):
        knowledge.review_page(store[0], sha, 3, {"corrected_text": "test", "kind": "classic", "reviewer": "医师", "note": "对照"})


def test_reviewed_unchanged_page_evidence_uses_raw_source(store, tmp_path):
    sha, _, _ = imported(store, tmp_path)
    review(store[0], sha, "太阳病，桂枝湯主之。生薑三兩。")
    item = knowledge.create_evidence(store[0], {"document_id": sha, "physical_page": 1, "quote": "桂枝湯", "kind": "classic", "reviewer": "医师"})
    assert item["source_type"] == "raw"


def test_mutations_belong_to_caller_transaction(store, tmp_path):
    conn, data_dir = store
    conn.commit()
    sha, _, _ = imported(store, tmp_path)
    conn.rollback()
    assert knowledge.list_documents(conn) == []
    knowledge.import_audit(conn, data_dir, tmp_path / "manifest.json")
    conn.commit()
    review(conn, sha)
    conn.rollback()
    assert knowledge.get_page(conn, sha, 1)["review_status"] == "pending"
    review(conn, sha)
    conn.commit()
    knowledge.create_evidence(conn, {"document_id": sha, "physical_page": 1, "quote": "桂枝汤", "kind": "classic", "reviewer": "医师"})
    conn.rollback()
    assert knowledge.list_evidence(conn) == []


@pytest.mark.parametrize("change", ["hash", "page_gap", "duplicate_page", "page_count", "text_type", "page_type"])
def test_audit_rejects_corruption_before_importing(store, tmp_path, change):
    manifest, _, _ = make_audit(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    doc = data["documents"][0]
    pages_path = Path(doc["pages_json_path"])
    pages = json.loads(pages_path.read_text(encoding="utf-8"))
    if change == "hash":
        doc["source_sha256"] = "0" * 64
    elif change == "page_gap":
        pages[1]["physical_page"] = 3
    elif change == "duplicate_page":
        pages[1]["physical_page"] = 1
    elif change == "page_count":
        doc["physical_pages"] = 3
    elif change == "text_type":
        pages[0]["text"] = None
    else:
        pages[0] = 1
    manifest.write_text(json.dumps(data), encoding="utf-8")
    pages_path.write_text(json.dumps(pages), encoding="utf-8")
    with pytest.raises(ValueError):
        knowledge.import_audit(*store, manifest)
    assert knowledge.list_documents(store[0]) == []


def test_known_audit_issues_remain_warnings_not_corrections(store, tmp_path):
    sha, _, _ = imported(store, tmp_path, texts=["正文桂枝汤"] * 19)
    assert "顺序" in knowledge.get_page(store[0], sha, 15)["warning"]
    assert "顺序" in knowledge.get_page(store[0], sha, 16)["warning"]
    assert knowledge.get_page(store[0], sha, 15)["corrected_text"] is None


def test_unconfirmed_author_and_duplicate_fragments_are_flagged(store, tmp_path):
    inner = tmp_path / "inner"
    inner.mkdir()
    nei_sha, _, _ = imported(store, inner, filename="黄帝内经.pdf")
    doc = next(item for item in knowledge.list_documents(store[0]) if item["id"] == nei_sha)
    assert doc["author_status"] == "unconfirmed"
    assert "归属" in doc["warning"]
    outer = tmp_path / "outer"
    outer.mkdir()
    jin_sha, _, _ = imported(store, outer, filename="金匮要略.pdf", texts=["正文"] * 12)
    assert "重复" in knowledge.get_page(store[0], jin_sha, 12)["warning"]


def test_new_pdf_import_marks_image_only_pages_pending(store, tmp_path):
    _, source, sha = make_audit(tmp_path)
    item = knowledge.import_pdf(*store, source)
    assert item["id"] == sha
    assert item["duplicate"] is False
    page = knowledge.get_page(store[0], sha, 1)
    assert page["review_status"] == "pending"
    assert page["corrected_text"] is None
    assert "图像" in page["warning"]


def test_pdf_path_rejects_unregistered_ids_and_tampering(store, tmp_path):
    sha, _, _ = imported(store, tmp_path)
    for bad in ("../../outside.pdf", "a" * 64):
        with pytest.raises(ValueError):
            knowledge.document_path(*store, bad)
    registered = knowledge.document_path(*store, sha)
    registered.write_bytes(b"replaced original")
    with pytest.raises(ValueError):
        knowledge.document_path(*store, sha)


def test_invalid_pdf_is_rejected_without_registering_document(store, tmp_path):
    source = tmp_path / "bad.pdf"
    source.write_bytes(b"not a pdf")
    with pytest.raises(ValueError):
        knowledge.import_pdf(*store, source)
    assert knowledge.list_documents(store[0]) == []


def test_cli_reimports_without_duplicating_pages(tmp_path):
    manifest, _, _ = make_audit(tmp_path)
    script = Path(__file__).resolve().parents[1] / "scripts" / "import_audit.py"
    command = [sys.executable, str(script), str(manifest), "--data-dir", str(tmp_path / "runtime")]
    first = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["imported"] == 1
    again = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)["duplicates"] == 1
    with sqlite3.connect(tmp_path / "runtime" / "clinical.sqlite3") as conn:
        assert conn.execute("SELECT count(*) FROM pages").fetchone()[0] == 2
