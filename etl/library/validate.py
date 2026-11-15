"""Strict provenance, non-fabrication, and referential integrity validator for Stage 5 Library & Network."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "brain_data"
LIB_SOURCES_DIR = ROOT / "sources" / "library"


def validate_all() -> dict[str, Any]:
    errors: list[str] = []

    catalog_path = DATA_DIR / "library" / "catalog.json"
    cross_path = DATA_DIR / "library" / "cross_links.json"
    syndromes_path = DATA_DIR / "relations" / "syndrome_clusters.json"
    network_path = DATA_DIR / "relations" / "unified_network.json"
    for p in (catalog_path, cross_path, syndromes_path, network_path):
        if not p.exists():
            errors.append(f"Missing required artifact: {p}")
    if errors:
        return {"valid": False, "errors": errors}

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    books = catalog.get("books", [])
    if len(books) != 17:
        errors.append(f"Expected 17 books in catalog, got {len(books)}")

    src_cat = json.loads((DATA_DIR / "source_catalog.json").read_text(encoding="utf-8"))
    src_by_id = {s["source_id"]: s for s in src_cat.get("sources", [])}

    page_sha_by_key: dict[str, str] = {}
    page_body_by_key: dict[str, str] = {}
    for b in books:
        bid = b["book_id"]
        if bid not in src_by_id:
            errors.append(f"Book {bid} missing from data/source_catalog.json")
        elif b.get("sha256") != src_by_id[bid].get("sha256"):
            errors.append(f"SHA mismatch for {bid}")

        jsonl_path = LIB_SOURCES_DIR / f"{bid}.jsonl"
        if not jsonl_path.exists():
            errors.append(f"Missing extracted JSONL for {bid}")
            continue

        rows = [json.loads(ln) for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if len(rows) != b["total_units"]:
            errors.append(f"Unit count mismatch for {bid}: {len(rows)} vs {b['total_units']}")

        if b["search_index_status"] == "scan_browse_only":
            non_empty = sum(1 for r in rows if r.get("body_text"))
            if non_empty != 0:
                errors.append(f"Scan-only book {bid} has {non_empty} non-empty fabricated body_text rows!")
        else:
            for r in rows:
                key = f"{bid}:{r['page_no']}"
                page_sha_by_key[key] = r.get("text_sha256", "")
                page_body_by_key[key] = r.get("body_text", "")

    # Verify known IDs across all 4 modules
    valid_ids: set[str] = set()
    for fn in ("formulas.json", "jinkui_formulas.json"):
        raw_f = json.loads((DATA_DIR / fn).read_text(encoding="utf-8"))
        for f in (raw_f if isinstance(raw_f, list) else raw_f.get("formulas", [])):
            valid_ids.add(f["id"])
    raw_b = json.loads((DATA_DIR / "bencao" / "entries.json").read_text(encoding="utf-8"))
    for h in (raw_b if isinstance(raw_b, list) else raw_b.get("items", [])):
        valid_ids.add(h["id"])
    for fn in ("acupoints.json", "conditions.json", "meridians.json", "techniques.json"):
        for item in json.loads((DATA_DIR / "acupuncture" / fn).read_text(encoding="utf-8")).get("items", []):
            valid_ids.add(item["id"])
    for item in json.loads((DATA_DIR / "neijing" / "concepts.json").read_text(encoding="utf-8")).get("items", []):
        valid_ids.add(item["id"])
    for ch in json.loads((DATA_DIR / "neijing" / "chapters.json").read_text(encoding="utf-8")).get("chapters", []):
        valid_ids.add(ch["id"])

    cross = json.loads(cross_path.read_text(encoding="utf-8"))
    for pk, links in cross.get("page_links", {}).items():
        if pk not in page_body_by_key:
            errors.append(f"page_links references unknown or scan-only page {pk}")
        for lk in links:
            if lk["entity_id"] not in valid_ids:
                errors.append(f"Broken entity_id in page_links[{pk}]: {lk['entity_id']}")

    for eid, refs in cross.get("entity_refs", {}).items():
        if eid not in valid_ids:
            errors.append(f"Broken entity_id in entity_refs: {eid}")
        for r in refs:
            key = f"{r['book_id']}:{r['page_no']}"
            if page_sha_by_key.get(key) != r.get("text_sha256"):
                errors.append(f"SHA mismatch on entity_refs[{eid}] -> {key}")

    syndromes = json.loads(syndromes_path.read_text(encoding="utf-8")).get("items", [])
    if len(syndromes) < 18:
        errors.append(f"Expected >= 18 syndrome clusters, got {len(syndromes)}")
    for sc in syndromes:
        for field in (
            "neijing_concept_ids",
            "neijing_chapter_ids",
            "formula_ids",
            "bencao_ids",
            "acupuncture_condition_ids",
            "acupuncture_point_ids",
        ):
            for tid in sc.get(field, []):
                if tid not in valid_ids:
                    errors.append(f"Syndrome {sc['id']} broken {field} ID: {tid}")
        for lr in sc.get("library_refs", []):
            key = f"{lr['book_id']}:{lr['page_no']}"
            if page_sha_by_key.get(key) != lr.get("text_sha256"):
                errors.append(f"Syndrome {sc['id']} library_ref SHA mismatch: {key}")

    net = json.loads(network_path.read_text(encoding="utf-8"))
    for edge in net.get("edges", []):
        if edge["target_id"] not in valid_ids:
            errors.append(f"Broken network edge: {edge}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "books": len(books),
        "indexed_books": catalog["stats"]["indexed_books"],
        "scan_only_books": catalog["stats"]["scan_only_books"],
        "linked_pages": len(cross.get("page_links", {})),
        "linked_entities": len(cross.get("entity_refs", {})),
        "syndromes": len(syndromes),
        "network_edges": len(net.get("edges", [])),
    }


def main() -> None:
    res = validate_all()
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if not res["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
