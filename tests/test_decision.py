import hashlib
import sqlite3
from copy import deepcopy
import pytest
from app import decision, library


@pytest.fixture
def store(tmp_path):
    conn = sqlite3.connect(':memory:')
    library.initialize(conn, tmp_path)
    decision.initialize(conn)
    raw = 'synthetic source: A B C'
    source = 'a' * 64
    conn.execute('INSERT INTO text_sources VALUES (?,?,?,?,?)', (source, 'synthetic', 'txt', 1, 'utf8'))
    conn.execute('INSERT INTO source_units (source_id,unit_no,locator,raw_text) VALUES (?,?,?,?)', (source, 1, '{}', raw))
    conn.execute('INSERT INTO source_catalog VALUES (?,?)', (source, 'reference'))
    anchor = dict(id='a', source_id=source, unit_no=1, start=0, end=len(raw), quote=raw, unit_sha256=hashlib.sha256(raw.encode()).hexdigest(), layer='reference_author', attribution='synthetic', version_label='v1')
    def claim(id, kind): return dict(id=id, kind=kind, text='synthetic', anchor_ids=['a'], inference='literal', scope='synthetic', limitations=[])
    component = dict(name='A', processing='raw', source_dose='1', source_unit='unit', provenance=dict(name=['identity'], processing=['processing'], source_dose=['dose'], source_unit=['dose']))
    p = dict(format_version=1, id='p', version=1, title='synthetic', anchors=[anchor], claims=[claim('identity','identity'),claim('processing','processing'),claim('dose','dose'),claim('necessary','necessary'),claim('support','support'),claim('mod','modification')], formulas=[dict(version_id='f1',catalog_id='f',name='F',identity_claim_ids=['identity'],components=[component],preparation=[],limitations=[])], nodes=[dict(id='n',label='N',kind='pattern',scope='synthetic',scope_claim_ids=['support'],formula_version_id='f1',conditions=[dict(id='c',role='required',expr={'any':[{'fact':'x'},{'fact':'y'}]},claim_ids=['necessary'])],questions=[dict(key='x',question='x?',reason='?',claim_ids=['necessary']),dict(key='y',question='y?',reason='?',claim_ids=['necessary'])],limitations=[])],edges=[],modifications=[])
    return conn, p


def fact(key, state='present', **extra):
    return dict(key=key,state=state,verified=True,scope='current',subject='patient',**extra)


def test_graph_preserves_or_unknown_conflict_and_ignored_facts(store):
    conn, p = store
    decision.import_package(conn,p)
    result = decision.evaluate(conn,[dict(key='x',state='present',verified=True,scope='history')])
    assert result['nodes'][0]['status'] == 'pending'
    assert {q['key'] for q in result['questions']} == {'x','y'}
    assert result['ignored_facts']
    assert decision.evaluate(conn,[fact('y')])['nodes'][0]['status'] == 'clue'
    assert decision.evaluate(conn,[fact('x'),fact('x','absent')])['nodes'][0]['status'] == 'conflict'


def test_package_immutable_and_source_tampering_fails_closed(store):
    conn,p = store
    decision.import_package(conn,p)
    changed = deepcopy(p); changed['title'] = 'changed'
    with pytest.raises(ValueError): decision.import_package(conn,changed)
    conn.execute("UPDATE source_units SET raw_text='changed'")
    result = decision.evaluate(conn,[])
    assert result['nodes'][0]['status'] == 'source_invalid'
    assert result['source_issues']


def test_fields_require_matching_claims_and_necessary_must_be_literal(store):
    conn,p = store
    p['formulas'][0]['components'][0]['provenance']['source_dose'] = ['identity']
    with pytest.raises(ValueError): decision.import_package(conn,p)
    p['formulas'][0]['components'][0]['provenance']['source_dose'] = ['dose']
    p['claims'][3]['inference'] = 'interpretation'
    with pytest.raises(ValueError): decision.import_package(conn,p)


def test_preview_is_atomic_and_reports_target_difference(store):
    conn,p = store
    base = p['formulas'][0]['components'][0]
    added = deepcopy(base); added['name'] = 'B'; added['source_dose'] = None; added['source_unit'] = None; added['provenance']['source_dose'] = []; added['provenance']['source_unit'] = []
    target = deepcopy(p['formulas'][0]); target['version_id'] = 'f2'; target['components'].append(deepcopy(added)); target['components'][0]['source_dose'] = '2'
    p['formulas'].append(target)
    p['modifications'] = [dict(id='m',base_version_id='f1',target_version_id='f2',trigger={'fact':'x'},claim_ids=['mod'],actions=[dict(operation='add',component=added,claim_ids=['mod'])],limitations=[])]
    decision.import_package(conn,p)
    result = decision.preview_modifications(conn,'p','f1',['m'],[fact('x')])
    assert result['components'] == [base]
    assert result['conflicts'] and result['unapplied'] and result['diff']
    p['version'] = 2; p['formulas'][1]['components'][0]['source_dose'] = '1'
    decision.import_package(conn,p)
    result = decision.preview_modifications(conn,'p','f1',['m'],[fact('x')])
    assert result['components'] == [base,added]
    assert result['applied'] and not result['conflicts']


def test_graph_edges_do_not_exclude_parent_and_question_dedup(store):
    conn,p = store
    child = deepcopy(p['nodes'][0]); child['id'] = 'child'; child['conditions'][0]['id'] = 'c2'
    p['nodes'].append(child)
    p['edges'] = [dict(id='edge',**{'from':'n','to':'child'},relation='refines',claim_ids=['support'],note='synthetic')]
    decision.import_package(conn,p)
    result = decision.evaluate(conn,[])
    assert len(result['questions']) == 2
    assert set(result['questions'][0]['node_ids']) == {'n','child'}
    assert result['edges'][0]['to_status'] == 'pending'
    for field in ('nodes','formulas','claims','anchors','edges'):
        assert all(x['package_id'] == 'p' and x['package_version'] == 1 for x in result[field])


def test_trigger_unknown_and_conflict_never_apply(store):
    conn,p = store
    added = deepcopy(p['formulas'][0]['components'][0]); added['name'] = 'B'
    p['modifications'] = [dict(id='m',base_version_id='f1',trigger={'fact':'x'},claim_ids=['mod'],actions=[dict(operation='add',component=added,claim_ids=['mod'])],limitations=[])]
    decision.import_package(conn,p)
    result = decision.preview_modifications(conn,'p','f1',['m'],[])
    assert not result['applied'] and result['missing'] == ['x'] and result['components'] == p['formulas'][0]['components']
    result = decision.preview_modifications(conn,'p','f1',['m'],[fact('x'),fact('x','absent')])
    assert not result['applied'] and result['conflicts']


def test_rejects_invalid_anchor_and_missing_provenance(store):
    conn,p = store
    p['anchors'][0]['start'] = -1
    with pytest.raises(ValueError): decision.import_package(conn,p)
    p['anchors'][0]['start'] = 0
    p['claims'][0]['anchor_ids'] = 'a'
    with pytest.raises(ValueError): decision.import_package(conn,p)


def test_preview_rejects_uncertain_base_processing(store):
    conn,p = store
    p['formulas'][0]['components'][0]['processing'] = None
    p['formulas'][0]['components'][0]['provenance']['processing'] = []
    added = deepcopy(p['formulas'][0]['components'][0]); added['name'] = 'B'
    p['modifications'] = [dict(id='m',base_version_id='f1',trigger={'fact':'x'},claim_ids=['mod'],actions=[dict(operation='add',component=added,claim_ids=['mod'])],limitations=[])]
    decision.import_package(conn,p)
    result = decision.preview_modifications(conn,'p','f1',['m'],[fact('x')])
    assert result['conflicts'] and not result['applied']


def test_support_unknown_pending_and_refinement_retains_parent(store):
    conn,p = store
    n = p['nodes'][0]; n['conditions'] = [dict(id='s',role='support',expr={'fact':'x'},claim_ids=['support'])]
    child = deepcopy(n); child['id'] = 'child'; child['conditions'][0]['id'] = 'child-s'
    p['nodes'].append(child); p['edges'] = [dict(id='e',**{'from':'n','to':'child'},relation='refines',claim_ids=['support'],note='synthetic')]
    decision.import_package(conn,p)
    out = decision.evaluate(conn,[])
    assert out['nodes'][0]['status'] == 'pending'
    assert out['questions'] and out['edges'][0]['retained_parent'] is True
    assert decision.evaluate(conn,[fact('x','absent')])['nodes'][0]['status'] == 'pending'


@pytest.mark.parametrize('operation', ['remove','replace','adjust'])
def test_preview_executes_absolute_source_actions(store, operation):
    conn,p = store
    component = deepcopy(p['formulas'][0]['components'][0])
    if operation == 'replace': component['name'] = 'B'
    if operation == 'adjust': component['source_dose'] = '2'
    action = dict(operation=operation,target_name='A',target_processing='raw',claim_ids=['mod'])
    if operation != 'remove': action['component'] = component
    p['modifications'] = [dict(id='m',base_version_id='f1',trigger={'fact':'x'},claim_ids=['mod'],actions=[action],limitations=[])]
    decision.import_package(conn,p)
    result = decision.preview_modifications(conn,'p','f1',['m'],[fact('x')])
    assert result['components'] == ([] if operation == 'remove' else [component])
    assert result['applied'] and not result['conflicts']


def test_sql_package_rows_are_immutable(store):
    conn,p = store
    decision.import_package(conn,p)
    with pytest.raises(sqlite3.IntegrityError): conn.execute("UPDATE decision_packages SET payload='{}'")
    with pytest.raises(sqlite3.IntegrityError): conn.execute('DELETE FROM decision_packages')


def test_cases_require_source_context_and_support_alone_is_only_clue(store):
    conn,p = store
    n = p['nodes'][0]
    n['conditions'] = [dict(id='s', role='support', expr={'fact':'x'}, claim_ids=['support'])]
    n['cases'] = [dict(id='context',label='synthetic case',expr={'all':[{'fact':'x'},{'fact':'setting'}]},claim_ids=['support'],scope='synthetic')]
    n['questions'].append(dict(key='setting',question='setting?',reason='synthetic',claim_ids=['support']))
    decision.import_package(conn,p)
    result = decision.evaluate(conn,[fact('x')])
    assert result['nodes'][0]['status'] == 'pending'
    assert {q['key'] for q in result['questions']} == {'setting'}
    assert result['nodes'][0]['case_traces'][0]['claim_ids'] == ['support']
    assert decision.evaluate(conn,[fact('x'),fact('setting')])['nodes'][0]['status'] == 'compatible'
    assert decision.evaluate(conn,[fact('x'),fact('setting','absent')])['nodes'][0]['status'] == 'clue'


def test_independent_cases_are_alternatives_and_conflicts_block(store):
    conn,p = store
    p['nodes'][0]['cases'] = [dict(id='one',label='one',expr={'fact':'x'},claim_ids=['support'],scope='synthetic'),dict(id='two',label='two',expr={'fact':'z'},claim_ids=['support'],scope='synthetic')]
    decision.import_package(conn,p)
    assert decision.evaluate(conn,[fact('x')])['nodes'][0]['status'] == 'compatible'
    assert decision.evaluate(conn,[fact('x'),fact('z'),fact('z','absent')])['nodes'][0]['status'] == 'conflict'


def test_case_claim_type_and_parent_fallback(store):
    conn,p = store
    parent = p['nodes'][0]
    parent['cases'] = [dict(id='case1',label='one',expr={'fact':'x'},claim_ids=['support'],scope='synthetic')]
    child = deepcopy(parent); child['id'] = 'child'; child['cases'][0]['expr'] = {'fact':'y'}
    p['nodes'].append(child)
    p['edges'] = [dict(id='e',**{'from':'n','to':'child'},relation='refines',claim_ids=['support'],note='synthetic')]
    bad = deepcopy(p); bad['nodes'][0]['cases'][0]['claim_ids'] = ['dose']
    with pytest.raises(ValueError): decision.import_package(conn,bad)
    decision.import_package(conn,p)
    out = decision.evaluate(conn,[fact('x'),fact('y','absent')])
    assert out['nodes'][0]['status'] == 'compatible'
    assert out['nodes'][1]['status'] == 'clue'
    assert out['edges'][0]['retained_parent']


def test_replace_cannot_overwrite_package_and_tampered_payload_is_rejected(store):
    conn,p = store
    decision.import_package(conn,p)
    row = conn.execute('SELECT id,version,digest,payload FROM decision_packages').fetchone()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('INSERT OR REPLACE INTO decision_packages VALUES (?,?,?,?)', (row[0],row[1],row[2],row[3].replace('synthetic source','tampered source')))
    conn.execute('DROP TRIGGER decision_packages_no_update')
    conn.execute('UPDATE decision_packages SET payload=? WHERE id=?', (row[3].replace('synthetic source','tampered source'),row[0]))
    with pytest.raises(ValueError): decision.evaluate(conn,[])


@pytest.mark.parametrize('additional', [{}, {'value': 39}, {'value': 39, 'unit':'F'}])
def test_numeric_fact_missing_value_or_unit_prompts_again(store, additional):
    conn,p = store
    n = p['nodes'][0]
    n['conditions'] = [dict(id='temp',role='required',expr={'fact':'temperature','op':'gte','value':38,'unit':'C'},claim_ids=['necessary'])]
    n['questions'] = [dict(key='temperature',question='temperature?',reason='synthetic',claim_ids=['necessary'])]
    decision.import_package(conn,p)
    out = decision.evaluate(conn,[fact('temperature',**additional)])
    assert out['nodes'][0]['status'] == 'pending'
    assert [q['key'] for q in out['questions']] == ['temperature']
    assert not decision.evaluate(conn,[fact('temperature',value=39,unit='C')])['questions']


def test_pinned_preview_retains_exact_version_and_digest_tracks_registry(store):
    conn,p = store
    added = deepcopy(p['formulas'][0]['components'][0]); added['name'] = 'B'
    p['modifications'] = [dict(id='m',base_version_id='f1',trigger={'fact':'x'},claim_ids=['mod'],actions=[dict(operation='add',component=added,claim_ids=['mod'])],limitations=[])]
    decision.import_package(conn,p)
    snapshot = decision.evaluate(conn,[fact('x')])
    old_digest = snapshot['registry_digest']
    assert old_digest == decision.digest(conn)
    p2 = deepcopy(p); p2['version'] = 2; p2['modifications'][0]['actions'][0]['component']['name'] = 'C'
    decision.import_package(conn,p2)
    pinned = decision.preview_modifications(conn,'p','f1',['m'],[fact('x')],package_version=1)
    assert pinned['package_version'] == 1 and pinned['components'][1]['name'] == 'B'
    assert decision.preview_modifications(conn,'p','f1',['m'],[fact('x')])['components'][1]['name'] == 'C'
    with pytest.raises(ValueError): decision.preview_modifications(conn,'p','f1',['m'],[fact('x')],package_version=3)
    assert decision.digest(conn) != old_digest


def test_evaluate_uses_one_registry_read(store, monkeypatch):
    conn,p = store
    decision.import_package(conn,p)
    original = decision.load_packages
    calls = []
    def load_once(conn):
        result = original(conn)
        calls.append(1)
        if len(calls) == 1:
            p2 = deepcopy(p); p2['version'] = 2
            decision.import_package(conn,p2)
        return result
    monkeypatch.setattr(decision,'load_packages',load_once)
    result = decision.evaluate(conn,[])
    assert len(calls) == 1
    assert result['packages'][0]['version'] == 1 and result['coverage']['installed_versions'] == 1
    expected = decision._hash(decision._encode([('p',1,result['packages'][0]['digest'])]))
    assert result['registry_digest'] == expected


@pytest.mark.parametrize('layer', ['ai_inference','open_source_summary','ni_case'])
def test_global_necessary_cannot_be_derived_only_from_non_primary_layer(store, layer):
    conn,p = store
    extra = deepcopy(p['anchors'][0]); extra['id'] = 'nonprimary'; extra['layer'] = layer
    p['anchors'].append(extra)
    next(c for c in p['claims'] if c['id'] == 'necessary')['anchor_ids'] = ['nonprimary']
    with pytest.raises(ValueError): decision.import_package(conn,p)


@pytest.mark.parametrize('field,kind', [('identity','identity'),('processing','processing'),('dose','dose'),('mod','modification'),('support','support')])
def test_unbacked_source_cannot_authorize_formula_case_or_actions(store, field, kind):
    conn,p = store
    extra = deepcopy(p['anchors'][0]); extra['id'] = 'ai'; extra['layer'] = 'ai_inference'
    p['anchors'].append(extra)
    next(c for c in p['claims'] if c['id'] == field)['anchor_ids'] = ['ai']
    if field == 'mod':
        p['modifications'] = [dict(id='m',base_version_id='f1',trigger={'fact':'x'},claim_ids=['mod'],actions=[dict(operation='remove',target_name='A',target_processing='raw',claim_ids=['mod'])],limitations=[])]
    if field == 'support':
        p['nodes'][0]['cases'] = [dict(id='case',label='case',scope='synthetic',expr={'fact':'x'},claim_ids=['support'])]
    with pytest.raises(ValueError): decision.import_package(conn,p)


def test_ai_claim_may_remain_nonexecuted_and_case_source_may_back_case(store):
    conn,p = store
    ai = deepcopy(p['anchors'][0]); ai['id'] = 'ai'; ai['layer'] = 'ai_inference'
    case = deepcopy(p['anchors'][0]); case['id'] = 'case'; case['layer'] = 'ni_case'
    p['anchors'].extend([ai,case])
    p['claims'].append(dict(id='ai-note',kind='interpretation',text='synthetic note',anchor_ids=['ai'],inference='interpretation',scope='synthetic',limitations=[]))
    p['claims'].append(dict(id='case-note',kind='support',text='synthetic case',anchor_ids=['case'],inference='visual_transcription',scope='synthetic',limitations=[]))
    p['nodes'][0]['cases'] = [dict(id='case',label='case',scope='synthetic',expr={'fact':'x'},claim_ids=['case-note'])]
    decision.import_package(conn,p)
    assert decision.evaluate(conn,[fact('x')])['nodes'][0]['status'] == 'compatible'


def test_previous_unqualified_package_is_not_executed(store):
    conn,p = store
    extra = deepcopy(p['anchors'][0]); extra['id'] = 'ai'; extra['layer'] = 'ai_inference'
    p['anchors'].append(extra)
    next(c for c in p['claims'] if c['id'] == 'necessary')['anchor_ids'] = ['ai']
    encoded = decision._encode(p)
    conn.execute('INSERT INTO decision_packages VALUES (?,?,?,?)', ('p',1,decision._hash(encoded),encoded))
    with pytest.raises(ValueError, match='source layer'): decision.evaluate(conn,[])
