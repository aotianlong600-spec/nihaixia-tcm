import json,time
from io import StringIO
from pathlib import Path
import threading
import pytest
from app.model_oauth import OAuthManager

CREDENTIAL={'type':'oauth','access':'synthetic-access','refresh':'synthetic-refresh','expires':int(time.time()*1000)+3600000,'accountId':'synthetic'}


@pytest.mark.parametrize('failure',['provider','storage','exit'])
def test_login_failure_reports_safe_stage_instead_of_losing_the_cause(tmp_path,monkeypatch,failure):
    manager=OAuthManager(tmp_path)
    class Process:
        def __init__(self):
            self.stdin=StringIO();self.returncode=0 if failure=='storage' else 1
            events=[{'type':'progress','stage':'exchanging_token'}]
            events.append({'type':'credential','credential':CREDENTIAL} if failure!='provider' else
                {'type':'error','code':'token_http_403','stage':'exchanging_token','message':'synthetic-private-server-body'})
            self.stdout=StringIO(''.join(json.dumps(e)+'\n' for e in events))
        def poll(self):return self.returncode
        def wait(self,timeout=None):return self.returncode
        def kill(self):pass
    monkeypatch.setattr(manager,'_spawn',Process)
    if failure=='storage':
        def fail(value):raise ValueError('synthetic-private-server-body')
        monkeypatch.setattr(manager,'save_credential',fail)
    attempt={'id':'synthetic','status':'pending','method':'browser','generation':0}
    manager.attempt=attempt;manager._login(attempt)
    result=manager.status();login=result['login']
    assert not result['logged_in'] and login['status']=='failed'
    assert login['stage']=={'storage':'saving_credential','provider':'exchanging_token','exit':'validating_credential'}[failure]
    assert login['error_code']=={'storage':'credential_storage','provider':'token_http_403','exit':'bridge_exit'}[failure]
    if failure=='exit':
        assert login['bridge_exit_code']==1 and login['credential_received'] is True
        assert not manager.path.exists()
    assert 'synthetic-private' not in json.dumps(result) and 'synthetic-access' not in json.dumps(result)


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


@pytest.mark.parametrize('held_operation',['access_token','logout'])
def test_codex_logout_serializes_credential_use_and_job_registration(tmp_path,monkeypatch,held_operation):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import closing
    from fastapi import HTTPException
    from app import model,storage
    from app.main import create_app

    app=create_app(tmp_path)
    oauth=app.state.model_oauth
    oauth.save_credential(CREDENTIAL)
    (tmp_path/'model-config.json').write_text(json.dumps({**model.DEFAULT_CONFIG,'auth_mode':'codex','model':'synthetic'}))
    bridge=tmp_path/'bridge-root'/'ai-bridge'
    bridge.mkdir(parents=True);(bridge/'node_modules').mkdir();(bridge/'bridge.mjs').touch()
    monkeypatch.setattr(model,'ROOT',bridge.parent)
    def unexpected_process(*args,**kwargs): raise AssertionError('Cancelled jobs must not start a model bridge')
    monkeypatch.setattr(model.subprocess,'Popen',unexpected_process)
    routes={r.path:r.endpoint for r in app.routes if hasattr(r,'endpoint')}
    start_job=routes['/api/model/jobs'];logout=routes['/api/model/codex/logout']
    cells=dict(zip(start_job.__code__.co_freevars,start_job.__closure__))
    entered,release,lock_attempted,scheduled=(threading.Event() for _ in range(4))
    second_thread=[];blocked=[];deferred=[]
    original_lock=cells['guard'].cell_contents
    class ObservedLock:
        def __enter__(self):
            if second_thread and threading.current_thread() is second_thread[0]:
                acquired=original_lock.acquire(blocking=False)
                blocked.append(not acquired);lock_attempted.set()
                if not acquired: original_lock.acquire()
            else: original_lock.acquire()
        def __exit__(self,*args): original_lock.release()
    monkeypatch.setattr(cells['guard'],'cell_contents',ObservedLock())
    run_job=cells['run_job'].cell_contents
    def defer_job(*args): deferred.append(args);scheduled.set()
    monkeypatch.setattr(cells['run_job'],'cell_contents',defer_job)
    operation=getattr(oauth,held_operation)
    def hold_operation():
        token=operation() if held_operation=='access_token' else None
        entered.set()
        assert release.wait(5)
        return token if held_operation=='access_token' else operation()
    monkeypatch.setattr(oauth,held_operation,hold_operation)
    def start():
        with closing(storage.connect(tmp_path)) as conn,conn:
            return start_job(model.JobInput(purpose='test'),conn)
    def second(action):
        second_thread.append(threading.current_thread())
        return action()
    first_action,second_action=(start,logout) if held_operation=='access_token' else (logout,start)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(first_action)
        try:
            assert entered.wait(5)
            following=pool.submit(second,second_action)
            assert lock_attempted.wait(5)
            assert blocked==[True]
        finally:
            release.set()
        if held_operation=='access_token':
            first.result(timeout=5);assert following.result(timeout=5)=={'logged_in':False}
            assert scheduled.wait(5)
            run_job(*deferred[0])
            assert deferred[0][0]['status']=='cancelled'
        else:
            assert first.result(timeout=5)=={'logged_in':False}
            with pytest.raises(HTTPException) as failure: following.result(timeout=5)
            assert failure.value.status_code==409 and not deferred
    assert not oauth.status()['logged_in']
