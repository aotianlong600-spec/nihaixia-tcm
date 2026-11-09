"""Device-local API for the bundled Android UI; no listening server or desktop deps."""
from contextlib import closing
import json
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from . import consultation_core as core, decision, formula_engine, library, offline_pack, storage
from .domain import DomainError
from .knowledge import _normalize
from .portable_validation import validate
from .offline_runtime import prepare_runtime

ASSET_ORIGIN = 'https://appassets.androidplatform.net'
_runtime = None


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _body(raw):
    if not raw:
        return {}
    try:
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError):
        raise DomainError(400, '请求不是有效JSON对象') from None
    if not isinstance(value, dict):
        raise DomainError(400, '请求不是有效JSON对象')
    return value


class LocalRuntime:
    def __init__(self, data_dir, knowledge_dir, http, secrets):
        self.data_dir = Path(data_dir).resolve()
        self.knowledge_dir = Path(knowledge_dir).resolve()
        self.pack = prepare_runtime(self.data_dir,self.knowledge_dir)
        from .mobile_models import MobileModels
        self.models = MobileModels(self.data_dir, http, secrets)
        self.guard = threading.RLock()

    def handle(self, method, target, body=None):
        if not isinstance(target, str) or not target.startswith('/') or len(target) > 8192:
            raise DomainError(400, '本机请求路径无效')
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or parsed.fragment or '..' in parsed.path.split('/'):
            raise DomainError(400, '本机请求路径无效')
        method = method.upper()
        path = parsed.path.rstrip('/') or '/'
        query = parse_qs(parsed.query, max_num_fields=24)
        body = {} if body is None else body
        if path.startswith('/model/'):
            return self.models.handle(method, path, body)
        with self.guard, closing(storage.connect(self.data_dir)) as conn:
            return self._handle(conn, method, path, query, body)

    def _handle(self, conn, method, path, query, body):
        def number(key, default, lower=1, upper=100):
            try:
                value = int(query.get(key, [str(default)])[0])
            except (ValueError, TypeError):
                raise DomainError(400, '查询数量无效') from None
            if not lower <= value <= upper:
                raise DomainError(400, '查询数量超出范围')
            return value

        if path == '/session' and method == 'GET':
            return 200, {'authenticated': True, 'csrf_token': 'local', 'access_configured': False,
                         'platform': 'android', 'standalone': True}
        if path == '/status' and method == 'GET':
            return 200, {'app_id': 'nihaixia-local', 'offline': True, 'knowledge_pack': self.pack['pack_id']}
        if path == '/access/status' and method == 'GET':
            return 200, {'configured': False, 'setup_allowed': False, 'standalone': True, 'platform': 'android'}
        if path == '/access/logout' and method == 'POST':
            return 200, {'standalone': True, 'authenticated': True}
        if path == '/personal/overview' and method == 'GET':
            sources = library.list_sources(conn)
            data = formula_engine.load_library()
            return 200, {'sources': len(sources), 'pdf_pages': sum(s['pdf_pages'] or 0 for s in sources),
                         'text_units': sum(s['units'] for s in sources if s['format'] != 'pdf'),
                         'formula_count': len(data['formulas']), 'pattern_count': len(data['patterns']),
                         'consultations': conn.execute('SELECT COUNT(*) FROM consultations').fetchone()[0],
                         'ocr_pages': conn.execute('SELECT COUNT(*) FROM pages WHERE ocr_text IS NOT NULL').fetchone()[0]}
        if path == '/consultations':
            if method == 'GET':
                rows = conn.execute('SELECT id,title,revision,created_at,updated_at FROM consultations ORDER BY updated_at DESC,id').fetchall()
                return 200, {'items': [dict(row) for row in rows]}
            if method == 'POST':
                payload = validate('NewConsultation', body)
                core.facts_from_intake(payload['intake'])
                key, at = str(uuid4()), storage.now()
                with conn:
                    conn.execute('INSERT INTO consultations VALUES(?,?,?,?,?,?)',
                                 (key, payload['title'] or '新问诊', storage.encode(payload['intake']), 1, at, at))
                return 200, core.get_record(conn, key)
        case = re.fullmatch(r'/consultations/([^/]+)(?:/(messages|context))?', path)
        if case:
            key, action = case.groups()
            if not action and method == 'GET':
                return 200, core.get_record(conn, key)
            if action == 'context' and method == 'GET':
                return 200, core.build_context(conn, key)
            if not action and method == 'PUT':
                payload = validate('EditConsultation', body)
                core.facts_from_intake(payload['intake'])
                with conn:
                    conn.execute('BEGIN IMMEDIATE')
                    current = core.get_record(conn, key, False)
                    if current['revision'] != payload['expected_revision']:
                        raise DomainError(409, '问诊信息已变化，请重新加载')
                    conn.execute('UPDATE consultations SET intake=?,revision=revision+1,updated_at=? WHERE id=?',
                                 (storage.encode(payload['intake']), storage.now(), key))
                return 200, core.get_record(conn, key)
            if action == 'messages' and method == 'POST':
                payload = validate('MessageInput', body)
                with conn:
                    conn.execute('BEGIN IMMEDIATE')
                    current = core.get_record(conn, key, False)
                    if payload['expected_revision'] is not None and current['revision'] != payload['expected_revision']:
                        raise DomainError(409, '对话已更新，请重新加载')
                    revision, message_id, at = current['revision'] + 1, str(uuid4()), storage.now()
                    conn.execute('INSERT INTO consultation_messages VALUES(?,?,?,?,?,?,?,?,?)',
                                 (message_id, key, 'user', payload['text'], None, None, None, revision, at))
                    title = payload['text'][:30] if current['title'] == '新问诊' else current['title']
                    conn.execute('UPDATE consultations SET title=?,revision=?,updated_at=? WHERE id=?', (title, revision, at, key))
                return 200, {'consultation': core.get_record(conn, key), 'revision': revision,
                             'message': {'id': message_id, 'role': 'user', 'text': payload['text'], 'created_at': at}}
        if path == '/library/sources' and method == 'GET':
            return 200, {'items': library.list_sources(conn)}
        if path == '/library/search' and method == 'GET':
            return 200, {'items': library.search(conn, query.get('q', [''])[0], query.get('source_id', [None])[0], number('limit', 30))}
        unit = re.fullmatch(r'/library/sources/([a-f0-9]{64})/units/([1-9][0-9]*)', path)
        if unit and method == 'GET':
            sha, page = unit.groups()
            value = library.get_unit(conn, self.data_dir, sha, int(page))
            if value is None:
                raise DomainError(404, '原文单元不存在')
            if value['format'] == 'pdf':
                value['image_url'] = f'{ASSET_ORIGIN}/local/pdf/{sha}/{page}.png'
            value['original_url'] = f'{ASSET_ORIGIN}/local/original/{sha}'
            return 200, value
        if path == '/formulas' and method == 'GET':
            return 200, {'items': formula_engine.search_formulas(query.get('q', [''])[0], number('limit', 30))}
        if path == '/formulas/match' and method == 'POST':
            payload = validate('MatchInput', body)
            from .engine import analyze
            analyze(payload['facts'], [], {})
            return 200, {'items': formula_engine.match_patterns(payload['facts'], payload['query'], payload['limit'])}
        formula = re.fullmatch(r'/formulas/([^/]+)', path)
        if formula and method == 'GET':
            value = formula_engine.get_formula(formula.group(1))
            if value is None:
                raise DomainError(404, '方剂条目不存在')
            return 200, value
        if path == '/decision/coverage' and method == 'GET':
            return 200, {**decision.coverage(conn), 'external_catalog_formulas': len(formula_engine.load_library()['formulas']), 'safety': 'incomplete'}
        if path == '/decision/packages' and method == 'GET':
            return 200, {'items': decision.load_packages(conn)}
        if path == '/decision/evaluate' and method == 'POST':
            payload = validate('DecisionInput', body)
            return 200, decision.evaluate(conn, payload['facts'], payload['package_id'])
        if path == '/decision/modifications/preview' and method == 'POST':
            payload = validate('DecisionPreview', body)
            return 200, decision.preview_modifications(conn, payload['package_id'], payload['base_version_id'], payload['modification_ids'], payload['facts'])
        raise DomainError(404, '本机接口不存在')


def _native_backends():
    from java import jclass
    services = jclass('com.nihaixia.local.NativeServices')

    class Http:
        def __call__(self, method, url, headers, body, request_id, timeout_ms):
            return json.loads(str(services.http(method, url, _json(headers), body, request_id, timeout_ms)))

        def cancel(self, request_id):
            services.cancelHttp(request_id)

    class Secrets:
        def read(self, path):
            value = services.readSecret(str(path))
            return str(value) if value is not None else None

        def write(self, path, value):
            services.writeSecret(str(path), value)

    return Http(), Secrets()


def initialize(data_dir, knowledge_dir):
    global _runtime
    try:
        if (_runtime is not None and _runtime.data_dir==Path(data_dir).resolve()
                and _runtime.knowledge_dir==Path(knowledge_dir).resolve()):
            return _json({'status':200,'body':{'ready':True,'knowledge_pack':_runtime.pack['pack_id']}})
        http, secrets = _native_backends()
        _runtime = LocalRuntime(data_dir, knowledge_dir, http, secrets)
        return _json({'status': 200, 'body': {'ready': True, 'knowledge_pack': _runtime.pack['pack_id']}})
    except Exception as exc:
        import traceback
        frames = traceback.extract_tb(exc.__traceback__)
        location = frames[-1] if frames else None
        diagnostic = {'type':type(exc).__name__,
                      'location':(Path(location.filename).name+':'+str(location.lineno)) if location else 'unknown'}
        return _json({'status': 500, 'body': {'detail': '本机知识库准备失败，请检查安装包或可用存储空间后重试',
                                            'diagnostic':diagnostic}})


def dispatch(method, path, body_json=''):
    try:
        if _runtime is None:
            raise DomainError(503, '本机知识库尚未准备完成')
        status, value = _runtime.handle(method, path, _body(body_json))
        return _json({'status': status, 'body': value})
    except DomainError as exc:
        return _json({'status': exc.status_code, 'body': {'detail': exc.detail}})
    except (ValueError, TypeError, KeyError):
        return _json({'status': 400, 'body': {'detail': '本机请求字段无效，请检查输入后重试'}})
    except Exception:
        return _json({'status': 500, 'body': {'detail': '本机处理未完成，请保留记录后重试'}})
