"""Import the locally prepared expansion manifests into the existing library."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import library


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--pdf-manifest', type=Path, required=True)
    parser.add_argument('--text-manifest', type=Path, required=True)
    args = parser.parse_args()
    with sqlite3.connect(args.data_dir / 'clinical.sqlite3', timeout=30) as conn:
        result = library.import_expansion(conn, args.data_dir, args.pdf_manifest, args.text_manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
