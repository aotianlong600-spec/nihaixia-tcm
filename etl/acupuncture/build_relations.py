"""Compile typed bidirectional relations for the acupuncture knowledge graph."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "brain_data" / "acupuncture"
MANIFEST_PATH = DATA_DIR / "batch_manifest.json"
BATCHES_DIR = DATA_DIR / "review_batches"
SOURCE_ID = "ni-acupuncture-v2-20100703"


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    accepted_names = manifest.get("accepted", [])

    entity_ids: set[str] = set()
    for fname in ("meridians.json", "acupoints.json", "techniques.json", "conditions.json"):
        payload = json.loads((DATA_DIR / fname).read_text(encoding="utf-8"))
        for item in payload.get("items", []):
            entity_ids.add(item["id"])

    relations: list[dict] = []
    seen_keys: set[tuple[str, str, str]] = set()
    dangling: list[str] = []

    for fname in accepted_names:
        batch = json.loads((BATCHES_DIR / fname).read_text(encoding="utf-8"))
        for rel in batch.get("relations", []):
            if rel.get("from_id") not in entity_ids:
                dangling.append(f"{rel.get('id')}: missing from_id {rel.get('from_id')}")
            if rel.get("to_id") not in entity_ids:
                dangling.append(f"{rel.get('id')}: missing to_id {rel.get('to_id')}")
            key = (rel["relation_type"], rel["from_id"], rel["to_id"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            relations.append(rel)

    if dangling:
        raise RuntimeError(f"Dangling relation references: {dangling}")

    by_type: dict[str, int] = {}
    for rel in relations:
        rtype = rel["relation_type"]
        by_type[rtype] = by_type.get(rtype, 0) + 1

    out_payload = {
        "source_id": SOURCE_ID,
        "accepted_batches": accepted_names,
        "stats": {
            "total": len(relations),
            "approved": sum(1 for r in relations if r.get("review_status") == "approved"),
            "by_type": by_type,
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
