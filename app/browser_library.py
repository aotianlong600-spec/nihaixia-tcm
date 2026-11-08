"""Browser knowledge imports; persistence and whole-request rollback belong to the worker."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import zipfile

from . import formula_engine, knowledge, library, offline_pack

MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_FILES = 4096
_MIME = {'pdf': 'application/pdf', 'txt': 'text/plain',
         'md': 'text/markdown', 'doc': 'application/msword',
         'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


def _allowed(name):
    return name in ('knowledge.sqlite3', 'open_formula_library.json') or offline_pack.ORIGINAL.fullmatch(name)


def _manifest(raw):
    if len(raw) > offline_pack.MAX_MANIFEST_BYTES:
        raise ValueError('知识包清单过大')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=offline_pack._unique_object)
    if (not isinstance(value, dict) or set(value) != {'format', 'version', 'engine_analysis_revision', 'metadata_policy', 'files', 'tables', 'packages'}
            or value['format'] != offline_pack.FORMAT or type(value['version']) is not int or value['version'] != offline_pack.VERSION
            or type(value['engine_analysis_revision']) is not int or value['engine_analysis_revision'] not in offline_pack.SUPPORTED_ANALYSIS_REVISIONS
            or value['metadata_policy'] != offline_pack.METADATA_POLICY):
        raise ValueError('知识包清单格式或引擎版本不兼容')
    files, tables = value['files'], value['tables']
    if (not isinstance(files, dict) or not 2 <= len(files) <= MAX_ARCHIVE_FILES
            or not {'knowledge.sqlite3', 'open_formula_library.json'} <= set(files)
            or not isinstance(tables, dict) or set(tables) != set(offline_pack.TABLES)
            or any(type(n) is not int or n < 0 for n in tables.values()) or not isinstance(value['packages'], list)):
        raise ValueError('知识包文件或表清单无效')
    for name, detail in files.items():
        if (not _allowed(name) or not isinstance(detail, dict) or set(detail) != {'bytes', 'sha256'}
                or type(detail['bytes']) is not int or not 0 <= detail['bytes'] <= MAX_EXPANDED_BYTES
                or not isinstance(detail['sha256'], str) or not offline_pack.SHA.fullmatch(detail['sha256'])):
            raise ValueError('知识包文件路径或校验字段无效')
    if sum(detail['bytes'] for detail in files.values()) > MAX_EXPANDED_BYTES:
        raise ValueError('知识包解压体积超出浏览器范围')
    return value


def _members(archive):
    infos = archive.infolist()
    if not 1 <= len(infos) <= MAX_ARCHIVE_FILES + 3:
        raise ValueError('知识包文件数量超出浏览器范围')
    found = {}
    for info in infos:
        name = info.filename
        parts = name.rstrip('/').split('/')
        kind = stat.S_IFMT(info.external_attr >> 16)
        if (name != info.orig_filename or '\\' in name or any(ord(c) < 32 for c in name)
                or any(not part or part in ('.', '..') or ':' in part for part in parts)
                or kind not in (0, stat.S_IFREG, stat.S_IFDIR)
                or (kind == stat.S_IFDIR and not info.is_dir())
                or name in found or info.flag_bits & 1
                or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise ValueError('知识包ZIP包含重复、链接或不安全路径')
        found[name] = info
    manifests = [name for name, info in found.items() if not info.is_dir() and name.split('/')[-1] == 'manifest.json']
    if len(manifests) != 1 or len(manifests[0].split('/')) > 2:
        raise ValueError('知识包ZIP需要根清单或单层外部目录')
    prefix = manifests[0][:-len('manifest.json')]
    members = {}
    for name, info in found.items():
        if not name.startswith(prefix):
            raise ValueError('知识包ZIP包含包外文件')
        relative = name[len(prefix):]
        if info.is_dir():
            if relative not in ('', 'originals/'):
                raise ValueError('知识包ZIP包含未允许目录')
            continue
        if relative != 'manifest.json' and not _allowed(relative):
            raise ValueError('知识包ZIP包含未允许文件')
        members[relative] = info
    if len(members) > MAX_ARCHIVE_FILES or sum(info.file_size for info in members.values()) > MAX_EXPANDED_BYTES:
        raise ValueError('知识包文件数量或解压体积超出浏览器范围')
    return members


def _details(data, pack_id, manifest):
    relative = f'knowledge/{pack_id}'
    return {'format': manifest['format'], 'version': manifest['version'], 'pack_id': pack_id,
            'installed_rows': 0, 'tables': manifest['tables'],
            'formula_library_path': str(data / relative / 'open_formula_library.json'),
            'manifest_path': str(data / relative / 'manifest.json'),
            'active': {'pack_id': pack_id},
            'metadata': {'sources': manifest['tables']['documents'] + manifest['tables']['text_sources'],
                         'pdf_pages': manifest['tables']['pages'], 'text_units': manifest['tables']['source_units'],
                         'originals': sum(bool(offline_pack.ORIGINAL.fullmatch(name)) for name in manifest['files']),
                         'bytes': sum(detail['bytes'] for detail in manifest['files'].values())},
            'assets': sorted([name for name in manifest['files'] if offline_pack.ORIGINAL.fullmatch(name)]
                             + [relative + '/manifest.json', relative + '/open_formula_library.json', 'knowledge/active.json'])}


def activate_installed(data_dir, pack_id=None):
    """Reactivate persisted assets after the public starter runtime has initialized."""
    data = offline_pack._root(data_dir)
    marker = data / 'knowledge' / 'active.json'
    current = None
    if marker.exists():
        marker = offline_pack._file(data, 'knowledge/active.json')
        if marker.stat().st_size > 4096:
            raise ValueError('活动知识包标记无效')
        current = json.loads(marker.read_text(encoding='utf-8'), object_pairs_hook=offline_pack._unique_object)
        if not isinstance(current, dict) or set(current) != {'pack_id'}:
            raise ValueError('活动知识包标记无效')
    if pack_id is None:
        if current is None:
            return None
        pack_id = current['pack_id']
    if not isinstance(pack_id, str) or not offline_pack.SHA.fullmatch(pack_id):
        raise ValueError('活动知识包身份无效')
    resource = f'knowledge/{pack_id}/'
    manifest_file = offline_pack._file(data, resource + 'manifest.json')
    if manifest_file.stat().st_size > offline_pack.MAX_MANIFEST_BYTES:
        raise ValueError('知识包清单过大')
    manifest = _manifest(manifest_file.read_bytes())
    if hashlib.sha256(offline_pack._json_bytes(manifest)).hexdigest() != pack_id:
        raise ValueError('活动知识包清单身份不匹配')
    catalog = offline_pack._file(data, resource + 'open_formula_library.json')
    detail = manifest['files']['open_formula_library.json']
    if catalog.stat().st_size != detail['bytes'] or offline_pack._hash(catalog) != detail['sha256']:
        raise ValueError('活动知识包方剂资源身份不匹配')
    previous = formula_engine.library_path()
    formula_engine.set_library_path(catalog)
    try:
        if current != {'pack_id': pack_id}:
            handle, temporary = tempfile.mkstemp(dir=marker.parent, prefix='.active-', suffix='.tmp')
            try:
                with os.fdopen(handle, 'wb') as stream:
                    stream.write(offline_pack._json_bytes({'pack_id': pack_id}))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, marker)
            finally:
                Path(temporary).unlink(missing_ok=True)
    except Exception:
        formula_engine.set_library_path(previous)
        raise
    return _details(data, pack_id, manifest)


def install_archive(archive_path, data_dir):
    """Install a complete private ZIP without extracting any path into live data."""
    data = offline_pack._root(data_dir)
    path = Path(archive_path)
    if path.stat().st_size > MAX_ARCHIVE_BYTES or data.parent == data:
        raise ValueError('知识包ZIP体积或安装目录无效')
    try:
        with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix='.browser-knowledge-', dir=data.parent) as temporary:
            members = _members(archive)
            info = members['manifest.json']
            if info.file_size > offline_pack.MAX_MANIFEST_BYTES:
                raise ValueError('知识包清单过大')
            manifest = _manifest(archive.read(info))
            if set(members) != set(manifest['files']) | {'manifest.json'}:
                raise ValueError('知识包ZIP原件缺失或存在未登记文件')
            if any(members[name].file_size != detail['bytes'] for name, detail in manifest['files'].items()):
                raise ValueError('知识包ZIP声明体积与清单不匹配')
            stage = Path(temporary)
            for name, info in members.items():
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                size = 0
                with archive.open(info) as source, target.open('xb') as destination:
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        size += len(block)
                        if size > info.file_size:
                            raise ValueError('知识包ZIP实际体积与声明不匹配')
                        destination.write(block)
                if size != info.file_size:
                    raise ValueError('知识包ZIP文件不完整')
            installed = offline_pack.install_pack(stage, data)
            return {**activate_installed(data, installed['pack_id']), **installed}
    except (zipfile.BadZipFile, RuntimeError, EOFError, UnicodeError, KeyError, TypeError) as exc:
        raise ValueError('知识包ZIP或清单无效') from exc


def read_original(data_dir, source_id):
    """Read only a registered original whose bytes match its source identity."""
    knowledge._document_id(source_id)
    data = offline_pack._root(data_dir)
    database = offline_pack._file(data, 'clinical.sqlite3')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as conn:
        row = conn.execute('SELECT format FROM text_sources WHERE id=? UNION ALL SELECT \'pdf\' FROM documents WHERE id=?',
                           (source_id, source_id)).fetchall()
    if len(row) != 1 or row[0][0] not in _MIME:
        raise ValueError('原件未登记或格式无效')
    fmt = row[0][0]
    name = f'{source_id}.{fmt}'
    original = offline_pack._file(data, 'originals/' + name)
    content = original.read_bytes()
    if hashlib.sha256(content).hexdigest() != source_id:
        raise ValueError('原件内容与登记身份不匹配')
    return _MIME[fmt], content, name


def browser_unit(conn, data_dir, source_id, unit_no):
    value = library.get_unit(conn, data_dir, source_id, unit_no)
    if value is None:
        return None
    value.pop('image_url', None)
    value['content_scope'] = 'full_unit'
    try:
        offline_pack._file(offline_pack._root(data_dir), f"originals/{source_id}.{value['format']}")
        value['original_available'] = True
        value['original_url'] = f'/library/sources/{source_id}/original'
    except ValueError:
        value['original_available'] = False
        value.pop('original_url', None)
    return value
