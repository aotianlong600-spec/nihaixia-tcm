from fastapi.testclient import TestClient
import pytest
from app.main import create_app

PASSWORD='Synthetic-access-password-123'


def local_client(app): return TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',50001))
def remote_client(app): return TestClient(app,base_url='https://192.168.50.20:8766',client=('192.168.50.30',50002))
def csrf(client): return {'X-CSRF-Token':client.get('/api/session').json()['csrf_token']}


def test_remote_cannot_read_before_local_setup_and_host_cannot_spoof_peer(tmp_path):
    app=create_app(tmp_path,lan_hosts=['192.168.50.20'])
    with remote_client(app) as remote:
        headers=csrf(remote)
        assert remote.get('/api/personal/overview').status_code==403
        assert remote.post('/api/access/setup',json={'password':PASSWORD},headers=headers).status_code==403
        assert remote.post('/api/access/setup',json={'password':PASSWORD},headers={**headers,'X-Forwarded-For':'127.0.0.1'}).status_code==403


def test_local_setup_rotates_session_and_shared_clients_need_password(tmp_path):
    app=create_app(tmp_path,lan_hosts=['192.168.50.20'])
    with local_client(app) as pc,remote_client(app) as phone:
        old=csrf(pc);old_cookie=pc.cookies.get('tcm_session')
        setup=pc.post('/api/access/setup',json={'password':PASSWORD},headers=old)
        assert setup.status_code==200 and setup.json()['authenticated']
        assert pc.cookies.get('tcm_session')!=old_cookie
        assert pc.get('/api/personal/overview').status_code==200
        assert pc.post('/api/consultations',json={},headers=old).status_code==403
        phone_headers=csrf(phone)
        assert phone.get('/api/personal/overview').status_code==401
        assert phone.post('/api/access/login',json={'password':'wrong'},headers=phone_headers).status_code==401
        login=phone.post('/api/access/login',json={'password':PASSWORD},headers=phone_headers)
        assert login.status_code==200 and 'Secure' in login.headers['set-cookie']
        assert 'HttpOnly' in login.headers['set-cookie']
        created=pc.post('/api/consultations',json={'title':'合成双端记录'},headers={'X-CSRF-Token':setup.json()['csrf_token']}).json()
        assert phone.get('/api/consultations/'+created['id']).status_code==200
        new_headers={'X-CSRF-Token':login.json()['csrf_token']}
        assert phone.post('/api/access/logout',json={},headers=new_headers).status_code==200
        assert phone.get('/api/personal/overview').status_code==401
        assert pc.get('/api/personal/overview').status_code==200
        text=(tmp_path/'access.json').read_text()
        assert PASSWORD not in text and 'hash' in text


def test_remote_http_rejected_even_with_password_and_weak_setup_fails(tmp_path):
    app=create_app(tmp_path,lan_hosts=['192.168.50.20'])
    with local_client(app) as pc:
        h=csrf(pc)
        assert pc.post('/api/access/setup',json={'password':'short'},headers=h).status_code==422
        assert pc.post('/api/access/setup',json={'password':PASSWORD},headers=h).status_code==200
    with TestClient(app,base_url='http://192.168.50.20',client=('192.168.50.30',5)) as remote:
        h=csrf(remote)
        assert remote.post('/api/access/login',json={'password':PASSWORD},headers=h).status_code==403


def test_bruteforce_is_limited_and_corrupt_config_fails_closed(tmp_path):
    app=create_app(tmp_path,lan_hosts=['192.168.50.20'])
    with local_client(app) as pc:
        assert pc.post('/api/access/setup',json={'password':PASSWORD},headers=csrf(pc)).status_code==200
    with remote_client(app) as phone:
        h=csrf(phone)
        statuses=[phone.post('/api/access/login',json={'password':'bad'},headers=h).status_code for _ in range(7)]
        assert 429 in statuses
    (tmp_path/'access.json').write_text('{}')
    with remote_client(app) as phone:
        assert phone.get('/api/personal/overview').status_code==401
        assert phone.post('/api/access/login',json={'password':PASSWORD},headers=csrf(phone)).status_code in (400,429)


def test_invalid_password_is_not_reflected_in_validation_response(tmp_path):
    with local_client(create_app(tmp_path)) as pc:
        secret='synthetic-secret-'*30
        response=pc.post('/api/access/setup',json={'password':secret},headers=csrf(pc))
        assert response.status_code==422
        assert secret not in response.text and 'input' not in response.json()['detail'][0]
