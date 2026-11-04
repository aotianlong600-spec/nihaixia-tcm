"""Import an audited local corpus without re-extracting the PDFs."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.knowledge import import_audit, init_knowledge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(args.data_dir / "clinical.sqlite3") as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            init_knowledge(conn, args.data_dir)
            result = import_audit(conn, args.data_dir, args.manifest)
        print(json.dumps(result, ensure_ascii=True))
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f"Audit import failed: {exc}\n")


if __name__ == "__main__":
    main()
