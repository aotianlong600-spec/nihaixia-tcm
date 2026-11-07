"""Build a starter pack with the bundled formula index and no imported corpus."""
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.offline_pack import SCHEMA, export_pack


if __name__ == '__main__':
    destination = ROOT / 'knowledge'
    if destination.exists():
        sys.exit('knowledge/ already exists. Use your existing knowledge pack.')
    with TemporaryDirectory(prefix='.starter-knowledge-', dir=ROOT) as temporary:
        source = Path(temporary)
        with closing(sqlite3.connect(source / 'clinical.sqlite3')) as db, db:
            for statement in SCHEMA.values():
                db.execute(statement)
        export_pack(source, destination)
    print('Starter knowledge pack created in knowledge/.')
