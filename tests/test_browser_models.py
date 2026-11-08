"""Browser transport tests use only synthetic credentials and HTTP responses."""
import base64
import json
import time
from uuid import uuid4

import pytest

from app import consultation_core, library, storage


def test_secret_write_failure_preserves_previous_credential(tmp_path, monkeypatch):
    from app import browser_models
    path = tmp_path / 'credential'
    path.write_text('previous', encoding='utf-8')
    def fail(*args):
        raise OSError('synthetic replacement failure')
    monkeypatch.setattr(browser_models.os, 'replace', fail)
    with pytest.raises(OSError):
        browser_models.BrowserSecrets().write(path, 'replacement')
    assert path.read_text(encoding='utf-8') == 'previous'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['credential']


def make_models(tmp_path):
    from app.browser_models import BrowserModels
    storage.initialize(tmp_path)
    with storage.connect(tmp_path) as conn:
        library.initialize(conn, tmp_path)
        consultation_core.initialize(conn)
    return BrowserModels(tmp_path)


def select(models, **extra):
    data = {'name': 'Synthetic', 'auth_mode': 'api_key', 'base_url': 'https://example.test/v1',
            'model': 'synthetic', 'api_key': 'synthetic-key', 'enabled': True,
            'allow_external': True, 'allow_evidence': True, **extra}
    status, item = models.handle('POST', '/model/profiles', data)
    assert status == 200, item
    status, config = models.handle('POST', f"/model/profiles/{item['id']}/select", {})
    assert status == 200, config
    return config


def stream(text='OK', complete=True):
    events = [{'choices': [{'delta': {'content': text}, 'finish_reason': None}]}]
    if complete:
        events.append({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})
    body = ''.join('data: ' + json.dumps(value) + '\n\n' for value in events)
    return {'status': 200, 'headers': {'content-type': 'text/event-stream'},
            'body': body + ('data: [DONE]\n\n' if complete else '')}


def job_state(models, job):
    return models.handle('GET', '/model/jobs/' + job['id'])[1]


@pytest.mark.parametrize('complete', [True, False])
def test_browser_jobs_queue_and_validate_complete_stream(tmp_path, complete):
    models = make_models(tmp_path)
    cfg = select(models)
    assert cfg['has_key'] and 'synthetic-key' not in json.dumps(cfg)
    status, job = models.handle('POST', '/model/jobs', {'purpose': 'test'})
    assert status == 200 and job['status'] == 'queued'
    [request] = models.take_requests()
    assert request['url'] == 'https://example.test/v1/chat/completions'
    assert request['headers']['Authorization'] == 'Bearer synthetic-key'
    assert json.loads(request['body'])['stream'] is True
    assert job_state(models, job)['status'] == 'running'
    assert models.take_requests() == []
    models.complete_request(request['id'], stream(complete=complete))
    result = job_state(models, job)
    assert result['status'] == ('completed' if complete else 'failed')
    assert result['validated'] is complete
    with storage.connect(tmp_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0] == int(complete)
    assert models.oauth.path.is_relative_to(tmp_path / 'models')
    assert models.profiles.path.is_relative_to(tmp_path / 'models')
    assert models.profiles.key_path(cfg['profile_id']).is_relative_to(tmp_path / 'models')


@pytest.mark.parametrize('action', ['cancel', 'delete', 'reconfigure'])
def test_browser_cancel_and_profile_changes_discard_late_success(tmp_path, action):
    models = make_models(tmp_path)
    cfg = select(models)
    _, job = models.handle('POST', '/model/jobs', {'purpose': 'test'})
    [request] = models.take_requests()
    if action == 'cancel':
        models.handle('POST', f"/model/jobs/{job['id']}/cancel", {})
    elif action == 'delete':
        models.handle('DELETE', f"/model/profiles/{cfg['profile_id']}")
    else:
        models.handle('PUT', '/model/config', {'model': 'changed', 'base_url': 'https://example.test/v1'})
    models.complete_request(request['id'], stream())
    assert job_state(models, job)['status'] in ('cancelled', 'failed')
    with storage.connect(tmp_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0] == 0


def credential(expired=False):
    payload = {'https://api.openai.com/auth': {'chatgpt_account_id': 'synthetic-account'}}
    token = 'e30.' + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=') + '.synthetic'
    return {'type': 'oauth', 'access': token, 'refresh': 'synthetic-refresh',
            'expires': time.time() * 1000 + (-1 if expired else 3600000), 'accountId': 'synthetic-account'}


def json_response(value, status=200):
    return {'status': status, 'headers': {}, 'body': json.dumps(value)}


def test_browser_device_login_and_codex_refresh(tmp_path):
    models = make_models(tmp_path)
    select(models, auth_mode='codex', base_url='https://chatgpt.com/backend-api', api_key=None)
    status, attempt = models.handle('POST', '/model/codex/login', {'method': 'device'})
    assert status == 200 and attempt['stage'] == 'starting'
    [request] = models.take_requests()
    assert request['url'].endswith('/deviceauth/usercode')
    models.complete_request(request['id'], json_response({'device_auth_id': 'synthetic-device', 'user_code': 'SYNTH-1234', 'interval': 1}))
    public = models.handle('GET', '/model/codex')[1]
    assert public['login']['device_code']['code'] == 'SYNTH-1234'
    assert 'synthetic-device' not in json.dumps(public)
    [request] = models.take_requests()
    assert request['delay_ms'] == 1000
    models.complete_request(request['id'], json_response({'authorization_code': 'synthetic-code', 'code_verifier': 'synthetic-verifier'}))
    [request] = models.take_requests()
    assert 'grant_type=authorization_code' in request['body']
    fresh = credential()
    models.complete_request(request['id'], json_response({'access_token': fresh['access'], 'refresh_token': fresh['refresh'], 'expires_in': 3600}))
    state = models.handle('GET', '/model/codex')[1]
    assert state['logged_in'] and state['login']['status'] == 'completed'
    assert fresh['access'] not in json.dumps(state)
    models.secrets.write(models.oauth.path, json.dumps(credential(expired=True)))
    _, job = models.handle('POST', '/model/jobs', {'purpose': 'test'})
    [request] = models.take_requests()
    assert 'grant_type=refresh_token' in request['body']
    models.complete_request(request['id'], json_response({'access_token': fresh['access'], 'refresh_token': fresh['refresh'], 'expires_in': 3600}))
    [request] = models.take_requests()
    assert request['url'] == 'https://chatgpt.com/backend-api/codex/responses'
    body = {'type': 'response.completed', 'response': {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'OK'}]}]}}
    models.complete_request(request['id'], {'status': 200, 'headers': {'content-type': 'text/event-stream'}, 'body': 'data: ' + json.dumps(body) + '\n\n'})
    assert job_state(models, job)['status'] == 'completed'


def test_browser_logout_or_cancel_blocks_late_oauth(tmp_path):
    models = make_models(tmp_path)
    _, attempt = models.handle('POST', '/model/codex/login', {'method': 'device'})
    [request] = models.take_requests()
    models.handle('POST', f"/model/codex/login/{attempt['id']}/cancel", {})
    models.complete_request(request['id'], json_response({'device_auth_id': 'synthetic-device', 'user_code': 'SYNTH-1234', 'interval': 1}))
    assert models.take_requests() == []
    assert models.handle('GET', '/model/codex')[1]['logged_in'] is False
    select(models, auth_mode='codex', base_url='https://chatgpt.com/backend-api', api_key=None)
    models.secrets.write(models.oauth.path, json.dumps(credential(expired=True)))
    _, job = models.handle('POST', '/model/jobs', {'purpose': 'test'})
    [request] = models.take_requests()
    models.handle('POST', '/model/codex/logout', {})
    models.complete_request(request['id'], json_response({'access_token': credential()['access'], 'refresh_token': 'synthetic-refresh', 'expires_in': 3600}))
    assert models.take_requests() == []
    assert job_state(models, job)['status'] == 'cancelled'
    assert not models.oauth.path.exists()


@pytest.mark.parametrize('invalid', ['none', 'stale', 'reference'])
def test_browser_consult_uses_core_validation_and_saves_atomically(tmp_path, invalid):
    models = make_models(tmp_path)
    select(models)
    consultation_id = uuid4().hex
    with storage.connect(tmp_path) as conn:
        conn.execute('INSERT INTO consultations VALUES(?,?,?,?,?,?)',
                     (consultation_id, 'Synthetic', storage.encode({'facts': [], 'symptoms': []}), 1, storage.now(), storage.now()))
    status, job = models.handle('POST', '/model/jobs', {'purpose': 'consult', 'consultation_id': consultation_id, 'allow_send': True})
    assert status == 200, job
    [request] = models.take_requests()
    answer = {'stage': 'follow_up', 'summary': 'Synthetic follow-up', 'questions': [], 'syndromes': [],
              'formulas': [], 'risks': [], 'limitations': [], 'evidence_ids': []}
    if invalid == 'stale':
        with storage.connect(tmp_path) as conn:
            conn.execute('UPDATE consultations SET revision=revision+1 WHERE id=?', (consultation_id,))
    elif invalid == 'reference':
        answer['evidence_ids'] = ['fabricated-source']
    models.complete_request(request['id'], stream(json.dumps(answer)))
    assert job_state(models, job)['status'] == ('completed' if invalid == 'none' else 'failed')
    with storage.connect(tmp_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM consultation_messages WHERE role='assistant'").fetchone()[0] == int(invalid == 'none')
        assert conn.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0] == int(invalid == 'none')
    if invalid == 'none':
        restarted = make_models(tmp_path)
        assert job_state(restarted, job)['result']['summary'] == 'Synthetic follow-up'


def test_browser_checkpoint_rolls_back_cancellation_and_keeps_callbacks(tmp_path):
    models = make_models(tmp_path)
    select(models)
    _, job = models.handle('POST', '/model/jobs', {'purpose': 'test'})
    [request] = models.take_requests()
    checkpoint = models.checkpoint()
    models.handle('POST', f"/model/jobs/{job['id']}/cancel", {})
    assert models.pending_request_ids() == []
    models.restore_checkpoint(checkpoint)
    assert models.pending_request_ids() == [request['id']]
    assert job_state(models, job)['status'] == 'running'
    models.complete_request(request['id'], stream())
    assert job_state(models, job)['status'] == 'completed'


def test_browser_checkpoint_rolls_back_login_and_response_failure_is_private(tmp_path):
    models = make_models(tmp_path)
    _, attempt = models.handle('POST', '/model/codex/login', {'method': 'device'})
    [request] = models.take_requests()
    checkpoint = models.checkpoint()
    models.handle('POST', f"/model/codex/login/{attempt['id']}/cancel", {})
    assert models.pending_request_ids() == []
    models.restore_checkpoint(checkpoint)
    models.complete_request(request['id'], json_response({'device_auth_id': 'synthetic-device', 'user_code': 'SYNTH-1234', 'interval': 1}))
    assert models.handle('GET', '/model/codex')[1]['login']['stage'] == 'waiting_authorization'
    [request] = models.take_requests()
    models.fail_request(request['id'], 'synthetic-key private patient text')
    state = models.handle('GET', '/model/codex')[1]
    assert state['login']['status'] == 'failed'
    assert 'synthetic-key' not in json.dumps(state) and 'private patient' not in json.dumps(state)


def test_browser_uses_no_threads_and_rejects_invalid_network_envelopes(tmp_path, monkeypatch):
    import threading
    monkeypatch.setattr(threading, 'Thread', lambda *args, **kwargs: pytest.fail('Browser jobs must not start threads'))
    models = make_models(tmp_path)
    select(models)
    _, job = models.handle('POST', '/model/jobs', {'purpose': 'test'})
    [request] = models.take_requests()
    models.complete_request(request['id'], {'status': True, 'headers': {}, 'body': 'synthetic-key private text'})
    result = job_state(models, job)
    assert result['status'] == 'failed'
    assert 'synthetic-key' not in json.dumps(result) and 'private text' not in json.dumps(result)


def test_browser_device_poll_backoff_and_expiry(tmp_path):
    models = make_models(tmp_path)
    models.handle('POST', '/model/codex/login', {'method': 'device'})
    [request] = models.take_requests()
    models.complete_request(request['id'], json_response({'device_auth_id': 'synthetic-device', 'user_code': 'SYNTH-1234', 'interval': 1}))
    [request] = models.take_requests()
    models.complete_request(request['id'], json_response({'error': 'slow_down'}, status=429))
    [request] = models.take_requests()
    assert request['delay_ms'] == 6000
    models.oauth.attempt['_deadline'] = time.monotonic() - 1
    models.complete_request(request['id'], json_response({'authorization_code': 'synthetic-code', 'code_verifier': 'synthetic-verifier'}))
    assert models.take_requests() == []
    assert models.handle('GET', '/model/codex')[1]['login']['status'] == 'failed'


def test_browser_refresh_shared_by_jobs_and_rollback_preserves_waiters(tmp_path):
    models = make_models(tmp_path)
    select(models, auth_mode='codex', base_url='https://chatgpt.com/backend-api', api_key=None)
    models.secrets.write(models.oauth.path, json.dumps(credential(expired=True)))
    _, first = models.handle('POST', '/model/jobs', {'purpose': 'test'})
    _, second = models.handle('POST', '/model/jobs', {'purpose': 'test'})
    [request] = models.take_requests()
    checkpoint = models.checkpoint()
    models.handle('POST', f"/model/jobs/{first['id']}/cancel", {})
    models.restore_checkpoint(checkpoint)
    fresh = credential()
    models.complete_request(request['id'], json_response({'access_token': fresh['access'], 'refresh_token': fresh['refresh'], 'expires_in': 3600}))
    assert len(models.take_requests()) == 2
    assert job_state(models, first)['status'] == 'running'
    assert job_state(models, second)['status'] == 'running'


def test_browser_other_tab_logout_invalidates_old_request_even_after_relogin(tmp_path):
    models = make_models(tmp_path)
    select(models, auth_mode='codex', base_url='https://chatgpt.com/backend-api', api_key=None)
    models.secrets.write(models.oauth.path, json.dumps(credential()))
    _, job = models.handle('POST', '/model/jobs', {'purpose': 'test'})
    [request] = models.take_requests()
    other = make_models(tmp_path)
    other.handle('POST', '/model/codex/logout', {})
    other.secrets.write(other.oauth.path, json.dumps(credential()))
    body = {'type': 'response.completed', 'response': {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'OK'}]}]}}
    models.complete_request(request['id'], {'status': 200, 'headers': {}, 'body': 'data: ' + json.dumps(body) + '\n\n'})
    assert job_state(models, job)['status'] == 'failed'
    with storage.connect(tmp_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0] == 0
