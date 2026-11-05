import argparse
from contextlib import closing
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import research, storage
from app.engine import validate_rule


def main():
    parser = argparse.ArgumentParser(description="Import locally curated, clinically unreviewed literature entries")
    parser.add_argument("source", type=Path)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    storage.initialize(args.data_dir)
    with closing(storage.connect(args.data_dir)) as conn, conn:
        research.initialize_research(conn)
        print(research.import_research(conn, args.source))
        count = 0
        for entry in research.list_research(conn):
            draft = validate_rule(research.rule_draft(entry))
            count += conn.execute("INSERT OR IGNORE INTO rules VALUES(?,?,?,?)", (draft["id"], storage.encode(draft), "{}", storage.now())).rowcount
        print({"unpublished_rule_drafts_created": count})


if __name__ == "__main__":
    main()
