"""Validation gate for Stage 3 Huangdi Neijing review batches and compiled data."""
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
DATA_DIR = ROOT / "brain_data" / "neijing"
BATCHES_DIR = DATA_DIR / "review_batches"
MANIFEST_PATH = DATA_DIR / "batch_manifest.json"
CHAPTERS_PATH = DATA_DIR / "chapters.json"
PAGES_PATH = ROOT / "sources" / "neijing" / "pages.jsonl"

BANNED_PLACEHOLDERS = ("待整理", "待补", "尚待补全", "暂无来源")
HIGH_RISK_TERMS = ("真脏脉", "死症", "绝汗", "厥逆", "喘满", "呕血", "吐血", "剧痛", "急症", "重症", "昏迷", "危候", "死期")
CLINICAL_OVERCLAIM_TERMS = ("已获现代临床循证证实", "现代医学已完全证明", "保证治愈", "根治一切")

VALID_SUBMODULES = (
    "classic_text",
    "yin_yang_wu_xing",
    "zang_xiang",
    "bing_yin_bing_ji",
    "zhen_fa",
    "bian_zheng",
    "yang_sheng",
)

DOCTRINE_SUBMODULES = tuple(x for x in VALID_SUBMODULES if x != "classic_text")

VALID_TARGET_MODULES = (
    "neijing",
    "acupuncture",
    "six_channels",
    "formulas",
    "jinkui_formulas",
    "herbs",
)

VALID_RELATION_TYPES = (
    "grounds_theory",
    "guides_differentiation",
    "corresponds_to_channel",
    "corresponds_to_meridian",
    "supports_acupoint",
    "relates_condition",
    "illuminates_formula",
    "contextualizes_herb",
    "paired_doctrine",
    "contrasts_with",
    "relates_chapter",
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_external_target_ids() -> dict[str, set[str]]:
    """Load valid entity IDs from sibling Stage 1 / Stage 2 / Stage 4 datasets."""
    targets: dict[str, set[str]] = {
        "acupuncture": set(),
        "six_channels": set(),
        "formulas": set(),
        "jinkui_formulas": set(),
        "herbs": set(),
    }
    acu_dir = ROOT / "brain_data" / "acupuncture"
    for fname in ("meridians.json", "acupoints.json", "techniques.json", "conditions.json"):
        p = acu_dir / fname
        if p.is_file():
            for item in read_json(p).get("items", []):
                targets["acupuncture"].add(item["id"])

    six_p = ROOT / "brain_data" / "six_channels.json"
    if six_p.is_file():
        for item in read_json(six_p).get("items", []):
            targets["six_channels"].add(item["id"])

    for key, fname in (
        ("formulas", "formulas.json"),
        ("jinkui_formulas", "jinkui_formulas.json"),
        ("herbs", "herbs.json"),
    ):
        p = ROOT / "brain_data" / fname
        if p.is_file():
            for item in read_json(p):
                targets[key].add(item["id"])
    return targets


def _all_valid_external_ids(targets: dict[str, set[str]]) -> set[str]:
    merged: set[str] = set()
    for ids in targets.values():
        merged.update(ids)
    return merged


def validate_batch_payload(
    batch: dict,
    sources_by_id: dict[str, dict],
    pages_by_id: dict[str, dict],
    external_targets: dict[str, set[str]] | None = None,
) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    if external_targets is None:
        external_targets = load_external_target_ids()
    all_external = _all_valid_external_ids(external_targets)

    known_chapters: set[str] = set()
    if CHAPTERS_PATH.is_file():
        known_chapters = {ch["id"] for ch in read_json(CHAPTERS_PATH).get("chapters", [])}

    for group_key, expected_type in (
        ("passages", "classic_chapter"),
        ("concepts", "theory"),
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

            serialized_layers = json.dumps(
                {
                    "summary": item.get("summary", ""),
                    "content_layers": item.get("content_layers", {}),
                },
                ensure_ascii=False,
            )
            for term in CLINICAL_OVERCLAIM_TERMS:
                if term in serialized_layers:
                    errors.append(f"{rec_id}: contains unverified modern clinical claim {term!r}")

            if item.get("review_status") == "approved":
                for phrase in BANNED_PLACEHOLDERS:
                    if phrase in serialized_layers:
                        errors.append(f"{rec_id}: approved record contains placeholder {phrase!r}")

            if expected_type == "classic_chapter":
                cid = item.get("chapter_id")
                if not cid:
                    errors.append(f"{rec_id}: missing passage field chapter_id")
                elif known_chapters and cid not in known_chapters:
                    errors.append(f"{rec_id}: unknown chapter_id {cid!r}")
                if not item.get("classic_standard_title"):
                    errors.append(f"{rec_id}: missing classic_standard_title")
                if item.get("review_status") == "approved":
                    if not item.get("summary"):
                        errors.append(f"{rec_id}: approved passage missing summary")
                    layers = item.get("content_layers", {})
                    if not layers.get("source_quote") or not layers.get("ni_teaching"):
                        errors.append(f"{rec_id}: approved passage requires both source_quote and ni_teaching layers")
                    if not item.get("key_points"):
                        errors.append(f"{rec_id}: approved passage requires non-empty key_points")
                    if not item.get("historical_boundary_note"):
                        errors.append(f"{rec_id}: approved passage requires historical_boundary_note")

            elif expected_type == "theory":
                submod = item.get("submodule")
                if submod not in DOCTRINE_SUBMODULES:
                    errors.append(f"{rec_id}: invalid concept submodule {submod!r}")
                for field in ("canonical_name", "doctrine_key", "chapter_ids", "summary"):
                    if not item.get(field):
                        errors.append(f"{rec_id}: missing concept field {field}")
                for cid in item.get("chapter_ids", []):
                    if known_chapters and cid not in known_chapters:
                        errors.append(f"{rec_id}: unknown chapter_id in chapter_ids: {cid!r}")
                if item.get("review_status") == "approved":
                    if not item.get("historical_boundary_note"):
                        errors.append(f"{rec_id}: approved concept requires historical_boundary_note")
                    rules = item.get("differentiation_rules", [])
                    if not rules:
                        errors.append(f"{rec_id}: approved concept requires non-empty differentiation_rules")
                    for idx, rule in enumerate(rules, 1):
                        for rf in ("condition", "manifestations", "traditional_judgment", "classic_basis"):
                            if not rule.get(rf):
                                errors.append(f"{rec_id}: differentiation_rules #{idx} missing {rf}")
                    links = item.get("classic_links", [])
                    if not links:
                        errors.append(f"{rec_id}: approved concept requires at least one verified classic_links entry")
                    for l_idx, link in enumerate(links, 1):
                        mod = link.get("target_module")
                        tid = link.get("target_id")
                        if mod not in VALID_TARGET_MODULES:
                            errors.append(f"{rec_id}: classic_links #{l_idx} invalid target_module {mod!r}")
                        elif mod != "neijing" and tid not in external_targets.get(mod, set()):
                            errors.append(f"{rec_id}: classic_links #{l_idx} dangling {mod} target_id {tid!r}")
                        if not link.get("rationale"):
                            errors.append(f"{rec_id}: classic_links #{l_idx} missing rationale")

            text_blob = json.dumps(item, ensure_ascii=False)
            if any(term in text_blob for term in HIGH_RISK_TERMS) and item.get("risk_level") == "standard":
                errors.append(f"{rec_id}: contains high-risk/critical illness terms but risk_level is standard")

            if item.get("risk_level") in {"high_risk", "emergency"}:
                if not re.search(r"风险|警示|专业|急|危重|就医|医师|传统|理论|边界", item.get("safety_warning", "")):
                    errors.append(f"{rec_id}: safety_warning lacks explicit boundary/risk wording")

    for rel in batch.get("relations", []):
        rel_id = rel.get("id", "<missing-rel-id>")
        rtype = rel.get("relation_type")
        if rtype not in VALID_RELATION_TYPES:
            errors.append(f"{rel_id}: invalid relation_type {rtype!r}")
        for field in ("relation_type", "from_id", "to_id", "to_module", "label", "source_spans"):
            if not rel.get(field):
                errors.append(f"{rel_id}: relation missing {field}")
        to_mod = rel.get("to_module")
        if to_mod not in VALID_TARGET_MODULES:
            errors.append(f"{rel_id}: invalid to_module {to_mod!r}")
        elif to_mod != "neijing" and rel.get("to_id") not in external_targets.get(to_mod, set()):
            errors.append(f"{rel_id}: dangling {to_mod} target {rel.get('to_id')!r}")
        elif to_mod == "neijing" and rel.get("to_id") in all_external:
            errors.append(f"{rel_id}: to_module marked neijing but id belongs to external module")
        for sp in rel.get("source_spans", []):
            errors.extend(f"{rel_id}: {err}" for err in validate_source_span(sp, sources_by_id, pages_by_id))

    return errors


def validate_compiled_catalog() -> list[str]:
    errors: list[str] = []
    sources_by_id = load_source_catalog()
    pages_by_id = load_pages_index(PAGES_PATH)
    external_targets = load_external_target_ids()
    all_external = _all_valid_external_ids(external_targets)

    entity_ids: set[str] = set()
    neijing_ids: set[str] = set()

    for fname in ("passages.json", "concepts.json"):
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
            neijing_ids.add(eid)
            errors.extend(f"{eid}: {err}" for err in validate_record_provenance(item, sources_by_id, pages_by_id))

    if CHAPTERS_PATH.is_file() and (DATA_DIR / "passages.json").is_file():
        chapters = read_json(CHAPTERS_PATH).get("chapters", [])
        passages = read_json(DATA_DIR / "passages.json").get("items", [])
        ch_ids = {ch["id"] for ch in chapters}
        p_ch_ids = {p.get("chapter_id") for p in passages}
        if ch_ids != p_ch_ids:
            errors.append(
                f"passages.json chapter_id set mismatch: missing={sorted(ch_ids - p_ch_ids)[:5]}, extra={sorted(p_ch_ids - ch_ids)[:5]}"
            )

    if (DATA_DIR / "concepts.json").is_file():
        for concept in read_json(DATA_DIR / "concepts.json").get("items", []):
            cid = concept.get("id")
            for link in concept.get("classic_links", []):
                mod = link.get("target_module")
                tid = link.get("target_id")
                if mod == "neijing":
                    if tid not in neijing_ids:
                        errors.append(f"{cid}: dangling neijing classic_link target_id {tid!r}")
                elif tid not in external_targets.get(mod, set()):
                    errors.append(f"{cid}: dangling {mod} classic_link target_id {tid!r}")

    rel_path = DATA_DIR / "relations.json"
    if not rel_path.is_file():
        errors.append("missing compiled file: relations.json")
    else:
        rels = read_json(rel_path).get("items", [])
        for rel in rels:
            rid = rel.get("id")
            if rel.get("from_id") not in neijing_ids:
                errors.append(f"{rid}: dangling from_id {rel.get('from_id')!r}")
            to_id = rel.get("to_id")
            to_mod = rel.get("to_module")
            if to_mod == "neijing":
                if to_id not in neijing_ids:
                    errors.append(f"{rid}: dangling internal to_id {to_id!r}")
            else:
                if to_id not in external_targets.get(to_mod, set()) or to_id not in all_external:
                    errors.append(f"{rid}: dangling external {to_mod} to_id {to_id!r}")
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
    external_targets = load_external_target_ids()
    errors: list[str] = []

    if single_file:
        p = Path(single_file)
        paths = [p if p.is_file() else BATCHES_DIR / single_file]
    else:
        paths = sorted(BATCHES_DIR.glob("*.json")) if BATCHES_DIR.is_dir() else []
        if accepted_only:
            manifest = read_json(MANIFEST_PATH)
            paths = [BATCHES_DIR / name for name in manifest.get("accepted", [])]

    for path in paths:
        if not path.is_file():
            errors.append(f"missing batch file: {path}")
            continue
        batch = read_json(path)
        errors.extend(
            f"{path.name}: {err}"
            for err in validate_batch_payload(batch, sources_by_id, pages_by_id, external_targets)
        )

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
    if errors:
        print(f"VALIDATION FAILED ({len(errors)} errors across {count} batch files):")
        for err in errors:
            print(f"  - {err}")
        return 1
    print(f"VALIDATION PASSED ({count} batch files checked, compiled={args.compiled})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
