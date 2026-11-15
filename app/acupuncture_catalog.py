"""Backend read-only catalog for Stage 1 acupuncture knowledge & textbook browsing."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from app import neijing_catalog


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "brain_data" / "acupuncture"
PAGES_PATH = ROOT / "sources" / "acupuncture" / "pages.jsonl"
SOURCE_PDF = ROOT / "books" / "ni-haixia-medicine" / "倪海厦人纪系列之针灸教程.pdf"
IMAGE_CACHE_DIR = ROOT / ".tmp" / "acupuncture_pages"


@lru_cache(maxsize=1)
def _load_json(filename: str) -> dict:
    path = DATA_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _pages_by_num() -> dict[int, dict]:
    pages: dict[int, dict] = {}
    with PAGES_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            pages[int(row["pdf_page"])] = row
    return pages


@lru_cache(maxsize=1)
def _entities_by_id() -> dict[str, dict]:
    mapping: dict[str, dict] = {}
    for fname in ("meridians.json", "acupoints.json", "techniques.json", "conditions.json"):
        for item in _load_json(fname).get("items", []):
            mapping[item["id"]] = item
    return mapping


@lru_cache(maxsize=1)
def _condition_by_section_id() -> dict[str, str]:
    return {
        item["section_id"]: item["id"]
        for item in _load_json("conditions.json").get("items", [])
        if item.get("section_id")
    }


def _entity_summary(item: dict | None, fallback_id: str = "") -> dict:
    if not item:
        return {
            "id": fallback_id,
            "record_type": "",
            "canonical_name": fallback_id,
            "review_status": "pending",
            "risk_level": "standard",
        }
    return {
        "id": item["id"],
        "record_type": item.get("record_type", ""),
        "canonical_name": item.get("canonical_name", fallback_id),
        "review_status": item.get("review_status", "pending"),
        "evidence_status": item.get("evidence_status", "unlinked"),
        "generation_status": item.get("generation_status", "auto"),
        "risk_level": item.get("risk_level", "standard"),
        "meridian_id": item.get("meridian_id"),
    }


def _relations_for(entity_id: str) -> list[dict]:
    entities = _entities_by_id()
    rels = _load_json("relations.json").get("items", [])
    resolved: list[dict] = []
    for rel in rels:
        if rel["from_id"] != entity_id and rel["to_id"] != entity_id:
            continue
        direction = "outgoing" if rel["from_id"] == entity_id else "incoming"
        peer_id = rel["to_id"] if direction == "outgoing" else rel["from_id"]
        peer = entities.get(peer_id)
        resolved.append(
            {
                "id": rel["id"],
                "relation_type": rel["relation_type"],
                "direction": direction,
                "label": rel.get("label", ""),
                "note": rel.get("note", ""),
                "peer": _entity_summary(peer, peer_id),
                "source_spans": rel.get("source_spans", []),
                "review_status": rel.get("review_status", "pending"),
                "evidence_status": rel.get("evidence_status", "anchored"),
            }
        )
    return resolved


def _query_tokens(q: str) -> list[str]:
    return [tok for tok in re.split(r"[\s,，、;；]+", (q or "").strip().lower()) if tok]


def _matches_query(item: Any, q: str) -> bool:
    tokens = _query_tokens(q)
    if not tokens:
        return True
    blob = json.dumps(item, ensure_ascii=False).lower()
    return all(tok in blob for tok in tokens)


def _filter_common(
    items: list[dict],
    q: str = "",
    review_status: str = "",
    risk_level: str = "",
) -> list[dict]:
    out = items
    if review_status:
        out = [x for x in out if x.get("review_status") == review_status]
    if risk_level:
        out = [x for x in out if x.get("risk_level") == risk_level]
    if q:
        out = [x for x in out if _matches_query(x, q)]
    return out


def overview() -> dict:
    chapters = _load_json("chapters.json")
    indexes = _load_json("book_indexes.json")
    meridians = _load_json("meridians.json")["stats"]
    acupoints = _load_json("acupoints.json")["stats"]
    techniques = _load_json("techniques.json")["stats"]
    conditions = _load_json("conditions.json")["stats"]
    relations = _load_json("relations.json")["stats"]
    return {
        "source_id": chapters["source_id"],
        "total_pages": chapters["total_pages"],
        "chapters": chapters["stats"],
        "meridians": meridians,
        "acupoints": {
            **acupoints,
            "indexed_terms": indexes["stats"]["indexed_acupoint_terms"],
        },
        "techniques": techniques,
        "conditions": {
            **conditions,
            "indexed_terms": indexes["stats"]["indexed_condition_terms"],
        },
        "relations": relations,
    }


def list_chapters() -> dict:
    data = json.loads((DATA_DIR / "chapters.json").read_text(encoding="utf-8"))
    cond_map = _condition_by_section_id()
    for ch in data.get("chapters", []):
        for sec in ch.get("sections", []):
            if sec["id"] in cond_map:
                sec["condition_id"] = cond_map[sec["id"]]
    return data


def get_chapter(chapter_id: str) -> dict | None:
    data = list_chapters()
    for ch in data.get("chapters", []):
        if ch["id"] == chapter_id:
            return ch
    for item in data.get("frontmatter", []) + data.get("appendices", []):
        if item["id"] == chapter_id:
            return item
    return None


def list_book_indexes(q: str = "", kind: str = "") -> dict:
    indexes = _load_json("book_indexes.json")
    acup = indexes.get("pinyin_acupoints", [])
    cond = indexes.get("condition_index", [])
    tokens = _query_tokens(q)
    if tokens:
        acup = [x for x in acup if all(t in x["name"].lower() for t in tokens)]
        cond = [x for x in cond if all(t in x["name"].lower() for t in tokens)]
    if kind == "acupoint":
        cond = []
    elif kind == "condition":
        acup = []
    return {
        "source_id": indexes["source_id"],
        "acupoint_terms": acup,
        "condition_terms": cond,
        "counts": {"acupoint_terms": len(acup), "condition_terms": len(cond)},
    }


def list_meridians(q: str = "", review_status: str = "", risk_level: str = "") -> dict:
    items = _load_json("meridians.json").get("items", [])
    filtered = _filter_common(items, q=q, review_status=review_status, risk_level=risk_level)
    return {
        "total": len(items),
        "filtered": len(filtered),
        "items": [
            {
                "id": m["id"],
                "canonical_name": m["canonical_name"],
                "aliases": m.get("aliases", []),
                "page_range": m.get("page_range", []),
                "zang_fu": m.get("zang_fu", ""),
                "flow_hour": m.get("flow_hour", ""),
                "acupoint_count": len(m.get("acupoint_ids", [])),
                "paired_meridian_id": m.get("paired_meridian_id", ""),
                "summary": m.get("summary", ""),
                "generation_status": m["generation_status"],
                "evidence_status": m["evidence_status"],
                "review_status": m["review_status"],
                "risk_level": m["risk_level"],
            }
            for m in filtered
        ],
    }


def get_meridian(meridian_id: str) -> dict | None:
    entities = _entities_by_id()
    item = entities.get(meridian_id)
    if not item or item.get("record_type") != "meridian":
        return None
    detail = dict(item)
    detail["resolved_acupoints"] = [
        {
            **_entity_summary(entities.get(pid), pid),
            "sequence": entities.get(pid, {}).get("sequence"),
            "pinyin": entities.get(pid, {}).get("pinyin", ""),
            "special_categories": entities.get(pid, {}).get("special_categories", []),
            "summary": entities.get(pid, {}).get("summary", ""),
        }
        for pid in item.get("acupoint_ids", [])
    ]
    paired_id = item.get("paired_meridian_id")
    detail["paired_meridian"] = _entity_summary(entities.get(paired_id), paired_id) if paired_id else None
    detail["relations"] = _relations_for(meridian_id)
    detail["neijing_relations"] = neijing_catalog.relations_for_external(meridian_id)
    return detail


def list_points(
    q: str = "",
    meridian_id: str = "",
    review_status: str = "",
    risk_level: str = "",
) -> dict:
    entities = _entities_by_id()
    items = _load_json("acupoints.json").get("items", [])
    if meridian_id:
        items = [x for x in items if x.get("meridian_id") == meridian_id]
    filtered = _filter_common(items, q=q, review_status=review_status, risk_level=risk_level)
    return {
        "total": len(_load_json("acupoints.json").get("items", [])),
        "filtered": len(filtered),
        "items": [
            {
                "id": p["id"],
                "canonical_name": p["canonical_name"],
                "aliases": p.get("aliases", []),
                "pinyin": p.get("pinyin", ""),
                "meridian_id": p.get("meridian_id", ""),
                "meridian_name": entities.get(p.get("meridian_id", ""), {}).get("canonical_name", ""),
                "sequence": p.get("sequence"),
                "special_categories": p.get("special_categories", []),
                "indications": p.get("indications", []),
                "summary": p.get("summary", ""),
                "generation_status": p["generation_status"],
                "evidence_status": p["evidence_status"],
                "review_status": p["review_status"],
                "risk_level": p["risk_level"],
            }
            for p in filtered
        ],
    }


def get_point(point_id: str) -> dict | None:
    entities = _entities_by_id()
    item = entities.get(point_id)
    if not item or item.get("record_type") != "acupoint":
        return None
    detail = dict(item)
    mid = item.get("meridian_id", "")
    detail["meridian"] = _entity_summary(entities.get(mid), mid)
    detail["resolved_combinations"] = [
        {
            **combo,
            "point": _entity_summary(entities.get(combo["point_id"]), combo["point_id"]),
        }
        for combo in item.get("combinations", [])
    ]
    detail["relations"] = _relations_for(point_id)
    detail["neijing_relations"] = neijing_catalog.relations_for_external(point_id)
    return detail


def list_techniques(
    q: str = "",
    category: str = "",
    review_status: str = "",
    risk_level: str = "",
) -> dict:
    items = _load_json("techniques.json").get("items", [])
    if category:
        items = [x for x in items if x.get("category") == category]
    filtered = _filter_common(items, q=q, review_status=review_status, risk_level=risk_level)
    return {
        "total": len(_load_json("techniques.json").get("items", [])),
        "filtered": len(filtered),
        "items": [
            {
                "id": t["id"],
                "canonical_name": t["canonical_name"],
                "aliases": t.get("aliases", []),
                "category": t.get("category", ""),
                "clinical_purpose": t.get("clinical_purpose", ""),
                "summary": t.get("summary", ""),
                "generation_status": t["generation_status"],
                "evidence_status": t["evidence_status"],
                "review_status": t["review_status"],
                "risk_level": t["risk_level"],
            }
            for t in filtered
        ],
    }


def get_technique(technique_id: str) -> dict | None:
    item = _entities_by_id().get(technique_id)
    if not item or item.get("record_type") != "technique":
        return None
    detail = dict(item)
    detail["relations"] = _relations_for(technique_id)
    detail["neijing_relations"] = neijing_catalog.relations_for_external(technique_id)
    return detail


def list_conditions(
    q: str = "",
    review_status: str = "",
    risk_level: str = "",
) -> dict:
    items = _load_json("conditions.json").get("items", [])
    filtered = _filter_common(items, q=q, review_status=review_status, risk_level=risk_level)
    return {
        "total": len(items),
        "filtered": len(filtered),
        "items": [
            {
                "id": c["id"],
                "canonical_name": c["canonical_name"],
                "aliases": c.get("aliases", []),
                "chapter_id": c.get("chapter_id", ""),
                "section_id": c.get("section_id", ""),
                "page_range": c.get("page_range", []),
                "sub_pattern_count": len(c.get("sub_patterns", [])),
                "summary": c.get("summary", ""),
                "generation_status": c["generation_status"],
                "evidence_status": c["evidence_status"],
                "review_status": c["review_status"],
                "risk_level": c["risk_level"],
            }
            for c in filtered
        ],
    }


def get_condition(condition_id: str) -> dict | None:
    entities = _entities_by_id()
    item = entities.get(condition_id)
    if not item or item.get("record_type") != "condition_teaching":
        return None
    detail = dict(item)
    resolved_patterns = []
    for pat in item.get("sub_patterns", []):
        pat_copy = dict(pat)
        pat_copy["resolved_meridians"] = [
            _entity_summary(entities.get(mid), mid) for mid in pat.get("related_meridian_ids", [])
        ]
        pat_copy["resolved_points"] = [
            _entity_summary(entities.get(pid), pid) for pid in pat.get("referenced_point_ids", [])
        ]
        resolved_patterns.append(pat_copy)
    detail["sub_patterns"] = resolved_patterns
    detail["relations"] = _relations_for(condition_id)
    detail["neijing_relations"] = neijing_catalog.relations_for_external(condition_id)
    return detail


def get_source_page(pdf_page: int) -> dict | None:
    row = _pages_by_num().get(int(pdf_page))
    if not row:
        return None
    chapters = _load_json("chapters.json")
    covering_sections: list[dict] = []
    for ch in chapters.get("chapters", []):
        for sec in ch.get("sections", []):
            if sec["page_start"] <= pdf_page <= sec["page_end"]:
                covering_sections.append(
                    {
                        "chapter_id": ch["id"],
                        "chapter_title": ch["title"],
                        "section_id": sec["id"],
                        "section_title": sec["title"],
                        "pilot_status": sec.get("pilot_status", "pending"),
                    }
                )
    return {
        **row,
        "covering_sections": covering_sections,
        "image_url": f"/api/acupuncture/source-pages/{pdf_page}/image",
    }


def render_page_image(pdf_page: int) -> Path | None:
    if pdf_page < 1 or pdf_page > 216 or not SOURCE_PDF.is_file():
        return None
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = IMAGE_CACHE_DIR / f"p{pdf_page:03d}.png"
    if not out_path.is_file():
        import pypdfium2 as pdfium  # noqa: PLC0415

        doc = pdfium.PdfDocument(str(SOURCE_PDF))
        try:
            page = doc[pdf_page - 1]
            bitmap = page.render(scale=150 / 72)
            pil_image = bitmap.to_pil()
            pil_image.save(out_path, format="PNG")
        finally:
            doc.close()
    return out_path
