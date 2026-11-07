"""Export a fresh, knowledge-only pack; never copies the clinical database file."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.offline_pack import export_pack, verify_pack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--verify', type=Path, help='Verify an existing pack without changing it')
    args = parser.parse_args()
    if args.verify:
        if args.data_dir or args.destination: parser.error('--verify cannot be combined with export arguments')
        manifest = verify_pack(args.verify)
    else:
        if not args.data_dir or not args.destination: parser.error('--data-dir and --destination are required')
        manifest = export_pack(args.data_dir, args.destination)
    print(json.dumps({'format':manifest['format'],'version':manifest['version'],'tables':manifest['tables'],'files':len(manifest['files'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
