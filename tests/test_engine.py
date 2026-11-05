from copy import deepcopy

import pytest

from app import engine


def fact(key='sweat', state='present', **kwargs):
    return dict(key=key, state=state, verified=kwargs.pop('verified', True), **kwargs)


def drug(name='A', amount='0.1', processing='raw', unit='g', basis='per_dose'):
    return dict(name=name, processing=processing, amount=amount, unit=unit,
                basis=basis, evidence_ids=['e1'])


def rule(**kwargs):
    value = dict(id='r1', version=1, title='Synthetic example', kind='pattern',
                 status='published', synthetic=True, scope={'description': 'simulation'},
                 required={'fact': 'sweat'}, support=[], evidence_ids=[],
                 formula_id='base@1', formula=[drug()], actions=[], description='test')
    value.update(kwargs)
    return value


def candidate(facts, **kwargs):
    return engine.analyze(facts, [rule(**kwargs)])['candidates'][0]


def test_unrecorded_fact_is_unknown_even_under_not():
    result = candidate([], required={'not': {'fact': 'sweat'}})
    assert result['status'] == 'pending'
    assert result['required']['value'] is None
    assert 'sweat' in result['missing']
    assert result['formula'] == []


def test_support_does_not_complete_required_information():
    result = candidate([fact('thirst')], support=[{'fact': 'thirst'}])
    assert result['status'] == 'pending'
    assert result['support'][0]['value'] is True


def test_verified_current_facts_only():
    assert candidate([fact(verified=False)])['status'] == 'pending'
    assert candidate([fact(scope='history')])['status'] == 'pending'


def test_family_and_unknown_subject_facts_cannot_become_patient_findings():
    assert candidate([fact(subject='family')])['status'] == 'pending'
    assert candidate([fact(subject='unknown')])['status'] == 'pending'
    assert candidate([fact(subject='patient'), fact(state='absent', subject='family')])['status'] == 'matched'


def test_explicit_absent_and_exclusion_stop_match():
    assert candidate([fact(state='absent')])['status'] == 'not_matched'
    assert candidate([fact(), fact('danger')], excluded={'fact': 'danger'})['status'] == 'not_matched'


def test_conflicts_are_local_and_cannot_be_hidden_by_true_any():
    expr = {'any': [{'fact': 'sweat'}, {'fact': 'thirst'}]}
    result = candidate([fact(), fact(state='absent'), fact('thirst')], required=expr)
    assert result['status'] == 'conflict'
    assert result['conflicts'] == ['sweat']
    assert candidate([fact(), fact('other', 'conflict')])['status'] == 'matched'


def test_different_times_do_not_override_current_conflicts():
    facts = [fact(observed_at='2026-01-01T10:00:00Z'),
             fact(state='absent', observed_at='2026-01-02T10:00:00Z')]
    assert candidate(facts)['status'] == 'conflict'
    assert candidate(list(reversed(facts)))['status'] == 'conflict'


def test_draft_and_withdrawn_are_ignored_and_age_missing_is_pending():
    assert engine.analyze([], [rule(status='draft'), rule(status='withdrawn')])['candidates'] == []
    assert candidate([fact()], scope={'description': 'adult', 'min_age': 18})['status'] == 'pending'
    result = engine.analyze([fact()], [rule(scope={'description': 'adult', 'min_age': 18})], {'age_years': 17})
    assert result['candidates'][0]['status'] == 'not_applicable'


def test_red_flag_strips_all_formulas_and_exposes_urgency():
    result = engine.analyze([fact()], [rule(), rule(id='danger', kind='red_flag')])
    assert result['urgent'] is True
    assert all(item['formula'] == [] for item in result['candidates'])
    assert result['safety']['status'] == 'incomplete'


@pytest.mark.parametrize('required', [
    {'eval': '__import__("os").system("echo fail")'},
    {'fact': 'sweat', 'op': 'execute', 'value': 1, 'unit': 'g'},
    {'all': []}, {'any': []}, {'fact': 'sweat', 'state': 'maybe'},
    {'fact': 'sweat', 'op': 'gt', 'value': 'NaN', 'unit': 'g'},
    {'fact': 'sweat', 'op': 'gt', 'value': float('inf'), 'unit': 'g'},
    {'fact': 'sweat', 'script': 'return true'},
])
def test_reject_unsafe_expressions(required):
    with pytest.raises(ValueError):
        engine.validate_rule(rule(required=required))


def test_reject_deep_expression_and_unproven_real_rule():
    expr = {'fact': 'sweat'}
    for _ in range(40):
        expr = {'not': expr}
    with pytest.raises(ValueError):
        engine.validate_rule(rule(required=expr))
    with pytest.raises(ValueError):
        engine.validate_rule(rule(synthetic=False))


def test_three_value_logic_and_exact_unit_comparisons():
    assert candidate([fact()], required={'all': [{'fact': 'sweat'}, {'fact': 'thirst'}]})['status'] == 'pending'
    assert candidate([fact(state='absent')], required={'all': [{'fact': 'sweat'}, {'fact': 'thirst'}]})['status'] == 'not_matched'
    numeric = {'fact': 'weight', 'op': 'gte', 'value': '0.3', 'unit': 'g'}
    assert candidate([fact('weight', value='0.3', unit='g')], required=numeric)['status'] == 'matched'
    assert candidate([fact('weight', value='0.3', unit='liang')], required=numeric)['status'] == 'pending'


def modification(**kwargs):
    return rule(kind='modification', base_formula_id='base@1', formula=[],
                actions=kwargs.pop('actions', [{'operation': 'add', 'drug': drug('B')}]), **kwargs)


def test_modifications_require_version_and_complete_conditions():
    original = [drug()]
    result = engine.apply_modifications(original, [modification()], [], 'base@1')
    assert result['formula'] == original and result['pending'] and not result['applied']
    result = engine.apply_modifications(original, [modification()], [fact()], 'base@2')
    assert result['formula'] == original and result['conflicts'] and not result['applied']


def test_mutually_exclusive_modifications_are_atomic():
    mods = [modification(actions=[{'operation': 'remove', 'target': {'name': 'A', 'processing': 'raw'}}]),
            modification(id='r2', actions=[{'operation': 'adjust', 'target': {'name': 'A', 'processing': 'raw'}, 'drug': drug(amount='2')}])]
    original = [drug()]
    result = engine.apply_modifications(original, mods, [fact()], 'base@1')
    assert result['formula'] == original and len(result['conflicts']) > 0 and not result['applied']


def test_add_uses_decimal_and_keeps_processing_separate_without_mutation():
    original = [drug()]
    mods = [modification(actions=[{'operation': 'add', 'drug': drug(amount='0.2')},
                                  {'operation': 'add', 'drug': drug(amount='1', processing='prepared')}])]
    before = deepcopy(mods)
    result = engine.apply_modifications(original, mods, [fact()], 'base@1')
    assert [d['amount'] for d in result['formula']] == ['0.3', '1']
    assert original == [drug()] and mods == before


@pytest.mark.parametrize('different', [drug(unit='liang'), drug(basis='per_day')])
def test_cannot_sum_different_units_or_dose_basis(different):
    result = engine.apply_modifications([drug()], [modification(actions=[{'operation': 'add', 'drug': different}])], [fact()], 'base@1')
    assert result['conflicts'] and result['formula'] == [drug()]


@pytest.mark.parametrize('operation', ['execute', 'ADD', '', '__import__'])
def test_reject_unknown_actions(operation):
    with pytest.raises(ValueError):
        engine.validate_rule(modification(actions=[{'operation': operation, 'drug': drug()}]))


@pytest.mark.parametrize('amount', ['NaN', 'Infinity', '-1', '0', '1e99999', 0.1])
def test_reject_invalid_drug_amount(amount):
    with pytest.raises(ValueError):
        engine.check_formula([drug(amount=amount)])


def test_safety_without_library_or_patient_data_is_incomplete():
    result = engine.check_formula([drug()], {'allergies': [], 'medications': []})
    assert result['status'] == 'incomplete'
    assert result['uncovered']


def test_safety_context_hit_and_unknown_are_distinct():
    safety = rule(kind='safety', required={'fact': 'pregnancy'})
    risk = engine.check_formula([drug()], {'pregnancy': 'yes'}, [safety])
    assert risk['status'] == 'risk' and risk['issues']
    incomplete = engine.check_formula([drug()], {}, [safety])
    assert incomplete['status'] == 'incomplete' and incomplete['uncovered']
    covered = engine.check_formula([drug()], {'pregnancy': 'no'}, [safety])
    assert covered['coverage'] and covered['status'] in ('covered_no_hit', 'incomplete')


def test_invalid_fact_and_context_rejected():
    for facts in ([dict(key='sweat', state='maybe', verified=True)], [fact(value='NaN')], [fact(observed_at='yesterday')]):
        with pytest.raises(ValueError):
            engine.analyze(facts, [rule()])
    with pytest.raises(ValueError):
        engine.analyze([], [], {'age_years': float('nan')})



def test_unpublished_real_rule_can_be_created_without_evidence():
    assert engine.validate_rule(rule(status='draft', synthetic=False))['status'] == 'draft'


def test_allergy_exact_name_is_a_risk_even_without_library():
    result = engine.check_formula([drug()], {'allergies': ['A']})
    assert result['status'] == 'risk'
    assert result['issues'][0]['reason'] == 'recorded_allergy'


def test_dose_safety_rules_include_dose_basis():
    safety = rule(kind='safety', required={'fact': 'dose:per_day:A:raw', 'op': 'gt', 'value': '0.05', 'unit': 'g'})
    per_dose = engine.check_formula([drug()], {}, [safety])
    assert per_dose['status'] == 'incomplete' and not per_dose['issues']
    per_day = engine.check_formula([drug(basis='per_day')], {}, [safety])
    assert per_day['status'] == 'risk'


def test_remove_replace_and_adjust_apply_with_trace():
    mods = [modification(actions=[{'operation': 'remove', 'target': {'name': 'A', 'processing': 'raw'}},
                                  {'operation': 'replace', 'target': {'name': 'B', 'processing': 'raw'}, 'drug': drug('C', '2')},
                                  {'operation': 'adjust', 'target': {'name': 'D', 'processing': 'raw'}, 'drug': drug('D', '3')}])]
    result = engine.apply_modifications([drug(), drug('B'), drug('D')], mods, [fact()], 'base@1')
    assert result['formula'] == [drug('C', '2'), drug('D', '3')]
    assert len(result['applied']) == 3 and not result['conflicts']


def test_failed_late_action_leaves_original_formula_unchanged():
    mods = [modification(actions=[{'operation': 'add', 'drug': drug('B')},
                                  {'operation': 'remove', 'target': {'name': 'missing', 'processing': 'raw'}}])]
    result = engine.apply_modifications([drug()], mods, [fact()], 'base@1')
    assert result['formula'] == [drug()] and result['conflicts'] and result['applied'] == []


def test_plus_nan_and_boolean_values_are_rejected():
    for value in ('+NaN', '-NaN', True):
        with pytest.raises(ValueError):
            engine.analyze([fact(value=value)], [rule()])


def test_analysis_does_not_modify_input_snapshots():
    facts, rules, context = [fact()], [rule()], {'pregnancy': 'unknown'}
    before = deepcopy((facts, rules, context))
    result = engine.analyze(facts, rules, context)
    result['candidates'][0]['formula'][0]['amount'] = '10'
    assert (facts, rules, context) == before


@pytest.mark.parametrize('bad', [[], {}, 1, None])
def test_malformed_state_and_operation_fail_with_value_error(bad):
    with pytest.raises(ValueError):
        engine.analyze([fact(state=bad)], [rule()])
    with pytest.raises(ValueError):
        engine.validate_rule(rule(required={'fact': 'sweat', 'op': bad, 'value': 1, 'unit': 'g'}))


def test_decimal_addition_does_not_return_an_unusable_out_of_range_drug():
    huge = drug(amount='9' * 60)
    mods = [modification(actions=[{'operation': 'add', 'drug': huge}])]
    result = engine.apply_modifications([huge], mods, [fact()], 'base@1')
    assert result['formula'] == [huge] and result['conflicts']



def test_explicit_null_exclusion_is_absent_for_analysis_and_validation():
    value = rule(excluded=None)
    assert engine.validate_rule(value)['excluded'] is None
    result = engine.analyze([fact()], [value])['candidates'][0]
    assert result['status'] == 'matched'
    assert result['excluded']['value'] is False


def test_known_audit_metadata_is_preserved_without_affecting_execution():
    audit = dict(published_at='2026-11-05T10:00:00Z', published_by='reviewer',
                 withdrawn_at='', withdrawal_note='')
    value = rule(**audit)
    validated = engine.validate_rule(value)
    assert {key: validated[key] for key in audit} == audit
    assert engine.analyze([fact()], [validated])['candidates'][0]['status'] == 'matched'


@pytest.mark.parametrize('field', ['published_at', 'published_by', 'withdrawn_at', 'withdrawal_note'])
def test_audit_metadata_rejects_non_strings(field):
    with pytest.raises(ValueError):
        engine.validate_rule(rule(**{field: {'execute': 'anything'}}))


def test_other_unknown_rule_metadata_still_rejected():
    with pytest.raises(ValueError):
        engine.validate_rule(rule(arbitrary_script='run'))


def test_modification_uses_the_same_age_context_as_analysis():
    adult = modification(scope={'description': 'adults', 'min_age': 18})
    context = {'age_years': 40}
    assert engine.analyze([fact()], [adult], context)['candidates'][0]['status'] == 'matched'
    result = engine.apply_modifications([drug()], [adult], [fact()], 'base@1', context)
    assert result['formula'] == [drug(), drug('B')]
    assert result['applied'] and not result['pending']
    missing_age = engine.apply_modifications([drug()], [adult], [fact()], 'base@1')
    assert missing_age['pending'] and not missing_age['applied']
    child = engine.apply_modifications([drug()], [adult], [fact()], 'base@1', {'age_years': 10})
    assert child['formula'] == [drug()] and not child['applied']


@pytest.mark.parametrize('amounts', [('6', '6'), ('6', '7'), ('0.1', '0.2')])
def test_safety_uses_exact_total_amount_for_identical_drug_dose_groups(amounts):
    threshold = '0.29' if amounts[0] == '0.1' else '10'
    safety = rule(kind='safety', required={'fact': 'dose:per_dose:A:raw', 'op': 'gt', 'value': threshold, 'unit': 'g'})
    formula = [drug(amount=amount) for amount in amounts]
    before = deepcopy(formula)
    result = engine.check_formula(formula, {}, [safety])
    assert result['status'] == 'risk' and result['issues']
    assert result['coverage'][0]['result']['required']['value'] is True
    assert formula == before


@pytest.mark.parametrize('different', [drug(amount='6', unit='liang'),
                                      drug(amount='6', processing='prepared'),
                                      drug(amount='6', basis='per_day')])
def test_safety_never_sums_distinct_units_processing_or_dose_bases(different):
    safety = rule(kind='safety', required={'fact': 'dose:per_dose:A:raw', 'op': 'gt', 'value': '10', 'unit': 'g'})
    result = engine.check_formula([drug(amount='6'), different], {}, [safety])
    assert result['status'] == 'incomplete' and result['issues'] == []


def test_different_unit_does_not_hide_known_covered_dose_risk():
    safety = rule(kind='safety', required={'fact': 'dose:per_dose:A:raw', 'op': 'gt', 'value': '10', 'unit': 'g'})
    formula = [drug(amount='6'), drug(amount='6'), drug(amount='1', unit='liang')]
    result = engine.check_formula(formula, {}, [safety])
    assert result['status'] == 'risk' and result['issues']


def test_safety_aggregation_preserves_valid_high_precision_amounts():
    safety = rule(kind='safety', required={'fact': 'dose:per_dose:A:raw', 'op': 'gt', 'value': '1', 'unit': 'g'})
    amount = '9' * 60 + '.' + '9' * 59
    result = engine.check_formula([drug(amount=amount), drug(amount=amount)], {}, [safety])
    assert result['status'] == 'risk'
