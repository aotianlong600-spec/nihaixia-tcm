import json
from pathlib import Path

import pytest

from app import formula_engine
from app.domain import DomainError
from app.mobile_api import LocalRuntime
from app.offline_pack import export_pack


class Secrets:
    def __init__(self):
        self.values = {}

    def read(self, path):
        return self.values.get(str(path))

    def write(self, path, value):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'encrypted-synthetic-value')
        self.values[str(path)] = value


@pytest.fixture
def local(tmp_path):
    from test_offline_pack import sample
    source, text_sha, pdf_sha = sample(tmp_path)
    pack = tmp_path / 'pack'
    export_pack(source, pack)

    def offline(*args):
        raise AssertionError('Offline lookup must not call a model or network')

    runtime = LocalRuntime(tmp_path / 'device', pack, offline, Secrets())
    yield runtime, text_sha, pdf_sha
    formula_engine.set_library_path()


def test_offline_local_lookup_graph_and_case_survive_restart(local):
    runtime, text_sha, pdf_sha = local
    status, session = runtime.handle('GET', '/session')
    assert status == 200 and session['standalone'] and session['authenticated']
    assert session['platform'] == 'android'
    assert runtime.handle('GET', '/personal/overview')[1]['sources'] == 2
    assert runtime.handle('GET', '/consultations')[1]['items'] == []
    _, case = runtime.handle('POST', '/consultations', {'intake': {'symptoms': ['测试症']}})
    _, context = runtime.handle('GET', f"/consultations/{case['id']}/context")
    assert context['facts'][0]['key'] == '测试症'
    assert context['decision_graph']['nodes'][0]['status'] == 'clue'
    assert runtime.handle('GET', '/model/config')[1]['profile_id'] is None
    _, unit = runtime.handle('GET', f'/library/sources/{pdf_sha}/units/1')
    assert unit['locator'] == {'kind':'physical_page','start':1,'end':1,'printed_page':'150'}
    assert unit['image_url'].startswith('https://appassets.androidplatform.net/local/pdf/')
    assert unit['original_url'].endswith(pdf_sha)
    _, result = runtime.handle('GET', '/library/search?q=观察')
    assert any(item['source_id'] == text_sha for item in result['items'])
    reloaded = LocalRuntime(runtime.data_dir, runtime.knowledge_dir, lambda *a: {}, Secrets())
    assert reloaded.pack['installed_rows'] == 0
    assert reloaded.handle('GET', f"/consultations/{case['id']}")[1]['intake']['symptoms'] == ['测试症']


def test_local_edits_preserve_revision_and_reject_boolean_or_stale_updates(local):
    runtime, _, _ = local
    _, case = runtime.handle('POST', '/consultations', {})
    _, message = runtime.handle('POST', f"/consultations/{case['id']}/messages", {'text':'合成😀输入','expected_revision':1})
    assert message['revision'] == 2
    with pytest.raises(DomainError) as exc:
        runtime.handle('PUT', f"/consultations/{case['id']}", {'expected_revision':1,'intake':{}})
    assert exc.value.status_code == 409
    with pytest.raises(ValueError):
        runtime.handle('PUT', f"/consultations/{case['id']}", {'expected_revision':True,'intake':{}})
    assert runtime.handle('GET', f"/consultations/{case['id']}")[1]['messages'][0]['text'] == '合成😀输入'


def test_local_dispatch_error_is_safe_and_unknown_routes_are_not_faked(local, monkeypatch):
    runtime, _, _ = local
    import app.mobile_api as mobile
    monkeypatch.setattr(mobile, '_runtime', runtime)
    result = json.loads(mobile.dispatch('POST','/consultations','{"intake":{"unknown_secret_field":"sensitive-value"}}'))
    assert result['status'] == 400 and 'sensitive-value' not in json.dumps(result)
    assert json.loads(mobile.dispatch('GET','https://other.example/',''))['status'] == 400
    assert json.loads(mobile.dispatch('GET','/unimplemented',''))['status'] == 404
    assert json.loads(mobile.dispatch('POST','/consultations','{"intake":{"age_years":NaN}}'))['status'] == 400


def test_installed_catalog_changes_lookup_and_frozen_digest_without_overwriting_resources(tmp_path):
    from app import consultation_core
    original = formula_engine.library_path()
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps({'formulas':[{'id':'installed','name':'合成方'}],'patterns':[]}), encoding='utf-8')
    try:
        formula_engine.set_library_path(catalog)
        assert formula_engine.get_formula('installed')['name'] == '合成方'
        import hashlib
        assert consultation_core._library_digest() == hashlib.sha256(catalog.read_bytes()).hexdigest()
        invalid = tmp_path / 'bad.json'; invalid.write_text('{}',encoding='utf-8')
        with pytest.raises(ValueError): formula_engine.set_library_path(invalid)
        assert formula_engine.library_path() == catalog.resolve()
        assert original.is_file()
    finally:
        formula_engine.set_library_path(original)


def test_activity_recreation_reuses_device_runtime_and_pending_jobs(local, monkeypatch):
    runtime, _, _ = local
    import app.mobile_api as mobile
    monkeypatch.setattr(mobile, '_runtime', runtime)
    monkeypatch.setattr(mobile, '_native_backends', lambda: (_ for _ in ()).throw(AssertionError('Already initialized')))
    result = json.loads(mobile.initialize(str(runtime.data_dir),str(runtime.knowledge_dir)))
    assert result['status'] == 200
    assert mobile._runtime is runtime
