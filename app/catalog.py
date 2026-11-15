"""Read-only local catalog shared by the API and HTML app."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import re

from app import bencao_catalog, neijing_catalog
from etl.herb_alias import ALIAS, CONTROVERSY_ALIASES


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "brain_data"


def _read(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _norm(value: str) -> str:
    return re.sub(r"[\s·・，,。；;（）()]+", "", value or "").lower()


def _resolve_herb(
    name: str,
    herbs_by_name: dict[str, dict],
    bencao_by_name: dict[str, dict] | None = None,
) -> dict | None:
    target = ALIAS.get(name, (name, ""))[0]
    pool = bencao_by_name or {}
    # Stage 2 complete edition (385 herbs) first so recovered Ch3 entries like 豆豉/鸡子黄/猪胆 resolve accurately instead of old proxies
    return (
        pool.get(target)
        or pool.get(target.split("（")[0])
        or pool.get(name)
        or herbs_by_name.get(target)
        or herbs_by_name.get(name)
    )


def _summary(formula: dict) -> dict:
    source = formula["source"]
    return {
        "id": formula["id"],
        "name": formula["name"],
        "book": formula.get("book", ""),
        "type": formula["type"],
        "status": formula.get("status", "complete"),
        "status_label": formula.get("status_label", ""),
        "six_meridian": formula["six_meridian"],
        "chapter": formula.get("chapter", ""),
        "ingredient_count": len(formula["ingredients"]),
        "locator": source.get("line") or source.get("page") or "",
        "source_title": source.get("title", ""),
        "source_note": source.get("note", ""),
        "review_status": formula.get("evidence", {}).get("review_status", "pending"),
    }


@lru_cache(maxsize=1)
def _index() -> dict:
    formulas = _read("formulas.json") + _read("jinkui_formulas.json")
    evidence = _read("formula_evidence.json")
    modules = _read("formula_modules.json")
    for formula in formulas:
        merged = deepcopy(evidence.get(formula["id"], {}))
        merged.update(deepcopy(modules.get(formula["id"], {})))
        formula["evidence"] = merged
    herbs = _read("herbs.json")
    herbs_by_name = {item["name"]: item for item in herbs}
    bencao_entries = bencao_catalog._entries()
    bencao_by_name: dict[str, dict] = {}
    for entry in bencao_entries:
        if entry["kind"] == "main":
            bencao_by_name[entry["name"]] = entry
    for entry in bencao_entries:
        if entry["kind"] == "ch3":
            bencao_by_name.setdefault(entry["name"], entry)
            bencao_by_name.setdefault(entry["name"].split("（")[0], entry)

    formula_links: dict[str, list[dict]] = {}
    for formula in formulas:
        for ingredient in formula["ingredients"]:
            herb = _resolve_herb(ingredient["name"], herbs_by_name, bencao_by_name)
            if herb:
                formula_links.setdefault(herb["id"], []).append(_summary(formula))

    return {
        "formulas": formulas,
        "formulas_by_id": {item["id"]: item for item in formulas},
        "herbs": herbs,
        "herbs_by_id": {item["id"]: item for item in herbs},
        "herbs_by_name": herbs_by_name,
        "bencao_by_name": bencao_by_name,
        "formula_links": formula_links,
    }


def _formula_text(formula: dict) -> str:
    return " ".join(
        [
            formula["name"],
            formula.get("book", ""),
            formula.get("chapter", ""),
            formula.get("indication", ""),
            formula.get("composition_raw", ""),
            formula.get("decoction", ""),
            formula.get("notes", ""),
            " ".join(formula.get("aliases", [])),
            formula["source"].get("note", ""),
            formula.get("evidence", {}).get("usage_plain", ""),
            formula.get("evidence", {}).get("why", ""),
        ]
    )


def _herb_text(herb: dict) -> str:
    return " ".join([herb["name"], *herb.get("names", []), *herb.get("sections", {}).values()])


def list_formulas(
    query: str = "",
    kind: str = "",
    meridian: str = "",
    book: str = "",
    status: str = "",
    review: str = "",
    page: int = 1,
    page_size: int = 24,
) -> dict:
    query_norm = _norm(query)
    kind = kind.strip()
    meridian = meridian.strip()
    book = book.strip()
    status = status.strip()
    review = review.strip()
    items = [
        item
        for item in _index()["formulas"]
        if (not kind or item["type"] == kind)
        and (not meridian or item["six_meridian"] == meridian)
        and (not book or item.get("book") == book)
        and (not status or item.get("status") == status)
        and (not review or item.get("evidence", {}).get("review_status") == review)
        and (not query_norm or query_norm in _norm(_formula_text(item)))
    ]
    total = len(items)
    start = max(0, (page - 1) * page_size)
    return {
        "items": [_summary(item) for item in items[start : start + page_size]],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_formula(formula_id: str) -> dict | None:
    idx = _index()
    formula = idx["formulas_by_id"].get(formula_id)
    if not formula:
        return None
    result = deepcopy(formula)
    linked = []
    for ingredient in result["ingredients"]:
        raw_name = ingredient["name"]
        herb = _resolve_herb(raw_name, idx["herbs_by_name"], idx.get("bencao_by_name"))
        if herb:
            ingredient["herb_id"] = herb["id"]
            ingredient["herb_name"] = herb.get("short_name", herb["name"])
            if "properties" in herb:
                ingredient["herb_risk_level"] = herb["properties"].get("risk_level", "standard")
                ingredient["herb_grade"] = herb.get("grade", "")
            c_note = CONTROVERSY_ALIASES.get(raw_name, "")
            if c_note:
                ingredient["herb_controversy"] = c_note
            linked.append({"id": herb["id"], "name": herb.get("short_name", herb["name"])})
    result["related_herbs"] = linked
    result["neijing_relations"] = neijing_catalog.relations_for_external(formula_id)
    return result


def list_herbs(query: str = "", category: str = "", page: int = 1, page_size: int = 24) -> dict:
    query_norm = _norm(query)
    category = category.strip()
    items = [
        item
        for item in _index()["herbs"]
        if (not category or category in item.get("sections", {}))
        and (not query_norm or query_norm in _norm(_herb_text(item)))
    ]
    total = len(items)
    start = max(0, (page - 1) * page_size)
    return {
        "items": [
            {
                "id": item["id"],
                "name": item["name"],
                "page": item["page_start"],
                "formula_count": len(_index()["formula_links"].get(item["id"], [])),
                "source": item.get("source", ""),
            }
            for item in items[start : start + page_size]
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_herb(herb_id: str) -> dict | None:
    idx = _index()
    bencao_entry = bencao_catalog.get_entry(herb_id)
    herb = idx["herbs_by_id"].get(herb_id)
    if not herb and not bencao_entry:
        return None
    if not herb and bencao_entry:
        # Synthesize backward-compatible view for 34 newly recovered main/Ch3 Stage 2 entries
        result = {
            "id": bencao_entry["id"],
            "name": bencao_entry["name"],
            "names": [bencao_entry["name"], *bencao_entry.get("aliases", [])],
            "seq": bencao_entry["seq_raw"],
            "page_start": bencao_entry["page_start"],
            "page_end": bencao_entry["page_end"],
            "source": bencao_entry["grade"],
            "sections": {
                "本经原文": bencao_entry["classic_original"]["text"],
                "性味": bencao_entry["properties"].get("qi_wei_raw", ""),
                "主治": bencao_entry["applications"].get("main_summary", ""),
                "用量": bencao_entry["processing_and_compatibility"].get("dosage", ""),
                "禁忌": bencao_entry["processing_and_compatibility"].get("contraindications", ""),
            },
            "formulas": deepcopy(idx["formula_links"].get(bencao_entry["id"], [])),
            "neijing_relations": bencao_entry.get("neijing_relations", []),
            "bencao_entry": bencao_entry,
        }
        return result
    result = deepcopy(herb)
    result["formulas"] = deepcopy(idx["formula_links"].get(herb_id, []))
    result["neijing_relations"] = neijing_catalog.relations_for_external(herb_id)
    if bencao_entry:
        result["bencao_entry"] = bencao_entry
    return result


def list_six_channels() -> dict:
    return {"items": deepcopy(_read("six_channels.json")["items"])}


def get_six_channel(channel_id: str) -> dict | None:
    channel = next(
        (item for item in _read("six_channels.json")["items"] if item["id"] == channel_id),
        None,
    )
    if not channel:
        return None
    result = deepcopy(channel)
    result["neijing_relations"] = neijing_catalog.relations_for_external(channel_id)
    return result


def overview() -> dict:
    formulas = _index()["formulas"]
    by_book = {}
    by_status = {}
    review_status = {}
    for item in formulas:
        book = item.get("book", "")
        status = item.get("status", "")
        by_book[book] = by_book.get(book, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        review = item.get("evidence", {}).get("review_status", "pending")
        review_status[review] = review_status.get(review, 0) + 1
    return {
        "formulas": len(formulas),
        "herbs": len(_index()["herbs"]),
        "by_book": by_book,
        "by_status": by_status,
        "review_status": review_status,
        "source_pending": by_status.get("missing", 0),
        "six_channels": len(_read("six_channels.json")["items"]),
        "modules": {
            "formulas": "ready",
            "herbs": "complete",
            "diagnosis": "not_imported",
            "six_channels": "partial",
            "acupuncture": "complete",
            "conditions": "complete",
            "neijing": "partial",
        },
        "acupuncture_summary": _acupuncture_overview(),
        "bencao_summary": _bencao_overview(),
        "neijing_summary": _neijing_overview(),
    }


def _acupuncture_overview() -> dict:
    from . import acupuncture_catalog  # noqa: PLC0415

    return acupuncture_catalog.overview()


def _bencao_overview() -> dict:
    from . import bencao_catalog  # noqa: PLC0415

    return bencao_catalog.overview()


def _neijing_overview() -> dict:
    from . import neijing_catalog  # noqa: PLC0415

    return neijing_catalog.overview()
