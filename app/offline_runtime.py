"""Install shipped knowledge once, retaining owner edits and all device records."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import tempfile

from . import consultation_core as core, formula_engine, library, offline_pack, storage


def prepare_runtime(data_dir, knowledge_dir):
    data = Path(data_dir).resolve()
    data.mkdir(parents=True, exist_ok=True)
    existing_database = (data/'clinical.sqlite3').is_file()
    storage.initialize(data)
    with closing(storage.connect(data)) as conn:
        library.initialize(conn, data)
        core.initialize(conn)
        for table, sql in offline_pack.SCHEMA.items():
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                conn.execute(sql)
        conn.commit()
    manifest = offline_pack.verify_pack(Path(knowledge_dir))
    pack_id = hashlib.sha256(offline_pack._json_bytes(manifest)).hexdigest()
    marker = data/'knowledge'/'active.json'
    resource = data/'knowledge'/pack_id
    catalog = resource/'open_formula_library.json'
    active = None
    try:
        active = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    if (existing_database and isinstance(active,dict) and active.get('pack_id')==pack_id
            and catalog.is_file() and not catalog.is_symlink()
            and offline_pack._hash(catalog)==manifest['files']['open_formula_library.json']['sha256']):
        result = {'pack_id':pack_id,'installed_rows':0,'tables':manifest['tables'],
                  'formula_library_path':str(catalog),'manifest_path':str(resource/'manifest.json')}
    else:
        result = offline_pack.install_pack(Path(knowledge_dir),data)
        marker.parent.mkdir(exist_ok=True)
        handle, name = tempfile.mkstemp(dir=marker.parent,prefix='.active-',suffix='.tmp')
        import os
        try:
            with os.fdopen(handle,'w',encoding='utf-8') as stream:
                json.dump({'pack_id':result['pack_id']},stream)
                stream.flush();os.fsync(stream.fileno())
            os.replace(name,marker)
        finally:
            Path(name).unlink(missing_ok=True)
    formula_engine.set_library_path(result['formula_library_path'])
    return result
