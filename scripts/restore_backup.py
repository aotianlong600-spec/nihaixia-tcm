"""Restore an encrypted backup into a new or empty local directory."""
import argparse
from getpass import getpass
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.backup import restore_backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    try:
        password = getpass("Backup password (not stored): ")
        print(json.dumps(restore_backup(args.backup.read_bytes(), password, args.destination), ensure_ascii=True))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Restore failed: {exc}\n")


if __name__ == "__main__":
    main()
