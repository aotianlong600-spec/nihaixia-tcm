from contextlib import closing
import json
import sqlite3

from app import browser_api, formula_engine, mobile_api, offline_pack


def test_browser_runtime_uses_catalog_and_local_records_with_browser_models(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    with closing(sqlite3.connect(source / 'clinical.sqlite3')) as conn, conn:
        for statement in offline_pack.SCHEMA.values():
            conn.execute(statement)
    pack = tmp_path / 'pack'
    offline_pack.export_pack(source, pack)
    monkeypatch.setattr(mobile_api, '_runtime', None)
    original_catalog = formula_engine.library_path()

    def request(method, path, body=None):
        response = browser_api.dispatch(method, path, json.dumps(body) if body is not None else '')
        return json.loads(response)

    try:
        browser_api.initialize(tmp_path / 'records', pack)
        assert request('GET', '/session')['body']['platform'] == 'browser'
        assert request('GET', '/personal/overview')['body']['formula_count'] > 0
        formulas = request('GET', '/formulas?q=%E7%9F%B3%E8%86%8F&limit=100')['body']['items']
        assert any('石膏' in [component['name'] for component in formula['components']] for formula in formulas)
        assert request('GET', '/model/config')['status'] == 200
        assert request('POST', '/model/jobs', {'purpose': 'test'})['status'] == 409
        case = request('POST', '/consultations', {'intake': {'symptoms': ['怕冷']}})['body']
        browser_api.initialize(tmp_path / 'records', pack)
        assert request('GET', f"/consultations/{case['id']}")['body']['intake']['symptoms'] == ['怕冷']
    finally:
        formula_engine.set_library_path(original_catalog)
