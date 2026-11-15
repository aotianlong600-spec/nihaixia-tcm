"""Automated data integrity & scholarly evidence validator for Stage 2 《神农本草经》."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES_PATH = ROOT / "sources" / "bencao" / "pages.jsonl"
INV_PATH = ROOT / "brain_data" / "bencao" / "edition_inventory.json"
CHAPTERS_PATH = ROOT / "brain_data" / "bencao" / "chapters.json"
ENTRIES_PATH = ROOT / "brain_data" / "bencao" / "entries.json"
COMPARISONS_PATH = ROOT / "brain_data" / "bencao" / "comparisons.json"
LEGACY_HERBS_PATH = ROOT / "brain_data" / "herbs.json"
FORMULAS_SHANGHAN_PATH = ROOT / "brain_data" / "formulas.json"
FORMULAS_JINKUI_PATH = ROOT / "brain_data" / "jinkui_formulas.json"


def run_validation() -> dict:
    errors: list[str] = []

    pages = {}
    with PAGES_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                obj = json.loads(line)
                pages[int(obj["pdf_page"])] = obj

    if len(pages) != 154:
        errors.append(f"Expected 154 extracted pages, found {len(pages)}")

    inv = json.loads(INV_PATH.read_text(encoding="utf-8"))
    chapters = json.loads(CHAPTERS_PATH.read_text(encoding="utf-8"))
    entries = json.loads(ENTRIES_PATH.read_text(encoding="utf-8"))
    comparisons = json.loads(COMPARISONS_PATH.read_text(encoding="utf-8")).get("items", [])
    legacy = json.loads(LEGACY_HERBS_PATH.read_text(encoding="utf-8"))

    if len(legacy) != 351:
        errors.append(f"Legacy data/herbs.json must remain 351, got {len(legacy)}")

    if len(entries) != 385:
        errors.append(f"Expected 385 Bencao entries, got {len(entries)}")

    main_entries = [e for e in entries if e["kind"] == "main"]
    ch3_entries = [e for e in entries if e["kind"] == "ch3"]
    if len(main_entries) != 357 or len(ch3_entries) != 28:
        errors.append(f"Expected 357 main + 28 ch3, got {len(main_entries)} + {len(ch3_entries)}")

    by_id = {e["id"]: e for e in entries}
    if len(by_id) != 385:
        errors.append(f"Duplicate canonical entry IDs detected: {len(by_id)} unique vs {len(entries)}")

    # Verify all 351 legacy IDs preserved
    for h in legacy:
        if h["id"] not in by_id:
            errors.append(f"Missing legacy herb id in Stage 2 entries: {h['id']}")

    # Verify 6 recovered main entries exist
    for nm in inv["legacy_snapshot_comparison"]["recovered_omitted_main_entries"]:
        if f"bencao:{nm}" not in by_id:
            errors.append(f"Recovered main entry missing: bencao:{nm}")

    # Verify strict layer separation and verbatim source spans
    for e in entries:
        if e["kind"] == "ch3" and e["classic_original"]["in_shennong_classic"]:
            errors.append(f"Ch3 entry illegally marked in_shennong_classic=True: {e['id']}")
        if e["kind"] == "main" and not e["classic_original"]["text"].strip():
            errors.append(f"Main entry missing classic_original text: {e['id']}")
        if not e["source_spans"]:
            errors.append(f"Missing source_spans: {e['id']}")
        for sp in e["source_spans"]:
            pg = pages.get(sp["pdf_page"])
            if not pg:
                errors.append(f"Invalid pdf_page {sp['pdf_page']} in {e['id']}")
            else:
                if sp["quote"] not in pg["text"]:
                    errors.append(f"Non-verbatim source span quote in {e['id']} p.{sp['pdf_page']}: {sp['quote']!r}")
                if sp["text_sha256"] != pg["text_sha256"]:
                    errors.append(f"SHA256 mismatch in {e['id']} p.{sp['pdf_page']}")

    # Verify mandatory high-risk / emergency alerts
    must_flag = ("bencao:附子", "bencao:乌头", "bencao:半夏", "bencao:巴豆", "bencao:甘遂", "bencao:大戟", "bencao:芫花", "bencao:水蛭", "bencao:粉钖", "bencao:丹砂")
    for eid in must_flag:
        lvl = by_id.get(eid, {}).get("properties", {}).get("risk_level")
        if lvl != "emergency":
            errors.append(f"Toxic/critical herb {eid} expected risk_level='emergency', got {lvl!r}")

    # Verify comparison integrity
    for comp in comparisons:
        if not comp.get("entry_ids"):
            errors.append(f"Comparison missing entry_ids: {comp['id']}")
        for target_id in comp["entry_ids"]:
            if target_id not in by_id:
                errors.append(f"Comparison {comp['id']} cites unknown herb id {target_id}")
        if not comp.get("comparison_points"):
            errors.append(f"Comparison missing comparison_points: {comp['id']}")

    # Verify valid formula backlinks
    all_f_ids = {
        f["id"]
        for path in (FORMULAS_SHANGHAN_PATH, FORMULAS_JINKUI_PATH)
        for f in json.loads(path.read_text(encoding="utf-8"))
    }
    for e in entries:
        for fu in e["formula_usages"]:
            if fu["formula_id"] not in all_f_ids:
                errors.append(f"Invalid formula_id {fu['formula_id']} linked from {e['id']}")

    # Verify key recovered formulas actually link back cleanly
    for fid_need, eid_need in (
        ("shanghan:栀子豉汤", "bencao:ch3-豆豉"),
        ("shanghan:赤石脂禹余粮汤", "bencao:青石赤石黄石白石黑石脂等"),
        ("jinkui:黄土汤", "bencao:ch3-灶心土"),
        ("jinkui:小建中汤", "bencao:ch3-饴糖"),
        ("jinkui:栝蒌薤白半夏汤", "bencao:ch3-薤白"),
    ):
        linked = {u["formula_id"] for u in by_id.get(eid_need, {}).get("formula_usages", [])}
        if fid_need not in linked:
            errors.append(f"Expected Stage 2 recovered formula link missing: {fid_need} -> {eid_need}")

    if len(chapters.get("items", [])) != 8:
        errors.append(f"Expected 8 chapter blocks in chapters.json, got {len(chapters.get('items', []))}")

    summary = {
        "valid": len(errors) == 0,
        "error_count": len(errors),
        "errors": errors[:25],
        "stats": {
            "pages": len(pages),
            "entries": len(entries),
            "main": len(main_entries),
            "ch3": len(ch3_entries),
            "comparisons": len(comparisons),
            "curated_deep": sum(1 for e in entries if e["review_status"] == "approved"),
            "entries_with_formulas": sum(1 for e in entries if e["formula_usages"]),
            "emergency_or_high_risk": sum(1 for e in entries if e["properties"]["risk_level"] in ("high_risk", "emergency")),
        },
    }
    return summary


def main() -> None:
    res = run_validation()
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if not res["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
