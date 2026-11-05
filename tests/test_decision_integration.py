"""Synthetic engineering fixtures; not medical evidence or treatment cases."""
from contextlib import closing
from copy import deepcopy
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from app import decision, personal, storage
from app.main import create_app


@pytest.fixture
def mapped_client(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        headers = {"X-CSRF-Token": client.get("/api/session").json()["csrf_token"]}
        raw = "工程测试方：测试甲二两。仅测试有出处的输入映射。"
        sha = hashlib.sha256(raw.encode()).hexdigest()
        originals = tmp_path / "originals"; originals.mkdir(exist_ok=True)
        (originals / (sha + ".txt")).write_bytes(raw.encode())
        def claim(key, kind):
            return dict(id=key,kind=kind,text="合成工程断言",anchor_ids=["a"],inference="literal",scope="合成",limitations=[])
        p = dict(format_version=1,id="fixture",version=1,title="合成映射包",anchors=[dict(id="a",source_id=sha,unit_no=1,start=0,end=len(raw),quote=raw,unit_sha256=hashlib.sha256(raw.encode()).hexdigest(),layer="reference_author",attribution="测试夹具",version_label="fixture-1")],claims=[claim("identity","identity"),claim("dose","dose"),claim("need","necessary")],formulas=[dict(version_id="fixture-f1",catalog_id="guizhi_tang",name="工程测试方",identity_claim_ids=["identity"],components=[dict(name="测试甲",processing=None,source_dose="二",source_unit="两",provenance=dict(name=["identity"],processing=[],source_dose=["dose"],source_unit=["dose"]))],preparation=[],limitations=[])],nodes=[dict(id="fixture-n",label="合成分支",kind="pattern",scope="测试",scope_claim_ids=[],formula_version_id="fixture-f1",conditions=[dict(id="n1",role="required",expr={"fact":"测试症候"},claim_ids=["need"])],questions=[dict(key="测试症候",question="测试症候存在吗？",reason="工程鉴别测试",claim_ids=["need"])],limitations=[])],edges=[],modifications=[])
        with closing(storage.connect(tmp_path)) as conn:
            conn.execute('INSERT INTO text_sources VALUES(?,?,?,?,?)',(sha,'合成书','txt',1,'utf8'))
            conn.execute('INSERT INTO source_catalog VALUES(?,?)',(sha,'reference'))
            conn.execute('INSERT INTO source_units(source_id,unit_no,locator,raw_text,search_text) VALUES(?,?,?,?,?)',(sha,1,json.dumps({'kind':'line_range','start':1,'end':1}),raw,raw))
            decision.initialize(conn)
            decision.import_package(conn,p); conn.commit()
        case=client.post('/api/consultations',json={'intake':{'facts':[dict(key='测试症候',state='present',verified=True)]}},headers=headers).json()
        yield client,headers,case,p


def assessment(version=True):
    f = dict(formula_id='guizhi_tang',name='工程测试方',components=[],evidence_ids=['decision:fixture@1:a'])
    if version: f.update(formula_version_id='fixture-f1',decision_package_id='fixture',decision_package_version=1)
    return json.dumps(dict(stage='assessment',summary='合成结果',questions=[],syndromes=[],formulas=[f],risks=[],limitations=[],evidence_ids=[]))


def test_decision_api_and_model_input_share_frozen_source_graph(mapped_client):
    client,headers,case,p=mapped_client
    coverage=client.get('/api/decision/coverage')
    assert coverage.status_code==200
    assert coverage.json()['mapped_formulas']==1
    response=client.post('/api/decision/evaluate',json={'facts':[]},headers=headers)
    assert response.status_code==200 and response.json()['nodes'][0]['status']=='pending'
    context=client.get(f"/api/consultations/{case['id']}/context").json()
    assert context['decision_graph']['packages'][0]['snapshot']==p
    assert any(f.get('formula_version_id')=='fixture-f1' for f in context['formula_candidates'])
    assert any(e['id']=='decision:fixture@1:a' and e['source_layer']=='reference_author' for e in context['evidence'])
    with closing(storage.connect(client.app.state.data_dir)) as conn:
        frozen,payload,system=personal.prepare_task(conn,case['id'])
    assert json.loads(payload)['decision_graph']['nodes']==frozen['decision_graph']['nodes']
    assert '不预设固定' in system


def test_mapped_formula_backfills_each_field_and_rejects_unbound_version(mapped_client):
    client,headers,case,p=mapped_client
    context=client.get(f"/api/consultations/{case['id']}/context").json()
    result=personal.validate_consult_result(assessment(),context)
    f=result['formulas'][0]
    assert f['source_kind']=='source_mapped'
    assert f['components'][0]['name']=='测试甲' and f['components'][0]['source_dose']=='二'
    assert f['components'][0]['field_sources']['source_dose'][0]['claim_id']=='dose'
    assert f['components'][0]['field_sources']['processing']==[]
    assert any(c['claim_id']=='need' for c in f['decision_sources'])
    assert result['deterministic_assessment']['source_claims']
    with pytest.raises(ValueError,match='版本'):
        personal.validate_consult_result(assessment(False),context)
    context['decision_graph']['nodes'][0]['status']='excluded'
    with pytest.raises(ValueError): personal.validate_consult_result(assessment(),context)


def test_mapping_update_marks_frozen_task_stale_without_rewriting_it(mapped_client):
    client,headers,case,p=mapped_client
    with closing(storage.connect(client.app.state.data_dir)) as conn:
        frozen,_,_=personal.prepare_task(conn,case['id'])
        p2=deepcopy(p);p2['version']=2
        decision.import_package(conn,p2);conn.commit()
        assert personal.task_warnings(conn,frozen)
        assert frozen['decision_graph']['packages'][0]['version']==1


def test_mapping_payload_is_preserved_in_existing_backup_format(mapped_client,tmp_path):
    from app.backup import create_backup,restore_backup
    client,headers,case,p=mapped_client
    restored=tmp_path/'restored'
    restore_backup(create_backup(client.app.state.data_dir,'synthetic-test-password'),'synthetic-test-password',restored)
    with closing(storage.connect(restored)) as conn:
        assert decision.load_packages(conn)[0]['snapshot']==p


@pytest.mark.parametrize("change", ["dose", "preparation", "modification"])
def test_model_cannot_hide_conflicts_or_unbound_modifications_in_mapped_version(mapped_client, change):
    client,headers,case,p=mapped_client
    context=client.get(f"/api/consultations/{case['id']}/context").json()
    output=json.loads(assessment())
    if change=='dose': output['formulas'][0]['components']=[dict(name='测试甲',source_dose='999')]
    elif change=='preparation': output['formulas'][0]['preparation']='凭空编造的煎服'
    else: output['formulas'][0]['modifications']=[dict(action='add',herb='伪造药',evidence_ids=[])]
    with pytest.raises(ValueError): personal.validate_consult_result(json.dumps(output),context)


@pytest.mark.parametrize("state", ["unknown", "conflict"])
def test_unapplied_mapped_action_is_explicit_outside_collapsed_details(mapped_client, state):
    client,headers,case,p=mapped_client
    p=deepcopy(p);p['version']=2
    p['claims'].append(dict(id='mclaim',kind='modification',text='合成加味动作',anchor_ids=['a'],inference='literal',scope='合成',limitations=[]))
    added=dict(name='测试乙',processing=None,source_dose=None,source_unit=None,provenance=dict(name=['identity'],processing=[],source_dose=[],source_unit=[]))
    p['modifications']=[dict(id='m1',base_version_id='fixture-f1',trigger={'fact':'触发项'},claim_ids=['mclaim'],actions=[dict(operation='add',component=added,claim_ids=['mclaim'])],limitations=[])]
    with closing(storage.connect(client.app.state.data_dir)) as conn:
        decision.import_package(conn,p);conn.commit()
    facts=[dict(key='测试症候',state='present',verified=True),dict(key='触发项',state=state,verified=True)]
    client.put(f"/api/consultations/{case['id']}",json={'expected_revision':1,'intake':{'facts':facts}},headers=headers)
    context=client.get(f"/api/consultations/{case['id']}/context").json()
    output=json.loads(assessment());f=output['formulas'][0]
    f.update(decision_package_version=2,evidence_ids=['decision:fixture@2:a'],source_modification_ids=['m1'])
    result=personal.validate_consult_result(json.dumps(output),context)
    modification=result['formulas'][0]['modifications'][0]
    assert modification['application_status']=='unapplied'
    assert modification['application_reason']
    assert result['formulas'][0]['modification_preview']['applied']==[]



def test_mapped_graph_survives_real_local_bridge_job_and_history(mapped_client):
    import threading,time
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    client,headers,case,p=mapped_client
    captured=[]
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            captured.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            chunk={'choices':[{'index':0,'delta':{'role':'assistant','content':assessment()},'finish_reason':None}]}
            final={'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}
            self.wfile.write(('data: '+json.dumps(chunk)+'\n\ndata: '+json.dumps(final)+'\n\ndata: [DONE]\n\n').encode());self.wfile.flush();self.close_connection=True
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        config=dict(base_url=f'http://127.0.0.1:{server.server_port}/v1',model='synthetic-graph',api_key='synthetic-graph-key',enabled=True,allow_external=True,allow_evidence=True)
        assert client.put('/api/model/config',json=config,headers=headers).status_code==200
        started=client.post('/api/model/jobs',json=dict(purpose='consult',consultation_id=case['id'],allow_send=True),headers=headers)
        assert started.status_code==200,started.text
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            job=client.get('/api/model/jobs/'+started.json()['id']).json()
            if job['status'] not in ('queued','running'):break
            time.sleep(.05)
        assert job['status']=='completed',job
        assert job['result']['formulas'][0]['source_kind']=='source_mapped'
        assert job['result']['formulas'][0]['components'][0]['source_dose']=='二'
        assert job['result']['deterministic_assessment']['nodes']
        record=client.get(f"/api/consultations/{case['id']}").json()
        assert record['messages'][-1]['result']['formulas'][0]['components'][0]['field_sources']['source_dose']
        assert 'decision_graph' in json.dumps(captured) and 'registry_digest' in json.dumps(captured)
        assert case['id'] not in json.dumps(captured)
        assert 'synthetic-graph-key' not in json.dumps(job)
    finally:
        server.shutdown();server.server_close()
