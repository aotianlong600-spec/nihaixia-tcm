"""Validation gate for Stage 1 acupuncture review batches and compiled data."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from etl.review_ledger import (
    load_pages_index,
    load_source_catalog,
    validate_record_provenance,
    validate_source_span,
)


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "brain_data" / "acupuncture"
BATCHES_DIR = DATA_DIR / "review_batches"
MANIFEST_PATH = DATA_DIR / "batch_manifest.json"
PAGES_PATH = ROOT / "sources" / "acupuncture" / "pages.jsonl"

BANNED_PLACEHOLDERS = ("待整理", "待补", "尚待补全", "暂无来源")
HIGH_RISK_TERMS = ("直刺", "深", "肺", "放血", "火针", "烧针", "肿瘤", "脑瘤", "癌", "全蝎", "蜈蚣", "禁", "孕妇", "小儿", "急", "昏迷", "疤")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_batch_payload(
    batch: dict,
    sources_by_id: dict[str, dict],
    pages_by_id: dict[str, dict],
) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()

    for group_key, expected_type in (
        ("meridians", "meridian"),
        ("acupoints", "acupoint"),
        ("techniques", "technique"),
        ("conditions", "condition_teaching"),
    ):
        items = batch.get(group_key, [])
        if not isinstance(items, list):
            errors.append(f"{group_key} must be a list")
            continue
        for item in items:
            rec_id = item.get("id", "<missing-id>")
            if rec_id in seen_ids:
                errors.append(f"duplicate id in batch: {rec_id}")
            seen_ids.add(rec_id)
            if item.get("record_type") != expected_type:
                errors.append(f"{rec_id}: record_type must be {expected_type}")
            errors.extend(f"{rec_id}: {err}" for err in validate_record_provenance(item, sources_by_id, pages_by_id))

            if item.get("review_status") == "approved":
                serialized = json.dumps(
                    {
                        "summary": item.get("summary", ""),
                        "content_layers": item.get("content_layers", {}),
                    },
                    ensure_ascii=False,
                )
                for phrase in BANNED_PLACEHOLDERS:
                    if phrase in serialized:
                        errors.append(f"{rec_id}: approved record contains placeholder {phrase!r}")

            if expected_type == "meridian":
                for field in ("zang_fu", "yin_yang_five_element", "flow_hour", "pathway_source", "acupoint_ids"):
                    if not item.get(field):
                        errors.append(f"{rec_id}: missing meridian field {field}")

            elif expected_type == "acupoint":
                if not item.get("meridian_id"):
                    errors.append(f"{rec_id}: missing acupoint field meridian_id")
                if item.get("review_status") == "approved":
                    for field in ("location_source", "location_simplified", "indications"):
                        if not item.get(field):
                            errors.append(f"{rec_id}: approved acupoint missing field {field}")
                text_blob = json.dumps(item, ensure_ascii=False)
                if any(term in text_blob for term in HIGH_RISK_TERMS) and item.get("risk_level") == "standard":
                    errors.append(f"{rec_id}: contains high-risk terms but risk_level is standard")

            elif expected_type == "technique":
                for field in ("category", "clinical_purpose", "steps_or_rules"):
                    if not item.get(field):
                        errors.append(f"{rec_id}: missing technique field {field}")

            elif expected_type == "condition_teaching":
                patterns = item.get("sub_patterns", [])
                if not patterns:
                    errors.append(f"{rec_id}: condition_teaching needs non-empty sub_patterns")
                for p_idx, pat in enumerate(patterns, 1):
                    for field in (
                        "pattern_name",
                        "symptoms",
                        "syndrome_differentiation",
                        "related_meridian_ids",
                        "referenced_point_ids",
                        "why_selected",
                        "source_spans",
                    ):
                        if not pat.get(field):
                            errors.append(f"{rec_id}: sub_pattern #{p_idx} missing {field}")
                    for sp in pat.get("source_spans", []):
                        errors.extend(
                            f"{rec_id}: sub_pattern #{p_idx} {err}"
                            for err in validate_source_span(sp, sources_by_id, pages_by_id)
                        )

            if item.get("risk_level") in {"high_risk", "emergency"}:
                if not re.search(r"风险|警示|专业|禁忌|不可|禁|医师|急救|危险|损伤", item.get("safety_warning", "")):
                    errors.append(f"{rec_id}: safety_warning lacks explicit risk/professional boundary wording")

    for rel in batch.get("relations", []):
        rel_id = rel.get("id", "<missing-rel-id>")
        for field in ("relation_type", "from_id", "to_id", "label", "source_spans"):
            if not rel.get(field):
                errors.append(f"{rel_id}: relation missing {field}")
        for sp in rel.get("source_spans", []):
            errors.extend(f"{rel_id}: {err}" for err in validate_source_span(sp, sources_by_id, pages_by_id))

    return errors


def validate_compiled_catalog() -> list[str]:
    errors: list[str] = []
    sources_by_id = load_source_catalog()
    pages_by_id = load_pages_index(PAGES_PATH)

    entity_ids: set[str] = set()
    for fname in ("meridians.json", "acupoints.json", "techniques.json", "conditions.json"):
        path = DATA_DIR / fname
        if not path.is_file():
            errors.append(f"missing compiled file: {fname}")
            continue
        payload = read_json(path)
        for item in payload.get("items", []):
            eid = item.get("id")
            if eid in entity_ids:
                errors.append(f"duplicate compiled entity id: {eid}")
            entity_ids.add(eid)
            errors.extend(f"{eid}: {err}" for err in validate_record_provenance(item, sources_by_id, pages_by_id))

    rel_path = DATA_DIR / "relations.json"
    if not rel_path.is_file():
        errors.append("missing compiled file: relations.json")
    else:
        rels = read_json(rel_path).get("items", [])
        for rel in rels:
            rid = rel.get("id")
            if rel.get("from_id") not in entity_ids:
                errors.append(f"{rid}: dangling from_id {rel.get('from_id')!r}")
            if rel.get("to_id") not in entity_ids:
                errors.append(f"{rid}: dangling to_id {rel.get('to_id')!r}")
            for sp in rel.get("source_spans", []):
                errors.extend(f"{rid}: {err}" for err in validate_source_span(sp, sources_by_id, pages_by_id))
    return errors


def validate_all(
    accepted_only: bool = False,
    check_compiled: bool = False,
    single_file: str | None = None,
) -> tuple[int, list[str]]:
    sources_by_id = load_source_catalog()
    pages_by_id = load_pages_index(PAGES_PATH)
    errors: list[str] = []
    if single_file:
        p = Path(single_file)
        paths = [p if p.is_file() else BATCHES_DIR / single_file]
    else:
        paths = sorted(BATCHES_DIR.glob("*.json"))
        if accepted_only:
            manifest = read_json(MANIFEST_PATH)
            paths = [BATCHES_DIR / name for name in manifest.get("accepted", [])]

    for path in paths:
        if not path.is_file():
            errors.append(f"missing batch file: {path}")
            continue
        batch = read_json(path)
        errors.extend(f"{path.name}: {err}" for err in validate_batch_payload(batch, sources_by_id, pages_by_id))

    if check_compiled:
        errors.extend(validate_compiled_catalog())
    return len(paths), errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted", action="store_true")
    parser.add_argument("--compiled", action="store_true")
    parser.add_argument("--file", default=None, help="Validate a single batch file path or filename")
    args = parser.parse_args()
    count, errors = validate_all(
        accepted_only=args.accepted,
        check_compiled=args.compiled,
        single_file=args.file,
    )
    print(json.dumps({"batches": count, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
