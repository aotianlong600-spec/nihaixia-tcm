import base64
import json
from pathlib import Path
import sqlite3
import threading
import time

import pytest


class Secrets:
    def __init__(self):
        self.values = {}
        self.reads = 0

    def read(self, path):
        self.reads += 1
        return self.values.get(str(path)) if Path(path).exists() else None

    def write(self, path, value):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b'synthetic encrypted bytes')
        self.values[str(path)] = value


def response(text='OK', complete=True):
    events = [{'choices':[{'delta':{'content':text},'finish_reason':None}]}]
    if complete:
        events += [{'choices':[{'delta':{},'finish_reason':'stop'}]}]
    body = ''.join('data: '+json.dumps(e)+'\n\n' for e in events)
    return {'status':200,'headers':{'content-type':'text/event-stream'},'body':body+('data: [DONE]\n\n' if complete else '')}


def profile(**extra):
    return {'name':'Synthetic','auth_mode':'api_key','base_url':'https://example.test/v1','model':'synthetic',
            'api_key':'synthetic-key','enabled':True,'allow_external':True,'allow_evidence':True,**extra}


def make_models(tmp_path, http):
    from app.mobile_models import MobileModels
    from app import storage, consultation_core, library
    storage.initialize(tmp_path)
    with storage.connect(tmp_path) as conn:
        library.initialize(conn, tmp_path)
        consultation_core.initialize(conn)
    secrets = Secrets()
    return MobileModels(tmp_path, http, secrets), secrets


def selected(models, **extra):
    status, item = models.handle('POST','/model/profiles',profile(**extra))
    assert status == 200, item
    status, cfg = models.handle('POST',f"/model/profiles/{item['id']}/select",{})
    assert status == 200
    return cfg


def wait_job(models, job):
    deadline = time.monotonic()+3
    while time.monotonic()<deadline:
        status, value = models.handle('GET','/model/jobs/'+job['id'],None)
        assert status == 200
        if value['status'] not in ('queued','running'):
            return value
        time.sleep(.01)
    pytest.fail('Synthetic model job did not finish')


def test_native_profiles_and_stale_selection_never_expose_or_read_keys(tmp_path):
    models, secrets = make_models(tmp_path,lambda *args: response())
    cfg = selected(models)
    assert cfg['has_key'] and 'synthetic-key' not in json.dumps(cfg)
    assert models.handle('PUT','/model/profiles/'+cfg['profile_id'],profile(base_url='https://other.test',api_key=None))[0] == 409
    assert models.handle('PUT','/model/profiles/'+cfg['profile_id'],profile(reasoning_effort='high'))[0] == 200
    before = secrets.reads
    status, _ = models.handle('POST','/model/jobs',{'purpose':'test','expected_profile_id':cfg['profile_id'],'expected_profile_revision':cfg['profile_revision']})
    assert status == 409 and secrets.reads == before
    assert models.handle('DELETE','/model/profiles/'+cfg['profile_id'],None)[0] == 200
    assert models.handle('POST','/model/jobs',{'purpose':'test'})[0] == 409


@pytest.mark.parametrize('complete',[True,False])
def test_native_jobs_require_terminal_completion_and_explicit_effort(tmp_path, complete):
    calls = []
    def http(*args):
        calls.append(args)
        return response(complete=complete)
    models, _ = make_models(tmp_path,http)
    selected(models,reasoning_effort='none')
    status, job = models.handle('POST','/model/jobs',{'purpose':'test'})
    assert status == 200
    result = wait_job(models,job)
    assert result['status'] == ('completed' if complete else 'failed')
    body = json.loads(calls[0][3])
    assert body['reasoning_effort'] == 'none' and 'thinking' not in body and 'tools' not in body
    assert 'Synthetic' in body['messages'][-1]['content']
    with sqlite3.connect(tmp_path/'clinical.sqlite3') as conn:
        assert conn.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0] == int(complete)


def test_cancel_discards_a_late_success_without_persisting(tmp_path):
    started, release = threading.Event(), threading.Event()
    def http(*args):
        started.set(); assert release.wait(3)
        return response()
    models, _ = make_models(tmp_path,http)
    selected(models)
    _, job = models.handle('POST','/model/jobs',{'purpose':'test'})
    assert started.wait(2)
    assert models.handle('POST','/model/jobs/'+job['id']+'/cancel',{})[1]['status'] == 'cancelled'
    release.set()
    assert models.jobs[job['id']]['_done'].wait(2)
    with sqlite3.connect(tmp_path/'clinical.sqlite3') as conn:
        assert conn.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0] == 0


def test_cancel_before_transport_dispatch_does_not_contact_provider(tmp_path):
    calls = []
    models, _ = make_models(tmp_path, lambda *args: calls.append(args) or response())
    selected(models)
    original = models._model_response
    def cancel_before_dispatch(job, *args):
        with models.guard:
            models._cancel_job(job)
        return original(job, *args)
    models._model_response = cancel_before_dispatch
    status, job = models.handle('POST','/model/jobs',{'purpose':'test'})
    assert status == 200
    assert wait_job(models,job)['status'] == 'cancelled'
    assert calls == []


def token():
    payload={'https://api.openai.com/auth':{'chatgpt_account_id':'synthetic-account'}}
    return 'e30.'+base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')+'.synthetic'


def test_device_login_and_refresh_are_app_owned_and_private(tmp_path):
    calls = []
    def http(method,url,headers,body,request_id,timeout):
        calls.append((url,body))
        if url.endswith('/usercode'):
            value={'device_auth_id':'internal-id','user_code':'SYNTH-1234','interval':0}
        elif url.endswith('/deviceauth/token'):
            value={'authorization_code':'synthetic-code','code_verifier':'synthetic-verifier'}
        else:
            assert url=='https://auth.openai.com/oauth/token'
            value={'access_token':token(),'refresh_token':'synthetic-refresh','expires_in':3600}
        return {'status':200,'headers':{},'body':json.dumps(value)}
    models, secrets = make_models(tmp_path,http)
    status, _ = models.handle('POST','/model/codex/login',{'method':'device'})
    assert status == 200
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        state=models.handle('GET','/model/codex',None)[1]
        if state.get('login',{}).get('status')=='completed':break
        time.sleep(.01)
    assert state['logged_in'] and state['login']['status']=='completed'
    assert token() not in json.dumps(state) and 'synthetic-refresh' not in json.dumps(state)
    credential=json.loads(secrets.read(models.oauth.path));credential['expires']=time.time()*1000-1
    secrets.write(models.oauth.path,json.dumps(credential))
    assert models.oauth.access_token()[0]==token()
    assert any('grant_type=refresh_token' in body for _,body in calls)
    assert models.handle('POST','/model/codex/logout',{})[1]['logged_in'] is False


def test_unknown_provider_error_never_echoes_input_or_key(tmp_path):
    models,_=make_models(tmp_path,lambda *args:{'status':400,'headers':{},'body':'synthetic-key private patient text'})
    selected(models)
    _,job=models.handle('POST','/model/jobs',{'purpose':'test'})
    result=wait_job(models,job)
    assert result['status']=='failed'
    assert 'synthetic-key' not in json.dumps(result) and 'private patient' not in json.dumps(result)


def test_codex_uses_fixed_endpoint_no_summary_override_and_rejects_unknown_effort_before_credentials(tmp_path):
    calls=[]
    def http(*args):
        calls.append(args)
        event={'type':'response.completed','response':{'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'OK'}]}]}}
        return {'status':200,'headers':{},'body':'data: '+json.dumps(event)+'\n\n'}
    models,secrets=make_models(tmp_path,http)
    secrets.write(models.oauth.path,json.dumps({'type':'oauth','access':token(),'refresh':'synthetic-refresh','expires':time.time()*1000+3600000,'accountId':'synthetic-account'}))
    cfg=selected(models,auth_mode='codex',base_url='',api_key=None,model='gpt-6.1-sol',reasoning_effort='low')
    _,job=models.handle('POST','/model/jobs',{'purpose':'test'})
    assert wait_job(models,job)['status']=='completed'
    assert calls[0][1]=='https://chatgpt.com/backend-api/codex/responses'
    assert calls[0][2]['ChatGPT-Account-Id']=='synthetic-account'
    body=json.loads(calls[0][3]);assert body['reasoning']=={'effort':'low'} and body['tools']==[] and body['tool_choice']=='none'
    assert models.handle('PUT','/model/profiles/'+cfg['profile_id'],profile(auth_mode='codex',base_url='',api_key=None,model='unknown-codex',reasoning_effort='high'))[0]==200
    reads=secrets.reads
    assert models.handle('POST','/model/jobs',{'purpose':'test'})[0]==409
    assert secrets.reads==reads and len(calls)==1


def test_device_cancel_does_not_save_a_late_authorization(tmp_path):
    started,release=threading.Event(),threading.Event()
    def http(method,url,*args):
        if url.endswith('/usercode'):
            return {'status':200,'headers':{},'body':json.dumps({'device_auth_id':'internal','user_code':'SYNTH-1234','interval':0})}
        started.set();assert release.wait(3)
        return {'status':200,'headers':{},'body':json.dumps({'authorization_code':'late','code_verifier':'late'})}
    models,secrets=make_models(tmp_path,http)
    _,attempt=models.handle('POST','/model/codex/login',{'method':'device'})
    assert started.wait(2)
    assert models.handle('POST','/model/codex/login/'+attempt['id']+'/cancel',{})[1]['status']=='cancelled'
    release.set();time.sleep(.05)
    status=models.handle('GET','/model/codex',None)[1]
    assert not status['logged_in'] and status['login']['status']=='cancelled'
    assert not models.oauth.path.exists()


def test_logout_cannot_be_undone_by_a_late_refresh(tmp_path):
    started,release=threading.Event(),threading.Event()
    def http(*args):
        started.set();assert release.wait(3)
        return {'status':200,'headers':{},'body':json.dumps({'access_token':token(),'refresh_token':'new-refresh','expires_in':3600})}
    models,secrets=make_models(tmp_path,http)
    secrets.write(models.oauth.path,json.dumps({'type':'oauth','access':token(),'refresh':'old-refresh','expires':1,'accountId':'synthetic-account'}))
    errors=[]
    def refreshing():
        try:models.oauth.access_token()
        except Exception as e:errors.append(type(e).__name__)
    thread=threading.Thread(target=refreshing);thread.start()
    assert started.wait(2)
    models.handle('POST','/model/codex/logout',{})
    release.set();thread.join(2)
    assert errors and not models.oauth.path.exists()
    assert models.handle('GET','/model/codex',None)[1]['logged_in'] is False


@pytest.mark.parametrize('action', ['cancel', 'logout', 'delete'])
def test_job_is_registered_before_codex_refresh_and_cancelled_refresh_cannot_send(tmp_path, action):
    from app import storage
    from uuid import uuid4

    started, release, returned = threading.Event(), threading.Event(), threading.Event()
    provider_calls, reply = [], []
    def http(method, url, *args):
        if url.endswith('/oauth/token'):
            started.set()
            assert release.wait(3)
            return {'status':200,'headers':{},'body':json.dumps({'access_token':token(),'refresh_token':'synthetic-fresh','expires_in':3600})}
        provider_calls.append(url)
        answer = json.dumps({'stage':'follow_up','summary':'Synthetic','questions':[],
                             'syndromes':[],'formulas':[],'risks':[],'limitations':[],'evidence_ids':[]})
        event = {'type':'response.completed','response':{'status':'completed','output':[
            {'type':'message','content':[{'type':'output_text','text':answer}]}]}}
        return {'status':200,'headers':{},'body':'data: '+json.dumps(event)+'\n\n'}
    models, secrets = make_models(tmp_path, http)
    secrets.write(models.oauth.path,json.dumps({'type':'oauth','access':token(),'refresh':'synthetic-old',
                  'expires':1,'accountId':'synthetic-account'}))
    cfg = selected(models,auth_mode='codex',base_url='',api_key=None,model='gpt-6.1-sol')
    case_id = uuid4().hex
    with storage.connect(tmp_path) as conn:
        conn.execute('INSERT INTO consultations VALUES(?,?,?,?,?,?)',
                     (case_id,'Synthetic',storage.encode({'facts':[],'symptoms':[]}),1,storage.now(),storage.now()))
    def start():
        try:
            reply.append(models.handle('POST','/model/jobs',{'purpose':'consult','consultation_id':case_id,'allow_send':True}))
        finally:
            returned.set()
    caller = threading.Thread(target=start)
    caller.start()
    try:
        assert started.wait(2)
        assert returned.wait(.5), 'POST waited for cloud refresh instead of returning a registered job ID'
        status, job = reply[0]
        assert status == 200 and job['id'] in models.jobs
        if action == 'cancel':
            assert models.handle('POST','/model/jobs/'+job['id']+'/cancel',{})[0] == 200
        elif action == 'logout':
            assert models.handle('POST','/model/codex/logout',{})[0] == 200
        else:
            assert models.handle('DELETE','/model/profiles/'+cfg['profile_id'],None)[0] == 200
        release.set()
        assert models.jobs[job['id']]['_done'].wait(2)
        assert wait_job(models,job)['status'] == 'cancelled'
        assert provider_calls == []
        with storage.connect(tmp_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM consultation_messages WHERE role='assistant'").fetchone()[0] == 0
            assert conn.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0] == 0
    finally:
        release.set()
        caller.join(2)
        for job in list(models.jobs.values()):
            job['_done'].wait(2)


@pytest.mark.parametrize('stale',[False,True])
def test_native_consult_validates_and_saves_only_current_complete_result(tmp_path,stale):
    from app import storage
    from uuid import uuid4
    consultation_id=uuid4().hex
    answer={'stage':'follow_up','summary':'Synthetic follow-up','questions':[{'key':'synthetic','question':'Synthetic question?','reason':'Synthetic input'}],
            'syndromes':[],'formulas':[],'risks':[],'limitations':[],'evidence_ids':[]}
    def http(*args):
        if stale:
            with storage.connect(tmp_path) as conn:
                conn.execute('UPDATE consultations SET revision=revision+1 WHERE id=?',(consultation_id,))
        return response(json.dumps(answer))
    models,_=make_models(tmp_path,http)
    selected(models)
    with storage.connect(tmp_path) as conn:
        conn.execute('INSERT INTO consultations VALUES(?,?,?,?,?,?)',(consultation_id,'Synthetic',storage.encode({'facts':[],'symptoms':[]}),1,storage.now(),storage.now()))
        conn.execute('INSERT INTO consultation_messages VALUES(?,?,?,?,?,?,?,?,?)',(uuid4().hex,consultation_id,'user','Synthetic only',None,None,None,1,storage.now()))
    status,job=models.handle('POST','/model/jobs',{'purpose':'consult','consultation_id':consultation_id,'allow_send':True})
    assert status==200
    result=wait_job(models,job)
    assert result['status']==('failed' if stale else 'completed')
    with storage.connect(tmp_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM consultation_messages WHERE role='assistant'").fetchone()[0]==int(not stale)
        assert conn.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0]==int(not stale)
    if not stale:
        restarted,_=make_models(tmp_path,lambda *args:pytest.fail('History read must not contact a model'))
        assert restarted.handle('GET','/model/jobs/'+job['id'],None)[1]['result']['summary']=='Synthetic follow-up'


def test_model_module_imports_without_desktop_native_dependencies(tmp_path):
    import subprocess,sys
    script="""import sys
class Block:
 def find_spec(self,name,*args):
  if name.split('.')[0] in ('fastapi','pydantic','pydantic_core','pdfplumber','pypdfium2','ctypes'):
   raise RuntimeError('Desktop dependency was imported: '+name)
sys.meta_path.insert(0,Block())
from app.mobile_models import MobileModels
from app.model_profiles import ProfileStore
"""
    completed=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True)
    assert completed.returncode==0, completed.stderr
