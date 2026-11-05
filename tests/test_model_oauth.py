import json,time
from io import StringIO
from pathlib import Path
import threading
from app.model_oauth import OAuthManager

CREDENTIAL={'type':'oauth','access':'synthetic-access','refresh':'synthetic-refresh','expires':int(time.time()*1000)+3600000,'accountId':'synthetic'}


def test_oauth_status_never_returns_credentials_and_refresh_is_serialized(tmp_path,monkeypatch):
    manager=OAuthManager(tmp_path)
    manager.save_credential(CREDENTIAL)
    state=manager.status()
    assert state['logged_in'] and 'synthetic-access' not in json.dumps(state)
    assert 'synthetic-refresh' not in (tmp_path/'codex-secret.dpapi').read_bytes().decode('latin1')
    expired={**CREDENTIAL,'expires':1};manager.save_credential(expired)
    calls=[]
    def refresh(c):
        calls.append(1);time.sleep(.05);return {**CREDENTIAL,'access':'new-synthetic-access'}
    monkeypatch.setattr(manager,'_refresh',refresh)
    results=[]
    threads=[threading.Thread(target=lambda:results.append(manager.access_token())) for _ in range(2)]
    for t in threads:t.start()
    for t in threads:t.join()
    assert results==['new-synthetic-access']*2 and len(calls)==1
    manager.logout();assert not manager.status()['logged_in']


def test_cancelled_login_does_not_replace_existing_account(tmp_path,monkeypatch):
    manager=OAuthManager(tmp_path);manager.save_credential(CREDENTIAL)
    entered,release=threading.Event(),threading.Event()
    class Process:
        stdin=StringIO();returncode=0
        def __init__(self):self.stdout=self.lines()
        def lines(self):
            entered.set();release.wait(3)
            yield json.dumps({'type':'credential','credential':{**CREDENTIAL,'access':'cancelled-access'}})+'\n'
        def poll(self):return 0
        def wait(self,timeout=None):return 0
        def kill(self):pass
    monkeypatch.setattr(manager,'_spawn',lambda *a:Process())
    started=manager.start('device');assert entered.wait(2)
    manager.cancel(started['id']);release.set();time.sleep(.1)
    assert manager.access_token()=='synthetic-access'
    assert manager.status()['login']['status']=='cancelled'


def test_device_code_exposes_only_verification_url_and_code(tmp_path,monkeypatch):
    manager=OAuthManager(tmp_path)
    ready,release=threading.Event(),threading.Event()
    class Process:
        returncode=0
        def __init__(self):self.stdin=StringIO();self.stdout=self.lines()
        def lines(self):
            yield json.dumps({'type':'device_code','userCode':'ABCD-1234','verificationUri':'https://auth.openai.com/codex/device'})+'\n'
            ready.set();release.wait(3)
        def wait(self,timeout=None):return 0
        def poll(self):return 0
        def kill(self):release.set()
    monkeypatch.setattr(manager,'_spawn',lambda:Process())
    started=manager.start('device');assert ready.wait(2)
    status=manager.status()
    assert status['login']['device_code']=={'url':'https://auth.openai.com/codex/device','code':'ABCD-1234'}
    assert not status['logged_in']
    manager.cancel(started['id']);release.set()



def test_refresh_keeps_private_pipe_open_until_terminal_credential(tmp_path,monkeypatch):
    manager=OAuthManager(tmp_path)
    class Process:
        returncode=0
        def __init__(self):self.stdin=StringIO();self.stdout=self.lines()
        def lines(self):
            assert not self.stdin.closed and 'refresh' in self.stdin.getvalue()
            yield json.dumps({'type':'credential','credential':CREDENTIAL})+'\n'
        def poll(self):return 0
        def wait(self,timeout=None):return 0
        def kill(self):pass
    monkeypatch.setattr(manager,'_spawn',lambda:Process())
    assert manager._refresh(CREDENTIAL)==CREDENTIAL



def test_codex_config_does_not_require_api_key_or_return_tokens(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app(tmp_path),base_url='http://127.0.0.1',client=('127.0.0.1',5000)) as client:
        h={'X-CSRF-Token':client.get('/api/session').json()['csrf_token']}
        result=client.put('/api/model/config',json={'auth_mode':'codex','model':'synthetic'},headers=h)
        assert result.status_code==200,result.text
        assert result.json()['base_url']=='https://chatgpt.com/backend-api'
        assert not result.json()['has_oauth']
        missing=client.post('/api/model/jobs',json={'purpose':'test'},headers=h)
        assert missing.status_code==409
        assert client.get('/api/model/codex').status_code==200


def test_codex_job_passes_only_access_token_to_isolated_bridge(tmp_path,monkeypatch):
    import json
    from fastapi.testclient import TestClient
    from app import model
    from app.main import create_app
    fake_root=tmp_path/'bridge-root';bridge=fake_root/'ai-bridge';bridge.mkdir(parents=True);(bridge/'node_modules').mkdir()
    script="""let input='';process.stdin.on('data',d=>{input+=d;if(input.includes('\\n')){const r=JSON.parse(input.split('\\n')[0]);if(r.auth_mode!=='codex'||r.base_url!=='https://chatgpt.com/backend-api'||r.api_key!=='synthetic-access'||JSON.stringify(r).includes('synthetic-refresh'))process.exit(2);process.stdout.write(JSON.stringify({type:'done',text:'Synthetic connection complete',usage:{},stop_reason:'stop'})+'\\n',()=>process.exit(0));}});"""
    (bridge/'bridge.mjs').write_text(script,encoding='utf-8')
    monkeypatch.setattr(model,'ROOT',fake_root)
    OAuthManager(tmp_path).save_credential(CREDENTIAL)
    with TestClient(create_app(tmp_path),base_url='http://127.0.0.1',client=('127.0.0.1',5000)) as client:
        h={'X-CSRF-Token':client.get('/api/session').json()['csrf_token']}
        assert client.put('/api/model/config',json={'auth_mode':'codex','model':'synthetic'},headers=h).status_code==200
        started=client.post('/api/model/jobs',json={'purpose':'test'},headers=h)
        assert started.status_code==200,started.text
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            job=client.get('/api/model/jobs/'+started.json()['id']).json()
            if job['status'] not in ('queued','running'):break
            time.sleep(.05)
        assert job['status']=='completed',job
        assert 'synthetic-access' not in json.dumps(job)
        assert 'synthetic-refresh' not in json.dumps(client.get('/api/model/codex').json())
