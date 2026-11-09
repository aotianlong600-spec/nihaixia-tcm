"""Portable knowledge only; personal databases and credentials are never exported."""
from contextlib import closing
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile

from . import decision
from .consultation_core import ANALYSIS_REVISION

FORMAT = 'nihaixia-knowledge-pack'
VERSION = 1
SUPPORTED_ANALYSIS_REVISIONS = {2, 3}
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_FILES = 100000
FORMULA_SOURCE = Path(__file__).parent / 'resources/open_formula_library.json'
REDACTED = {'reviewer', 'note', 'reviewed_at'}
METADATA_POLICY = 'Page reviewer, note and reviewed_at are NULL; source text, corrections and import metadata are preserved.'

TABLES = {
    'documents': ('id','title','sha256','physical_pages','author_status','warning','created_at'),
    'pages': ('document_id','physical_page','raw_text','corrected_text','search_text','review_status','kind','printed_page','warning','extraction_method','reviewer','note','reviewed_at','ocr_text','ocr_metadata','ocr_search_text'),
    'source_catalog': ('id','corpus_role'),
    'text_sources': ('id','title','format','total_units','encoding'),
    'source_units': ('source_id','unit_no','locator','raw_text','search_text'),
    'decision_packages': ('id','version','digest','payload'),
    'research_entries': ('id','document_id','document','created_at'),
}
KEYS = {'documents':('id',), 'pages':('document_id','physical_page'), 'source_catalog':('id',),
        'text_sources':('id',), 'source_units':('source_id','unit_no'),
        'decision_packages':('id','version'), 'research_entries':('id',)}
SCHEMA = {
    'documents': 'CREATE TABLE documents (id TEXT PRIMARY KEY,title TEXT NOT NULL,sha256 TEXT NOT NULL UNIQUE,physical_pages INTEGER NOT NULL CHECK(physical_pages>0),author_status TEXT NOT NULL,warning TEXT NOT NULL,created_at TEXT NOT NULL)',
    'pages': "CREATE TABLE pages (document_id TEXT NOT NULL REFERENCES documents(id),physical_page INTEGER NOT NULL CHECK(physical_page>0),raw_text TEXT NOT NULL,corrected_text TEXT,search_text TEXT NOT NULL,review_status TEXT NOT NULL DEFAULT 'pending' CHECK(review_status IN ('pending','verified')),kind TEXT NOT NULL DEFAULT 'unclassified',printed_page TEXT,warning TEXT NOT NULL,extraction_method TEXT NOT NULL,reviewer TEXT,note TEXT,reviewed_at TEXT,ocr_text TEXT,ocr_metadata TEXT,ocr_search_text TEXT,PRIMARY KEY(document_id,physical_page))",
    'source_catalog': 'CREATE TABLE source_catalog (id TEXT PRIMARY KEY,corpus_role TEXT NOT NULL)',
    'text_sources': 'CREATE TABLE text_sources (id TEXT PRIMARY KEY,title TEXT NOT NULL,format TEXT NOT NULL,total_units INTEGER NOT NULL,encoding TEXT)',
    'source_units': 'CREATE TABLE source_units (source_id TEXT NOT NULL REFERENCES text_sources(id),unit_no INTEGER NOT NULL,locator TEXT NOT NULL,raw_text TEXT NOT NULL,search_text TEXT,PRIMARY KEY(source_id,unit_no))',
    'decision_packages': 'CREATE TABLE decision_packages (id TEXT NOT NULL,version INTEGER NOT NULL,digest TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(id,version))',
    'research_entries': 'CREATE TABLE research_entries (id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id),document TEXT NOT NULL,created_at TEXT NOT NULL)',
}
SHA = re.compile(r'[0-9a-f]{64}\Z')
ORIGINAL = re.compile(r'originals/([0-9a-f]{64})\.(pdf|txt|doc|docx|md)\Z')


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('知识包JSON包含重复字段')
        result[key] = value
    return result


def _reparse(path):
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def _root(path):
    path = Path(path).absolute()
    if not path.is_dir() or _reparse(path):
        raise ValueError('知识包或数据目录不存在，或使用了链接')
    return path.resolve()


def _file(root, relative):
    path = root / relative
    current = root
    for part in Path(relative).parts:
        current /= part
        if current.exists() and _reparse(current):
            raise ValueError('知识包不允许符号链接或目录联接')
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError('知识包文件缺失或路径越界')
    return path


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _copy(source, target, expected=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(); size = 0
    dst = target.open('xb')
    try:
        with dst, source.open('rb') as src:
            for block in iter(lambda: src.read(1024 * 1024), b''):
                dst.write(block); size += len(block); digest.update(block)
            dst.flush();os.fsync(dst.fileno())
        detail = {'bytes':size, 'sha256':digest.hexdigest()}
        if expected is not None and detail != expected:
            raise ValueError('知识包复制时文件已变化或损坏')
        return detail
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def _read_db(path):
    conn = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
    conn.execute('PRAGMA query_only=ON')
    conn.execute('PRAGMA trusted_schema=OFF')
    return conn


def _schema(conn, strict=False):
    if strict:
        objects = conn.execute('SELECT type,name,tbl_name,sql FROM sqlite_master').fetchall()
        actual = {name:sql for kind,name,table,sql in objects if kind == 'table'}
        normalize = lambda sql: ''.join(sql.split()).casefold()
        if set(actual) != set(TABLES) or any(normalize(actual[t]) != normalize(SCHEMA[t]) for t in TABLES):
            raise ValueError('知识包数据库表结构不在允许范围')
        if any(kind != 'table' and not (kind == 'index' and sql is None and table in TABLES and name.startswith('sqlite_autoindex_')) for kind,name,table,sql in objects):
            raise ValueError('知识包不能包含视图、触发器或额外索引')
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('知识库数据库完整性或引用校验失败')
        if conn.execute('PRAGMA freelist_count').fetchone()[0] != 0:
            raise ValueError('知识包数据库必须是全新逐表导出的文件')
    for table, columns in TABLES.items():
        obj = conn.execute('SELECT type,sql FROM sqlite_master WHERE name=?', (table,)).fetchone()
        if not obj or obj[0] != 'table' or re.search(r'\bVIRTUAL\s+TABLE\b', obj[1], re.IGNORECASE):
            raise ValueError('知识库只允许普通知识表：' + table)
        found = tuple(row[1] for row in conn.execute(f'PRAGMA table_info({table})'))
        if found != columns:
            raise ValueError('知识库字段不兼容：' + table)


def _rows(conn, table, redact=False):
    columns = ','.join('NULL AS ' + c if redact and table == 'pages' and c in REDACTED else c for c in TABLES[table])
    order = ','.join(KEYS[table])
    return conn.execute(f'SELECT {columns} FROM {table} ORDER BY {order}')


def _originals(conn):
    originals = set(); identities = set()
    for sha, registered, pages in conn.execute('SELECT id,sha256,physical_pages FROM documents'):
        if not isinstance(sha, str) or not SHA.fullmatch(sha) or sha != registered or type(pages) is not int or pages < 1:
            raise ValueError('PDF登记身份无效')
        count, low, high = conn.execute('SELECT COUNT(*),MIN(physical_page),MAX(physical_page) FROM pages WHERE document_id=?', (sha,)).fetchone()
        if (count, low, high) != (pages, 1, pages):
            raise ValueError('PDF物理页序列不完整')
        identities.add(sha); originals.add(f'originals/{sha}.pdf')
    for sha, fmt in conn.execute('SELECT id,format FROM text_sources'):
        if not isinstance(sha, str) or not SHA.fullmatch(sha) or sha in identities or fmt not in ('txt','doc','docx','md'):
            raise ValueError('文本原件登记身份无效')
        identities.add(sha); originals.add(f'originals/{sha}.{fmt}')
    if {r[0] for r in conn.execute('SELECT id FROM source_catalog')} != identities:
        raise ValueError('来源目录与原件登记不一致')
    return originals


def _packages(conn):
    packages = decision.load_packages(conn)
    for package in packages:
        decision._validate(conn, package['snapshot'])
    return [{k:p[k] for k in ('id','version','digest')} for p in packages]


def _tree(root):
    found = set()
    for current, dirs, files in os.walk(root, followlinks=False):
        directory = Path(current)
        for name in dirs:
            path = directory / name
            if _reparse(path) or path.relative_to(root).as_posix() != 'originals':
                raise ValueError('知识包包含不允许的目录或链接')
        for name in files:
            path = directory / name
            if _reparse(path) or not path.resolve().is_relative_to(root):
                raise ValueError('知识包包含链接或越界文件')
            found.add(path.relative_to(root).as_posix())
            if len(found) > MAX_FILES + 1:
                raise ValueError('知识包文件数量超出解析范围')
    return found


def verify_pack(pack_dir: Path) -> dict:
    root = _root(pack_dir)
    manifest_path = _file(root, 'manifest.json')
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError('知识包清单过大')
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
        if (not isinstance(manifest, dict) or set(manifest) != {'format','version','engine_analysis_revision','metadata_policy','files','tables','packages'}
                or manifest['format'] != FORMAT or type(manifest['version']) is not int or manifest['version'] != VERSION
                or type(manifest['engine_analysis_revision']) is not int or manifest['engine_analysis_revision'] not in SUPPORTED_ANALYSIS_REVISIONS
                or manifest['metadata_policy'] != METADATA_POLICY):
            raise ValueError('知识包清单格式或引擎版本不兼容')
        files = manifest['files']; counts = manifest['tables']
        if not isinstance(files, dict) or not 2 <= len(files) <= MAX_FILES or not isinstance(counts, dict) or set(counts) != set(TABLES):
            raise ValueError('知识包文件或表清单无效')
        if any(type(n) is not int or n < 0 for n in counts.values()):
            raise ValueError('知识包行数无效')
        for name, detail in files.items():
            if name not in ('knowledge.sqlite3','open_formula_library.json') and not ORIGINAL.fullmatch(name):
                raise ValueError('知识包文件路径不在允许范围')
            if (not isinstance(detail, dict) or set(detail) != {'bytes','sha256'} or type(detail['bytes']) is not int
                    or not 0 <= detail['bytes'] <= 2**63-1 or not isinstance(detail['sha256'], str) or not SHA.fullmatch(detail['sha256'])):
                raise ValueError('知识包文件校验字段无效')
            path = _file(root, name)
            if path.stat().st_size != detail['bytes'] or _hash(path) != detail['sha256']:
                raise ValueError('知识包文件字节数或哈希不匹配')
        if _tree(root) != set(files) | {'manifest.json'}:
            raise ValueError('知识包包含未登记文件或缺失文件')
        with closing(_read_db(_file(root, 'knowledge.sqlite3'))) as conn:
            _schema(conn, strict=True)
            expected_bytes = conn.execute('PRAGMA page_count').fetchone()[0] * conn.execute('PRAGMA page_size').fetchone()[0]
            if files['knowledge.sqlite3']['bytes'] != expected_bytes:
                raise ValueError('知识包数据库包含未登记的尾部数据')
            if conn.execute('SELECT COUNT(*) FROM pages WHERE reviewer IS NOT NULL OR note IS NOT NULL OR reviewed_at IS NOT NULL').fetchone()[0]:
                raise ValueError('知识包包含本机校注人员元数据')
            if {t:conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in TABLES} != counts:
                raise ValueError('知识包表行数不一致')
            registered = _originals(conn)
            if set(files) != registered | {'knowledge.sqlite3','open_formula_library.json'}:
                raise ValueError('知识包原件缺失、多余或未登记')
            if any(files[name]['sha256'] != ORIGINAL.fullmatch(name).group(1) for name in registered):
                raise ValueError('原件内容与登记SHA不一致')
            if _packages(conn) != manifest['packages']:
                raise ValueError('知识包版本或断言清单不一致')
        formulas = json.loads(_file(root, 'open_formula_library.json').read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
        if not isinstance(formulas, dict) or not isinstance(formulas.get('formulas'), list) or not isinstance(formulas.get('patterns'), list):
            raise ValueError('经方索引格式无效')
        return manifest
    except (sqlite3.DatabaseError, json.JSONDecodeError, UnicodeError, KeyError, TypeError) as exc:
        raise ValueError('知识包数据库或清单无效') from exc


def _storage_error(exc):
    if getattr(exc, 'errno', None) in (errno.ENOSPC, getattr(errno, 'EDQUOT', -1)) or getattr(exc, 'sqlite_errorcode', None) == sqlite3.SQLITE_FULL:
        return ValueError('磁盘空间不足，知识包未安装；原有数据已保留')
    return exc


def export_pack(source_data_dir: Path, destination: Path) -> dict:
    source = _root(source_data_dir); database = _file(source, 'clinical.sqlite3')
    destination = Path(destination).absolute()
    if destination.exists() and (_reparse(destination) or not destination.is_dir() or any(destination.iterdir())):
        raise ValueError('导出目标必须不存在或为空目录，不覆盖已有资料')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='.knowledge-export-', dir=destination.parent) as temporary:
            stage = Path(temporary) / 'pack'; stage.mkdir(); (stage / 'originals').mkdir()
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(stage / 'knowledge.sqlite3')) as dst:
                src.execute('PRAGMA query_only=ON'); src.execute('BEGIN')
                # Even a disguised source object must not read a personal table.
                src.set_authorizer(lambda action, table, column, db, origin:
                                   sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and table not in TABLES and table != 'sqlite_master' else sqlite3.SQLITE_OK)
                _schema(src)
                for sql in SCHEMA.values(): dst.execute(sql)
                for table, columns in TABLES.items():
                    dst.executemany(f'INSERT INTO {table} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})', _rows(src, table, redact=True))
                dst.commit()
                originals = _originals(dst); packages = _packages(dst)
                counts = {t:dst.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in TABLES}
            files = {name:_copy(_file(source, name), stage / name) for name in sorted(originals)}
            files['open_formula_library.json'] = _copy(FORMULA_SOURCE, stage / 'open_formula_library.json')
            db = stage / 'knowledge.sqlite3'; files['knowledge.sqlite3'] = {'bytes':db.stat().st_size,'sha256':_hash(db)}
            manifest = {'format':FORMAT,'version':VERSION,'engine_analysis_revision':ANALYSIS_REVISION,
                        'metadata_policy':METADATA_POLICY,'files':files,'tables':counts,'packages':packages}
            (stage / 'manifest.json').write_bytes(_json_bytes(manifest))
            verify_pack(stage)
            if destination.exists(): destination.rmdir()
            stage.rename(destination)
        return manifest
    except (OSError, sqlite3.DatabaseError) as exc:
        raise _storage_error(exc)


def install_pack(pack_dir: Path, data_dir: Path, *, replace: bool = False) -> dict:
    manifest = verify_pack(pack_dir); pack = _root(pack_dir); data = _root(data_dir)
    runtime = _file(data, 'clinical.sqlite3')
    canonical_manifest = _json_bytes(manifest)
    pack_id = hashlib.sha256(canonical_manifest).hexdigest()
    resource_dir = data / 'knowledge' / pack_id
    for path in (data / 'originals', data / 'knowledge', resource_dir):
        if path.exists() and (_reparse(path) or not path.is_dir()):
            raise ValueError('设备知识路径无效或使用了链接')
    required = sum(f['bytes'] for f in manifest['files'].values()) + manifest['files']['knowledge.sqlite3']['bytes'] + len(canonical_manifest)
    if shutil.disk_usage(data).free < required:
        raise ValueError('磁盘空间不足，知识包未安装；原有数据已保留')
    created = []; made_resource = False
    try:
        with tempfile.TemporaryDirectory(prefix='.knowledge-install-', dir=data) as temporary:
            stage = Path(temporary) / 'pack'; stage.mkdir(); (stage / 'originals').mkdir()
            for name, detail in manifest['files'].items(): _copy(_file(pack, name), stage / name, detail)
            (stage / 'manifest.json').write_bytes(canonical_manifest)
            verify_pack(stage)
            with closing(_read_db(stage / 'knowledge.sqlite3')) as src, closing(sqlite3.connect(runtime, timeout=30)) as dst:
                dst.execute('PRAGMA foreign_keys=ON'); dst.execute('BEGIN IMMEDIATE')
                try:
                    _schema(dst)
                    if replace:
                        for table in ('research_entries', 'pages', 'source_units', 'documents',
                                      'text_sources', 'source_catalog'):
                            dst.execute(f'DELETE FROM {table}')
                    installed = 0
                    for table, columns in TABLES.items():
                        where = ' AND '.join(f'{k}=?' for k in KEYS[table])
                        indexes = [columns.index(k) for k in KEYS[table]]
                        for row in _rows(src, table):
                            previous = dst.execute(f'SELECT {",".join(columns)} FROM {table} WHERE {where}', tuple(row[i] for i in indexes)).fetchone()
                            if previous is not None:
                                if any(a != b for column,a,b in zip(columns, previous, row) if not (table == 'pages' and column in REDACTED)):
                                    if replace and table == 'decision_packages':
                                        continue
                                    raise ValueError('知识身份内容冲突，整次安装已取消：' + table)
                                continue
                            dst.execute(f'INSERT INTO {table} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})', row)
                            installed += 1
                    for package in decision.load_packages(src): decision._validate(dst, package['snapshot'])
                    (data / 'originals').mkdir(exist_ok=True); (data / 'knowledge').mkdir(exist_ok=True)
                    if not resource_dir.exists(): resource_dir.mkdir(); made_resource = True
                    targets = [(stage / name, data / name, detail) for name,detail in manifest['files'].items() if ORIGINAL.fullmatch(name)]
                    targets += [(stage / 'open_formula_library.json', resource_dir / 'open_formula_library.json', manifest['files']['open_formula_library.json']),
                                (stage / 'manifest.json', resource_dir / 'manifest.json', {'bytes':len(canonical_manifest),'sha256':pack_id})]
                    for staged, target, detail in targets:
                        if target.exists():
                            if _reparse(target) or not target.is_file() or target.stat().st_size != detail['bytes'] or _hash(target) != detail['sha256']:
                                raise ValueError('设备原件或知识资源内容冲突')
                        else:
                            try:
                                os.link(staged, target)
                            except (AttributeError, OSError) as exc:
                                if isinstance(exc, OSError) and exc.errno not in {errno.EPERM,errno.EACCES,errno.EXDEV,errno.ENOSYS,getattr(errno,'ENOTSUP',-1)}:
                                    raise
                                # Some runtimes omit hardlinks; bytes finish before the DB transaction commits.
                                _copy(staged,target,detail)
                            created.append(target)
                    dst.commit()
                except Exception:
                    dst.rollback()
                    for path in reversed(created): path.unlink()
                    if made_resource: resource_dir.rmdir()
                    raise
        return {'format':FORMAT,'version':VERSION,'pack_id':pack_id,'installed_rows':installed,'tables':manifest['tables'],
                'formula_library_path':str(resource_dir / 'open_formula_library.json'),'manifest_path':str(resource_dir / 'manifest.json')}
    except (OSError, sqlite3.DatabaseError) as exc:
        raise _storage_error(exc)
