"""Compile typed relations linking Huangdi Neijing theories, chapters, and sibling TCM modules."""
from __future__ import annotations

import json
from pathlib import Path

from etl.neijing.validate import load_external_target_ids


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "brain_data" / "neijing"
MANIFEST_PATH = DATA_DIR / "batch_manifest.json"
BATCHES_DIR = DATA_DIR / "review_batches"


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    accepted_names = manifest.get("accepted", [])

    neijing_ids: set[str] = set()
    for fname in ("passages.json", "concepts.json"):
        payload = json.loads((DATA_DIR / fname).read_text(encoding="utf-8"))
        for item in payload.get("items", []):
            neijing_ids.add(item["id"])

    external_targets = load_external_target_ids()
    relations: list[dict] = []
    seen_keys: set[tuple[str, str, str]] = set()
    dangling: list[str] = []

    for fname in accepted_names:
        batch = json.loads((BATCHES_DIR / fname).read_text(encoding="utf-8"))
        for rel in batch.get("relations", []):
            from_id = rel.get("from_id", "")
            to_id = rel.get("to_id", "")
            to_mod = rel.get("to_module", "")
            if from_id not in neijing_ids:
                dangling.append(f"{rel.get('id')}: missing neijing from_id {from_id}")
            if to_mod == "neijing":
                if to_id not in neijing_ids:
                    dangling.append(f"{rel.get('id')}: missing neijing to_id {to_id}")
            elif to_id not in external_targets.get(to_mod, set()):
                dangling.append(f"{rel.get('id')}: missing {to_mod} to_id {to_id}")

            key = (rel.get("relation_type", ""), from_id, to_id)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            relations.append(rel)

    if dangling:
        raise RuntimeError(f"Dangling Neijing relation references: {dangling}")

    by_type: dict[str, int] = {}
    by_target_module: dict[str, int] = {}
    for rel in relations:
        rtype = rel["relation_type"]
        tmod = rel["to_module"]
        by_type[rtype] = by_type.get(rtype, 0) + 1
        by_target_module[tmod] = by_target_module.get(tmod, 0) + 1

    out_payload = {
        "schema_version": "1.0.0",
        "sources": ["ni-neijing-vol1-pdf", "ni-neijing-vol2-pdf"],
        "accepted_batches": accepted_names,
        "stats": {
            "total": len(relations),
            "approved": sum(1 for r in relations if r.get("review_status") == "approved"),
            "by_type": by_type,
            "by_target_module": by_target_module,
        },
        "items": relations,
    }
    (DATA_DIR / "relations.json").write_text(
        json.dumps(out_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(out_payload["stats"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
