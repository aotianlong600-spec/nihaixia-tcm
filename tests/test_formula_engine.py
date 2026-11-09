from app import formula_engine as engine


def test_required_unknown_contradiction_and_subject(monkeypatch):
    library = {'formulas': [{'id':'f', 'name':'方', 'components':[], 'contraindications':[], 'source_refs':['source']}], 'patterns':[{'id':'p', 'formula_id':'f', 'name':'方', 'syndrome':'证', 'six_meridian':'太阳', 'required':[['发热'], ['汗出']], 'reference':[], 'source_refs':['rule']}], 'source_metadata':{}}
    monkeypatch.setattr(engine, 'load_library', lambda: library)
    def fact(key, state='present', **kw):
        return {'key':key, 'state':state, 'verified':True, **kw}
    a = engine.match_patterns([fact('发热')])[0]
    assert a['matched_features'] == ['发热'] and a['missing_features'] == ['汗出']
    b = engine.match_patterns([fact('发热'), fact('汗出', 'absent')])[0]
    assert '汗出' in b['contradictions'] and b['score'] < a['score']
    c = engine.match_patterns([fact('发热'), fact('汗出', scope='history'), fact('汗出', subject='family')])[0]
    assert c['missing_features'] == ['汗出']
    assert engine.match_patterns([fact('发热', verified=False)]) == []
    q = engine.match_patterns([], query='不发热')[0]
    assert not q['matched_features'] and q['missing_features'] == ['发热', '汗出'] and q['score'] == 0


def test_library_original_dose_and_limit():
    library = engine.load_library()
    assert len(library['formulas']) >= 300 and library['patterns']
    f = engine.get_formula('wutou_tang')
    assert next(c for c in f['components'] if c['name'] == '乌头')['source_dose'] == '五枚'
    assert all(c['source_unit'] is None for c in f['components'])
    assert len(engine.match_patterns([], query='桂枝', limit=2)) <= 2
    assert engine.match_patterns([], query='桂枝', limit=0) == []


def test_formula_index_searches_name_component_syndrome_and_meridian():
    assert engine.search_formulas('桂枝汤', limit=10)[0]['name'] == '桂枝汤'
    assert any('石膏' in [c['name'] for c in formula['components']]
               for formula in engine.search_formulas('石膏', limit=100))
    assert any('汗出' in formula['syndrome'] or any('汗出' in keyword for keyword in formula['keywords'])
               for formula in engine.search_formulas('汗出', limit=100))
    assert any('太阳' in formula['six_meridian']
               for formula in engine.search_formulas('太阳', limit=100))


def test_formula_modification_notes_keep_their_rule_source():
    notes = [note for formula in engine.load_library()['formulas']
             for note in formula.get('modification_notes', [])]
    assert notes
    assert all(note.get('source_ref', '').startswith(
        'https://github.com/jangviktor-web/nihaixia-app/') for note in notes)


def test_separate_source_patterns_are_not_merged(monkeypatch):
    library = {'formulas':[{'id':'f','name':'同方','components':[],'source_refs':['formula']}], 'patterns':[{'id':'p1','formula_id':'f','name':'同方','required':[['发热']],'source_refs':['one']}, {'id':'p2','formula_id':'f','name':'同方','required':[['发热']],'source_refs':['two']}], 'source_metadata':{}}
    monkeypatch.setattr(engine, 'load_library', lambda: library)
    result = engine.match_patterns([{'key':'发热','state':'present','verified':True}])
    assert [r['id'] for r in result] == ['p1','p2']
    assert result[0]['source_refs'] == ['one','formula'] and result[1]['source_refs'] == ['two','formula']
from copy import deepcopy


def mod(action, herb, replacement=None):
    return {'action':action, 'herb':herb, 'replacement':replacement, 'trigger_symptoms':[], 'source_note':'', 'evidence_ids':[]}


def test_preview_source_backed_add_and_remove_are_real_and_immutable():
    before = engine.get_formula('guizhi_tang')
    requested = [mod('remove', '芍药'), mod('add', '葛根')]
    original_request = deepcopy(requested)
    out = engine.preview_modifications('guizhi_tang', requested)
    assert '芍药' not in [c['name'] for c in out['components']]
    added = next(c for c in out['components'] if c['name'] == '葛根')
    assert added['source_dose'] is None and added['source_unit'] is None and added['source_ref']
    assert len(out['applied']) == 2 and not out['conflicts']
    assert requested == original_request and engine.get_formula('guizhi_tang') == before


def test_preview_conflicts_are_atomic_and_unsupported_names_are_not_normalized():
    before = engine.get_formula('guizhi_tang')['components']
    out = engine.preview_modifications('guizhi_tang', [mod('remove', '芍药'), mod('add', '芍药')])
    assert out['components'] == before and out['conflicts'] and not out['applied']
    out = engine.preview_modifications('guizhi_tang', [mod('add', '炒葛根'), mod('add', '黄芪')])
    assert out['components'] == before and len(out['unapplied']) == 2
    out = engine.preview_modifications('guizhi_tang', [mod('add', '葛根'), mod('add', '葛根')])
    assert out['components'] == before and out['conflicts'] and not out['applied']


def test_preview_rejects_unsupported_replacement_and_unknown_formula():
    out = engine.preview_modifications('guizhi_tang', [mod('replace', '芍药', '葛根')])
    assert out['unapplied'] and not out['applied']
    assert engine.preview_modifications('missing', [mod('add','葛根')])['unapplied']


def test_preview_source_backed_replace_and_adjust_without_inventing_dose(monkeypatch):
    result = engine.preview_modifications('zhenwu_tang', [mod('replace', '芍药', '干姜')])
    assert '芍药' not in [c['name'] for c in result['components']]
    assert next(c for c in result['components'] if c['name'] == '干姜')['source_dose'] is None
    assert result['applied'][0]['source_ref']
    formula = {'components':[{'name':'药','processing':None,'source_dose':'二两','source_unit':None,'source_ref':'base'}], 'modification_notes':[{'type':'adjust','herbName':'药','source_ref':'rule'}]}
    monkeypatch.setattr(engine, 'get_formula', lambda _: deepcopy(formula))
    adjusted = engine.preview_modifications('fixture', [mod('adjust','药')])
    assert adjusted['components'][0]['source_dose'] is None
    assert formula['components'][0]['source_dose'] == '二两'


def test_preview_does_not_merge_different_processing_variants(monkeypatch):
    formula = {'components':[{'name':'药','processing':'生','source_dose':'一两'}, {'name':'药','processing':'炙','source_dose':'二两'}], 'modification_notes':[{'type':'remove','herbName':'药','source_ref':'rule'}]}
    monkeypatch.setattr(engine, 'get_formula', lambda _: deepcopy(formula))
    result = engine.preview_modifications('fixture', [mod('remove','药')])
    assert result['conflicts'] and result['components'] == formula['components']
