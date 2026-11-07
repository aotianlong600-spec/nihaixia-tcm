from pathlib import Path
import sqlite3

from app import formula_engine
from app.offline_pack import export_pack


def test_same_pack_does_not_reimport_over_local_database_edits(tmp_path):
    from test_offline_pack import sample
    from app.offline_runtime import prepare_runtime
    source, _, pdf_sha = sample(tmp_path)
    pack, data = tmp_path/'pack', tmp_path/'device'
    export_pack(source, pack)
    try:
        first = prepare_runtime(data, pack)
        with sqlite3.connect(data/'clinical.sqlite3') as conn:
            conn.execute('UPDATE documents SET title=? WHERE id=?', ('我的本地标题修订',pdf_sha))
        again = prepare_runtime(data, pack)
        assert again['installed_rows'] == 0
        assert first['pack_id'] == again['pack_id']
        with sqlite3.connect(data/'clinical.sqlite3') as conn:
            assert conn.execute('SELECT title FROM documents WHERE id=?',(pdf_sha,)).fetchone()[0] == '我的本地标题修订'
    finally:
        formula_engine.set_library_path()


def test_rebuilt_device_database_can_install_knowledge_again(tmp_path):
    from test_offline_pack import sample
    from app.offline_runtime import prepare_runtime
    source, _, _ = sample(tmp_path)
    pack, data = tmp_path/'pack', tmp_path/'device'
    export_pack(source, pack)
    try:
        prepare_runtime(data, pack)
        (data/'clinical.sqlite3').unlink()
        rebuilt = prepare_runtime(data, pack)
        assert rebuilt['installed_rows'] > 0
        with sqlite3.connect(data/'clinical.sqlite3') as conn:
            assert conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0] == 1
    finally:
        formula_engine.set_library_path()
