from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import stat
import zipfile

import pytest

from app import browser_library, formula_engine, library, offline_pack, offline_runtime, storage


@pytest.fixture(autouse=True)
def retain_catalog():
    previous = formula_engine.library_path()
    yield
    formula_engine.set_library_path(previous)


def corpus(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    content = '合成资料：观察测试症。'.encode()
    text_id = hashlib.sha256(content).hexdigest()
    pdf = b'%PDF-1.7\nsynthetic-test-original'
    pdf_id = hashlib.sha256(pdf).hexdigest()
    with closing(sqlite3.connect(source / 'clinical.sqlite3')) as conn, conn:
        for sql in offline_pack.SCHEMA.values():
            conn.execute(sql)
        conn.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?)', (pdf_id, '测试PDF', pdf_id, 1, 'synthetic', '', 'test'))
        conn.execute('INSERT INTO pages(document_id,physical_page,raw_text,search_text,warning,extraction_method) VALUES(?,?,?,?,?,?)',
                     (pdf_id, 1, '合成PDF文字', '合成pdf文字', '', 'synthetic'))
        conn.execute('INSERT INTO text_sources VALUES(?,?,?,?,?)', (text_id, '测试文本', 'txt', 1, 'utf-8'))
        conn.execute('INSERT INTO source_units VALUES(?,?,?,?,?)', (text_id, 1, '{"kind":"paragraph_range","start":1,"end":1}', content.decode(), '合成资料观察测试症'))
        conn.executemany('INSERT INTO source_catalog VALUES(?,?)', [(text_id, 'reference'), (pdf_id, 'reference')])
    (source / 'originals').mkdir()
    (source / 'originals' / f'{text_id}.txt').write_bytes(content)
    (source / 'originals' / f'{pdf_id}.pdf').write_bytes(pdf)
    pack = tmp_path / 'pack'
    offline_pack.export_pack(source, pack)
    return pack, text_id, pdf_id


def archive(tmp_path, pack, prefix=''):
    result = tmp_path / 'knowledge.zip'
    with zipfile.ZipFile(result, 'w', compression=zipfile.ZIP_DEFLATED) as out:
        for path in pack.rglob('*'):
            if path.is_file():
                out.write(path, prefix + path.relative_to(pack).as_posix())
    return result


def runtime(tmp_path):
    data = tmp_path / 'runtime'
    source = tmp_path / 'empty-source'
    source.mkdir()
    with closing(sqlite3.connect(source / 'clinical.sqlite3')) as conn, conn:
        for sql in offline_pack.SCHEMA.values():
            conn.execute(sql)
    pack = tmp_path / 'empty-pack'
    offline_pack.export_pack(source, pack)
    offline_runtime.prepare_runtime(data, pack)
    with storage.connect(data) as conn:
        conn.execute('INSERT INTO consultations VALUES(?,?,?,?,?,?)', ('local', '保留合成记录', '{}', 1, 'test', 'test'))
    (data / 'models').mkdir()
    (data / 'models' / 'synthetic-sentinel').write_bytes(b'keep-model-config')
    return data


@pytest.mark.parametrize('prefix', ['', 'knowledge/'])
def test_import_retains_local_records_original_bytes_and_active_catalog(tmp_path, prefix):
    pack, text_id, pdf_id = corpus(tmp_path)
    data = runtime(tmp_path)
    result = browser_library.install_archive(archive(tmp_path, pack, prefix), data)
    assert result['metadata']['sources'] == 2
    assert result['metadata']['pdf_pages'] == 1
    assert result['metadata']['text_units'] == 1
    assert result['tables']['documents'] == 1
    assert result['active'] == {'pack_id': result['pack_id']}
    assert set(result['assets']) == {
        f'originals/{text_id}.txt', f'originals/{pdf_id}.pdf', 'knowledge/active.json',
        f"knowledge/{result['pack_id']}/manifest.json", f"knowledge/{result['pack_id']}/open_formula_library.json",
    }
    assert formula_engine.library_path() == Path(result['formula_library_path'])
    with storage.connect(data) as conn:
        assert conn.execute('SELECT title FROM consultations').fetchone()[0] == '保留合成记录'
        assert len(library.search(conn, '测试症')) == 1
    assert (data / 'models' / 'synthetic-sentinel').read_bytes() == b'keep-model-config'
    assert browser_library.read_original(data, text_id) == ('text/plain', (pack / 'originals' / f'{text_id}.txt').read_bytes(), f'{text_id}.txt')
    assert browser_library.read_original(data, pdf_id)[0] == 'application/pdf'
    assert browser_library.install_archive(tmp_path / 'knowledge.zip', data)['installed_rows'] == 0


def test_active_catalog_is_recoverable_and_tampered_catalog_is_rejected(tmp_path):
    pack, _, _ = corpus(tmp_path)
    data = runtime(tmp_path)
    result = browser_library.install_archive(archive(tmp_path, pack), data)
    formula_engine.set_library_path()
    assert browser_library.activate_installed(data)['pack_id'] == result['pack_id']
    assert formula_engine.library_path() == Path(result['formula_library_path'])
    Path(result['formula_library_path']).write_text('{"formulas":[],"patterns":[]}')
    with pytest.raises(ValueError):
        browser_library.activate_installed(data)


def test_explicit_pack_reactivates_after_public_runtime_rewrites_the_marker(tmp_path):
    pack, _, _ = corpus(tmp_path)
    data = runtime(tmp_path)
    result = browser_library.install_archive(archive(tmp_path, pack), data)
    offline_runtime.prepare_runtime(data, tmp_path / 'empty-pack')
    assert json.loads((data / 'knowledge' / 'active.json').read_text()) != result['active']
    assert browser_library.activate_installed(data, result['pack_id'])['active'] == result['active']
    assert json.loads((data / 'knowledge' / 'active.json').read_text()) == result['active']
    assert formula_engine.library_path() == Path(result['formula_library_path'])
    with pytest.raises(ValueError):
        browser_library.activate_installed(data, '../escape')


def test_browser_units_use_full_text_and_registered_original_links(tmp_path):
    pack, text_id, pdf_id = corpus(tmp_path)
    data = runtime(tmp_path)
    browser_library.install_archive(archive(tmp_path, pack), data)
    with storage.connect(data) as conn:
        unit = browser_library.browser_unit(conn, data, pdf_id, 1)
        assert unit['raw_text'] == '合成PDF文字'
        assert unit['content_scope'] == 'full_unit'
        assert unit['original_available'] is True
        assert unit['original_url'] == f'/library/sources/{pdf_id}/original'
        assert 'image_url' not in unit
        assert browser_library.browser_unit(conn, data, text_id, 2) is None
    (data / 'originals' / f'{text_id}.txt').write_bytes(b'corrupted')
    with pytest.raises(ValueError):
        browser_library.read_original(data, text_id)
    with pytest.raises(ValueError):
        browser_library.read_original(data, '../clinical.sqlite3')
    with pytest.raises(ValueError):
        browser_library.read_original(data, '0' * 64)


@pytest.mark.parametrize('name', ['../escape', '/absolute', r'originals\escape', 'C:/escape', 'originals/../escape', 'a//b', './manifest.json', 'extra.txt'])
def test_zip_paths_are_rejected_before_changing_runtime(tmp_path, name):
    pack, _, _ = corpus(tmp_path)
    data = runtime(tmp_path)
    path = archive(tmp_path, pack)
    before = (data / 'clinical.sqlite3').read_bytes()
    with zipfile.ZipFile(path, 'a') as out:
        out.writestr(name, b'not-allowed')
    with pytest.raises(ValueError):
        browser_library.install_archive(path, data)
    assert (data / 'clinical.sqlite3').read_bytes() == before
    assert not (tmp_path / 'escape').exists()


def test_zip_symlinks_duplicates_and_unlisted_bytes_are_rejected(tmp_path):
    pack, _, _ = corpus(tmp_path)
    data = runtime(tmp_path)
    path = archive(tmp_path, pack)
    info = zipfile.ZipInfo('originals/' + '0' * 64 + '.txt')
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, 'a') as out:
        out.writestr(info, '../clinical.sqlite3')
    with pytest.raises(ValueError):
        browser_library.install_archive(path, data)
    path = archive(tmp_path, pack)
    with pytest.warns(UserWarning), zipfile.ZipFile(path, 'a') as out:
        out.writestr('manifest.json', (pack / 'manifest.json').read_bytes())
    with pytest.raises(ValueError):
        browser_library.install_archive(path, data)
    (pack / 'open_formula_library.json').write_bytes(b'changed')
    with pytest.raises(ValueError):
        browser_library.install_archive(archive(tmp_path, pack), data)


def test_zip_resource_limits_are_checked_before_extracting(tmp_path, monkeypatch):
    pack, _, _ = corpus(tmp_path)
    data = runtime(tmp_path)
    path = archive(tmp_path, pack)
    monkeypatch.setattr(browser_library, 'MAX_EXPANDED_BYTES', 1)
    with pytest.raises(ValueError):
        browser_library.install_archive(path, data)
    monkeypatch.setattr(browser_library, 'MAX_EXPANDED_BYTES', 256 * 1024 * 1024)
    monkeypatch.setattr(browser_library, 'MAX_ARCHIVE_FILES', 1)
    with pytest.raises(ValueError):
        browser_library.install_archive(path, data)


def test_manifest_declared_sizes_and_archive_size_are_enforced(tmp_path, monkeypatch):
    pack, _, _ = corpus(tmp_path)
    data = runtime(tmp_path)
    manifest = json.loads((pack / 'manifest.json').read_text())
    manifest['files']['open_formula_library.json']['bytes'] += 1
    (pack / 'manifest.json').write_text(json.dumps(manifest))
    path = archive(tmp_path, pack)
    before = (data / 'clinical.sqlite3').read_bytes()
    with pytest.raises(ValueError, match='体积'):
        browser_library.install_archive(path, data)
    monkeypatch.setattr(browser_library, 'MAX_ARCHIVE_BYTES', 1)
    with pytest.raises(ValueError, match='体积'):
        browser_library.install_archive(path, data)
    assert (data / 'clinical.sqlite3').read_bytes() == before


def test_conflict_rolls_back_import_and_retains_existing_files(tmp_path):
    pack, text_id, _ = corpus(tmp_path)
    data = runtime(tmp_path)
    with storage.connect(data) as conn:
        conn.execute('INSERT INTO text_sources VALUES(?,?,?,?,?)', (text_id, 'conflicting title', 'txt', 1, 'utf-8'))
    before = formula_engine.library_path()
    with pytest.raises(ValueError, match='冲突'):
        browser_library.install_archive(archive(tmp_path, pack), data)
    assert formula_engine.library_path() == before
    with storage.connect(data) as conn:
        assert conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0] == 0
        assert conn.execute('SELECT title FROM consultations').fetchone()[0] == '保留合成记录'
    assert (data / 'models' / 'synthetic-sentinel').read_bytes() == b'keep-model-config'
