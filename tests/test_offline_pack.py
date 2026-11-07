import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from app import decision, library, research, storage

PRIVATE = 'PHI-AND-SECRET-MUST-NOT-BE-IN-KNOWLEDGE-9f74c5'


def sample(tmp_path):
    data = tmp_path / 'source'
    storage.initialize(data)
    raw = '合成原文😀：观察测试症。'
    content = raw.encode('utf-8')
    sha = hashlib.sha256(content).hexdigest()
    pdf = b'%PDF-1.7\nsynthetic-original-only'
    pdf_sha = hashlib.sha256(pdf).hexdigest()
    with storage.connect(data) as conn:
        library.initialize(conn, data)
        research.initialize_research(conn)
        decision.initialize(conn)
        conn.execute('PRAGMA secure_delete=OFF')
        conn.execute('INSERT INTO patients VALUES(?,?,?,?)', ('deleted', PRIVATE, PRIVATE * 20, 'synthetic'))
        conn.execute("DELETE FROM patients WHERE id='deleted'")
        conn.execute('INSERT INTO patients VALUES(?,?,?,?)', ('kept', 'patient', PRIVATE, 'synthetic'))
        conn.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?)', (pdf_sha, '合成PDF', pdf_sha, 1, 'synthetic', '', 'source-time'))
        conn.execute('INSERT INTO pages(document_id,physical_page,raw_text,search_text,printed_page,warning,extraction_method,reviewer,note,reviewed_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                     (pdf_sha, 1, '合成PDF正文', '合成pdf正文', '150', '', 'synthetic', PRIVATE, PRIVATE, PRIVATE))
        conn.execute('INSERT INTO text_sources VALUES(?,?,?,?,?)', (sha, '合成文稿', 'txt', 1, 'utf-8'))
        conn.execute('INSERT INTO source_units VALUES(?,?,?,?,?)', (sha, 1, '{"kind":"paragraph_range","start":1,"end":1}', raw, '合成原文观察测试症'))
        conn.executemany('INSERT INTO source_catalog VALUES(?,?)', [(sha, 'reference'), (pdf_sha, 'reference')])
        conn.execute('INSERT INTO research_entries VALUES(?,?,?,?)', ('literature', pdf_sha,
                     json.dumps({'id':'literature','document_sha256':pdf_sha,'physical_pages':[1],'title':'synthetic','classic_quote':'合成PDF正文','features':[]}), 'source-time'))
        anchor = {'id':'a','source_id':sha,'unit_no':1,'start':0,'end':len(raw),'quote':raw,
                  'unit_sha256':hashlib.sha256(raw.encode()).hexdigest(),'layer':'reference_author','attribution':'synthetic','version_label':'one'}
        package = {'format_version':1,'id':'synthetic-package','version':1,'title':'合成包','anchors':[anchor],
                   'claims':[{'id':'need','kind':'necessary','text':'合成必要条件','anchor_ids':['a'],'inference':'literal','scope':'synthetic','limitations':[]}],
                   'formulas':[],'nodes':[{'id':'n','label':'合成节点','kind':'pattern','scope':'synthetic','scope_claim_ids':[],
                     'formula_version_id':None,'conditions':[{'id':'c','role':'required','expr':{'fact':'测试症'},'claim_ids':['need']}],
                     'questions':[{'key':'测试症','question':'是否存在测试症？','reason':'synthetic','claim_ids':['need']}],'limitations':[]}],
                   'edges':[],'modifications':[]}
        decision.import_package(conn, package)
    (data / 'originals' / f'{sha}.txt').write_bytes(content)
    (data / 'originals' / f'{pdf_sha}.pdf').write_bytes(pdf)
    (data / 'model-secret.dpapi').write_bytes(PRIVATE.encode())
    assert PRIVATE.encode() in (data / 'clinical.sqlite3').read_bytes()
    return data, sha, pdf_sha


def runtime(tmp_path):
    data = tmp_path / 'runtime'
    storage.initialize(data)
    with storage.connect(data) as conn:
        library.initialize(conn, data)
        research.initialize_research(conn)
        decision.initialize(conn)
        conn.execute('INSERT INTO patients VALUES(?,?,?,?)', ('local', 'KEEP-LOCAL', PRIVATE, 'synthetic'))
    (data / 'model-secret.dpapi').write_bytes(b'local-key-stays')
    return data


def rewrite_manifest(pack):
    manifest = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))
    for name, detail in manifest['files'].items():
        path = pack / name
        detail['bytes'] = path.stat().st_size
        detail['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (pack / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    return manifest


def test_export_is_fresh_allowlisted_knowledge_without_deleted_or_live_private_rows(tmp_path):
    from app.offline_pack import export_pack, verify_pack, TABLES

    source, sha, pdf_sha = sample(tmp_path)
    pack = tmp_path / 'pack'
    manifest = export_pack(source, pack)
    assert verify_pack(pack)['tables']['pages'] == 1
    assert set(manifest['tables']) == set(TABLES)
    for path in pack.rglob('*'):
        if path.is_file():
            assert PRIVATE.encode() not in path.read_bytes(), path.name
    with sqlite3.connect(pack / 'knowledge.sqlite3') as conn, sqlite3.connect(source / 'clinical.sqlite3') as original:
        assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} == set(TABLES)
        assert conn.execute('PRAGMA freelist_count').fetchone()[0] == 0
        assert conn.execute('SELECT reviewer,note,reviewed_at FROM pages').fetchone() == (None,None,None)
        assert conn.execute('SELECT payload FROM decision_packages').fetchone() == original.execute('SELECT payload FROM decision_packages').fetchone()
        assert conn.execute('SELECT printed_page FROM pages').fetchone()[0] == '150'
    for name in [f'{sha}.txt', f'{pdf_sha}.pdf']:
        assert (pack / 'originals' / name).read_bytes() == (source / 'originals' / name).read_bytes()


def test_install_is_repeatable_preserves_personal_tables_and_exposes_formula_catalog(tmp_path):
    from app.offline_pack import export_pack, install_pack

    source, _, _ = sample(tmp_path)
    pack = tmp_path / 'pack'; export_pack(source, pack)
    data = runtime(tmp_path)
    first = install_pack(pack, data)
    second = install_pack(pack, data)
    assert first['installed_rows'] > 0 and second['installed_rows'] == 0
    assert Path(first['formula_library_path']).read_bytes() == (pack / 'open_formula_library.json').read_bytes()
    with storage.connect(data) as conn:
        assert tuple(conn.execute('SELECT code,notes FROM patients').fetchone()) == ('KEEP-LOCAL', PRIVATE)
        assert len(decision.evaluate(conn, [])['nodes']) == 1
    assert (data / 'model-secret.dpapi').read_bytes() == b'local-key-stays'


@pytest.mark.parametrize('bad_path', ['../outside', '/absolute', 'originals/../../outside', r'originals\escape', 'C:/escape'])
def test_manifest_paths_cannot_escape_or_name_unregistered_files(tmp_path, bad_path):
    from app.offline_pack import export_pack, verify_pack

    source, _, _ = sample(tmp_path); pack = tmp_path / 'pack'; export_pack(source, pack)
    manifest = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))
    manifest['files'][bad_path] = {'bytes':0,'sha256':'0'*64}
    (pack / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError): verify_pack(pack)


def test_tamper_extra_file_or_database_table_is_rejected(tmp_path):
    from app.offline_pack import export_pack, verify_pack

    source, _, _ = sample(tmp_path); pack = tmp_path / 'pack'; export_pack(source, pack)
    extra = pack / 'model-secret.dpapi'; extra.write_bytes(b'never-allowed')
    with pytest.raises(ValueError): verify_pack(pack)
    extra.unlink()
    with sqlite3.connect(pack / 'knowledge.sqlite3') as conn:
        conn.execute('CREATE TABLE patients(secret TEXT)')
        conn.execute('INSERT INTO patients VALUES(?)', (PRIVATE,))
    rewrite_manifest(pack)
    with pytest.raises(ValueError): verify_pack(pack)


def test_valid_file_hashes_do_not_hide_a_changed_source_anchor(tmp_path):
    from app.offline_pack import export_pack, verify_pack

    source, _, _ = sample(tmp_path); pack = tmp_path / 'pack'; export_pack(source, pack)
    with sqlite3.connect(pack / 'knowledge.sqlite3') as conn:
        conn.execute("UPDATE source_units SET raw_text='different source'")
    rewrite_manifest(pack)
    with pytest.raises(ValueError, match='anchor|原文|锚点|来源'):
        verify_pack(pack)


def test_conflicting_existing_identity_rolls_back_the_entire_install(tmp_path):
    from app.offline_pack import export_pack, install_pack

    source, sha, _ = sample(tmp_path); pack = tmp_path / 'pack'; export_pack(source, pack)
    data = runtime(tmp_path)
    with storage.connect(data) as conn:
        conn.execute('INSERT INTO text_sources VALUES(?,?,?,?,?)', (sha, 'local conflicting title', 'txt', 1, 'utf-8'))
    with pytest.raises(ValueError, match='冲突|conflict'):
        install_pack(pack, data)
    with storage.connect(data) as conn:
        assert conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0] == 0
        assert conn.execute('SELECT title FROM text_sources').fetchone()[0] == 'local conflicting title'
        assert conn.execute('SELECT code FROM patients').fetchone()[0] == 'KEEP-LOCAL'
    assert not list((data / 'originals').iterdir())


def test_export_will_not_overwrite_an_occupied_directory(tmp_path):
    from app.offline_pack import export_pack

    source, _, _ = sample(tmp_path)
    destination = tmp_path / 'occupied'; destination.mkdir()
    marker = destination / 'keep'; marker.write_text('preserve')
    with pytest.raises(ValueError): export_pack(source, destination)
    assert marker.read_text() == 'preserve'


def test_repeat_export_has_stable_manifest_and_local_review_metadata_stays_local(tmp_path):
    from app.offline_pack import export_pack, install_pack

    source, _, _ = sample(tmp_path)
    one = tmp_path/'one'; two = tmp_path/'two'
    assert export_pack(source, one) == export_pack(source, two)
    data = runtime(tmp_path); install_pack(one,data)
    with storage.connect(data) as conn:
        conn.execute('UPDATE pages SET reviewer=?,note=?,reviewed_at=?',(PRIVATE,PRIVATE,PRIVATE))
    assert install_pack(one,data)['installed_rows'] == 0
    with storage.connect(data) as conn:
        assert tuple(conn.execute('SELECT reviewer,note,reviewed_at FROM pages').fetchone()) == (PRIVATE,PRIVATE,PRIVATE)


def test_disk_failure_rolls_back_rows_and_only_removes_new_files(tmp_path, monkeypatch):
    import errno
    from app import offline_pack as pack_module

    source, _, _ = sample(tmp_path); pack = tmp_path/'pack'; pack_module.export_pack(source,pack)
    data = runtime(tmp_path)
    original_link = pack_module.os.link
    calls = 0
    def full_disk(src,dst):
        nonlocal calls
        calls += 1
        if calls == 2: raise OSError(errno.ENOSPC,'synthetic full disk')
        return original_link(src,dst)
    monkeypatch.setattr(pack_module.os,'link',full_disk)
    with pytest.raises(ValueError,match='磁盘空间不足'):
        pack_module.install_pack(pack,data)
    with storage.connect(data) as conn:
        assert conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0] == 0
        assert conn.execute('SELECT code FROM patients').fetchone()[0] == 'KEEP-LOCAL'
    assert not list((data/'originals').iterdir())
    assert (data/'model-secret.dpapi').read_bytes() == b'local-key-stays'


def test_symlink_original_is_rejected(tmp_path):
    from app.offline_pack import export_pack, verify_pack

    source, sha, _ = sample(tmp_path); pack=tmp_path/'pack'; export_pack(source,pack)
    original=pack/'originals'/f'{sha}.txt'; content=original.read_bytes()
    outside=tmp_path/'outside.txt'; outside.write_bytes(content)
    original.unlink()
    try: original.symlink_to(outside)
    except OSError: pytest.skip('This Windows account cannot create symlinks')
    with pytest.raises(ValueError,match='链接|越界'):
        verify_pack(pack)


def test_export_does_not_follow_a_view_into_personal_tables(tmp_path):
    from app.offline_pack import export_pack

    source, _, _ = sample(tmp_path)
    with sqlite3.connect(source/'clinical.sqlite3') as conn:
        conn.execute('DROP TABLE source_catalog')
        conn.execute("CREATE VIEW source_catalog AS SELECT id,(SELECT notes FROM patients WHERE id='kept') AS corpus_role FROM text_sources UNION ALL SELECT id,'reference' FROM documents")
    with pytest.raises((ValueError,sqlite3.DatabaseError)):
        export_pack(source,tmp_path/'pack')
    assert not (tmp_path/'pack').exists()


def test_database_trailing_bytes_cannot_hide_unlisted_content(tmp_path):
    from app.offline_pack import export_pack, verify_pack

    source, _, _ = sample(tmp_path); pack=tmp_path/'pack'; export_pack(source,pack)
    with (pack/'knowledge.sqlite3').open('ab') as stream:
        stream.write(PRIVATE.encode())
    rewrite_manifest(pack)
    with pytest.raises(ValueError): verify_pack(pack)


def test_install_works_when_android_disallows_hardlinks(tmp_path, monkeypatch):
    from app.offline_pack import export_pack, install_pack
    import errno
    import os
    source, sha, _ = sample(tmp_path)
    pack = tmp_path/'pack';export_pack(source,pack)
    device = runtime(tmp_path)
    def denied(*args, **kwargs):
        raise PermissionError(errno.EPERM,'synthetic Android hardlink denial')
    monkeypatch.setattr(os,'link',denied)
    result = install_pack(pack,device)
    assert result['installed_rows'] > 0
    assert (device/'originals'/f'{sha}.txt').read_bytes() == (source/'originals'/f'{sha}.txt').read_bytes()
    with sqlite3.connect(device/'clinical.sqlite3') as conn:
        assert conn.execute("SELECT notes FROM patients WHERE id='local'").fetchone()[0] == PRIVATE
