"""Import one immutable source-mapped package; no approval or publication workflow."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import decision, library, storage


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',type=Path)
    parser.add_argument('--data-dir',type=Path,default=Path(__file__).resolve().parents[1]/'data')
    args=parser.parse_args()
    if args.package.stat().st_size > 32*1024*1024:
        parser.error('package exceeds 32 MiB')
    payload=json.loads(args.package.read_text(encoding='utf-8-sig'))
    storage.initialize(args.data_dir)
    with storage.connect(args.data_dir) as conn:
        library.initialize(conn,args.data_dir)
        decision.initialize(conn)
        for source_id in {a['source_id'] for a in payload['anchors']}:
            original=library.original_path(conn,args.data_dir,source_id)
            if hashlib.sha256(original.read_bytes()).hexdigest()!=source_id:
                raise ValueError('registered original hash mismatch')
        result=decision.import_package(conn,payload)
        print(json.dumps({'result':result,'coverage':decision.coverage(conn)},ensure_ascii=True))


if __name__=='__main__':
    main()
