"""Use the device-local endpoints in the browser's dedicated Python worker."""
from pathlib import Path
from contextlib import closing
from copy import deepcopy
import json
import re
import threading

from . import browser_excerpts, browser_library, consultation_library, formula_engine, library, library_analysis, library_evidence, mobile_api, storage
from .domain import DomainError
from .browser_models import BrowserModels
from .offline_runtime import prepare_runtime


class BrowserRuntime(mobile_api.LocalRuntime):
    def __init__(self, data_dir, knowledge_dir):
        self.data_dir = Path(data_dir).resolve()
        self.knowledge_dir = Path(knowledge_dir).resolve()
        self.pack = prepare_runtime(self.data_dir, self.knowledge_dir, replace_knowledge=True)
        self.models = BrowserModels(self.data_dir)
        self.guard = threading.RLock()

    def handle(self, method, target, body=None):
        status, result = super().handle(method, target, body)
        if 'platform' in result:
            result['platform'] = 'browser'
        return status, result

    def _handle(self, conn, method, path, query, body):
        confirmation = re.fullmatch(r'/consultations/([^/]+)/facts/confirm', path)
        if method == 'POST' and confirmation:
            return 200, consultation_library.confirm_fact(conn, confirmation.group(1), body.get('term'), body.get('state'), body.get('expected_revision'))
        if method == 'GET' and path == '/library/sources':
            return 200, {'items': browser_excerpts.list_sources(conn)}
        if method == 'GET' and path == '/library/search':
            try:
                limit = int(query.get('limit', ['30'])[0])
            except ValueError:
                raise DomainError(400, '检索数量无效') from None
            return 200, {'items': browser_excerpts.search(conn, query.get('q', [''])[0], query.get('source_id', [None])[0], limit)}
        unit = re.fullmatch(r'/library/sources/([a-f0-9]{64})/units/([1-9][0-9]*)', path)
        if method == 'GET' and unit:
            source, number = unit.group(1), int(unit.group(2))
            value = browser_library.browser_unit(conn, self.data_dir, source, number)
            if value is None:
                value = browser_excerpts.get_unit(conn, self.data_dir, source, number)
            if value is None:
                raise DomainError(404, '原文单元不存在')
            return 200, value
        if method == 'GET' and path == '/library/evidence/summary':
            return 200, library_evidence.summary()
        if method == 'GET' and path == '/library/analysis/summary':
            return 200, library_analysis.summary()
        if method == 'POST' and path == '/library/analysis':
            return 200, library_analysis.analyze(body.get('symptoms'), body.get('absent'), body.get('text', ''), body.get('facts'), body.get('limit', 10))
        return super()._handle(conn, method, path, query, body)


def initialize(data_dir, knowledge_dir):
    mobile_api._runtime = BrowserRuntime(data_dir, knowledge_dir)


dispatch = mobile_api.dispatch


def take_requests():
    return mobile_api._runtime.models.take_requests()


def complete_request(request_id, response):
    mobile_api._runtime.models.complete_request(request_id, response)


def fail_request(request_id, error):
    mobile_api._runtime.models.fail_request(request_id, error)


def pending_request_ids():
    return mobile_api._runtime.models.pending_request_ids()


def checkpoint():
    runtime = mobile_api._runtime
    return {'models': runtime.models.checkpoint(), 'catalog': str(formula_engine.library_path()), 'pack': deepcopy(runtime.pack)}


def restore_checkpoint(value):
    mobile_api._runtime.models.restore_checkpoint(value['models'])
    formula_engine.set_library_path(value['catalog'])
    mobile_api._runtime.pack = value['pack']


def activate_library():
    runtime = mobile_api._runtime
    marker = runtime.data_dir / 'knowledge/active.json'
    try:
        active = json.loads(marker.read_text(encoding='utf-8')).get('pack_id')
    except (OSError, ValueError, AttributeError):
        active = None
    if active != runtime.pack['pack_id']:
        runtime.pack = prepare_runtime(runtime.data_dir, runtime.knowledge_dir, replace_knowledge=True)
    else:
        formula_engine.set_library_path(runtime.pack['formula_library_path'])
    return runtime.pack


def original_info(source_id):
    runtime = mobile_api._runtime
    mime, content, filename = browser_library.read_original(runtime.data_dir, source_id)
    return {'path': 'originals/' + filename, 'mime': mime, 'filename': filename,
            'sha256': source_id, 'size': len(content)}
