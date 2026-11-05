"""Pure, deterministic engineering rules; no clinical knowledge or I/O."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
import re


_STATES = {'present', 'absent', 'unknown', 'conflict'}
_OPS = {'gt', 'gte', 'lt', 'lte', 'eq'}
_DRUG_FIELDS = {'name', 'processing', 'amount', 'unit', 'basis', 'evidence_ids'}
_SAFETY_AREAS = ['drug_identity_processing', 'allergies', 'special_populations',
                 'medications_and_duplicates', 'interactions', 'dose_units', 'preparation_limits']


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 10000:
        raise ValueError(f'{name} must be a nonempty string')
    return value


def _list(value, name):
    if not isinstance(value, list) or len(value) > 10000:
        raise ValueError(f'{name} must be a bounded list')
    return value


def _strings(value, name):
    for item in _list(value, name):
        _text(item, name)


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f'{name} must be numeric')
    try:
        if len(str(value)) > 250:
            raise ValueError(f'{name} is too large')
        number = Decimal(str(value))
        if not number.is_finite() or (number and abs(number.adjusted()) > 100):
            raise ValueError(f'{name} must be finite and bounded')
        return number
    except InvalidOperation as exc:
        raise ValueError(f'{name} must be numeric') from exc


def _identity(drug):
    return drug['name'], drug['processing']


def _target(value):
    if not isinstance(value, dict) or set(value) != {'name', 'processing'}:
        raise ValueError('target needs name and processing')
    _text(value['name'], 'name')
    _text(value['processing'], 'processing')


def _drug(drug):
    if not isinstance(drug, dict) or set(drug) != _DRUG_FIELDS:
        raise ValueError('invalid drug fields')
    for key in ('name', 'processing', 'unit'):
        _text(drug[key], key)
    if drug['basis'] not in ('per_dose', 'per_day', 'per_course'):
        raise ValueError('invalid dose basis')
    amount = drug['amount']
    if not isinstance(amount, str) or not re.fullmatch(r'[0-9]{1,60}(?:\.[0-9]{1,60})?', amount):
        raise ValueError('amount must be a bounded decimal string without exponent')
    if _number(amount, 'amount') <= 0:
        raise ValueError('amount must be positive')
    _strings(drug['evidence_ids'], 'evidence_ids')


def _formula(formula):
    for item in _list(formula, 'formula'):
        _drug(item)


def _expr(expr, depth=0, budget=None):
    budget = [0] if budget is None else budget
    budget[0] += 1
    if depth > 20 or budget[0] > 1000 or not isinstance(expr, dict):
        raise ValueError('expression exceeds limits or is not an object')
    if 'fact' in expr:
        _text(expr['fact'], 'fact')
        if 'op' in expr:
            if set(expr) != {'fact', 'op', 'value', 'unit'} or not isinstance(expr['op'], str) or expr['op'] not in _OPS:
                raise ValueError('invalid comparison')
            _number(expr['value'], 'comparison value')
            _text(expr['unit'], 'comparison unit')
        elif set(expr) - {'fact', 'state'} or expr.get('state', 'present') not in ('present', 'absent'):
            raise ValueError('invalid fact expression')
        return
    if len(expr) != 1:
        raise ValueError('expression must have one operator')
    operation = next(iter(expr))
    if operation == 'not':
        _expr(expr[operation], depth + 1, budget)
    elif operation in ('all', 'any'):
        children = _list(expr[operation], operation)
        if not children:
            raise ValueError('empty expression group')
        for child in children:
            _expr(child, depth + 1, budget)
    else:
        raise ValueError('unknown expression operator')


def validate_rule(rule: dict) -> dict:
    """Validate the executable grammar, returning an independent snapshot."""
    if not isinstance(rule, dict):
        raise ValueError('rule must be an object')
    fields = {'id', 'version', 'title', 'kind', 'status', 'synthetic', 'scope', 'required',
              'support', 'excluded', 'evidence_ids', 'formula_id', 'formula', 'actions',
              'base_formula_id', 'description', 'reviews', 'created_at',
              'published_at', 'published_by', 'withdrawn_at', 'withdrawal_note'}
    if set(rule) - fields:
        raise ValueError('unknown rule fields')
    for key in ('published_at', 'published_by', 'withdrawn_at', 'withdrawal_note'):
        if key in rule and not isinstance(rule[key], str):
            raise ValueError(f'{key} must be a string')
    for key in ('id', 'title', 'description'):
        _text(rule.get(key), key)
    if type(rule.get('version')) is not int or rule['version'] <= 0:
        raise ValueError('version must be a positive integer')
    if rule.get('kind') not in ('pattern', 'red_flag', 'safety', 'modification'):
        raise ValueError('invalid rule kind')
    if rule.get('status') not in ('draft', 'published', 'withdrawn'):
        raise ValueError('invalid rule status')
    if type(rule.get('synthetic')) is not bool:
        raise ValueError('synthetic must be boolean')
    scope = rule.get('scope')
    if not isinstance(scope, dict) or set(scope) - {'min_age', 'max_age', 'description'}:
        raise ValueError('invalid rule scope')
    _text(scope.get('description'), 'scope description')
    for key in ('min_age', 'max_age'):
        if key in scope and _number(scope[key], key) < 0:
            raise ValueError('negative age boundary')
    if 'min_age' in scope and 'max_age' in scope and _number(scope['min_age'], 'min_age') > _number(scope['max_age'], 'max_age'):
        raise ValueError('reversed age boundaries')
    _expr(rule.get('required'))
    for expression in _list(rule.get('support'), 'support'):
        _expr(expression)
    if rule.get('excluded') is not None:
        _expr(rule['excluded'])
    _strings(rule.get('evidence_ids'), 'evidence_ids')
    if rule['status'] == 'published' and not rule['synthetic'] and not rule['evidence_ids']:
        raise ValueError('non-synthetic rule requires evidence')
    _formula(rule.get('formula'))
    for key in ('formula_id', 'base_formula_id'):
        if key in rule:
            _text(rule[key], key)
    for action in _list(rule.get('actions'), 'actions'):
        if not isinstance(action, dict) or set(action) - {'operation', 'target', 'drug'}:
            raise ValueError('invalid action')
        operation = action.get('operation')
        if operation not in ('add', 'remove', 'replace', 'adjust'):
            raise ValueError('unknown action operation')
        expected = {'operation', 'drug'} if operation == 'add' else {'operation', 'target'}
        if operation in ('replace', 'adjust'):
            expected.add('drug')
        if set(action) != expected:
            raise ValueError('invalid fields for action operation')
        if 'target' in action:
            _target(action['target'])
        if 'drug' in action:
            _drug(action['drug'])
        if operation == 'adjust' and _identity(action['target']) != _identity(action['drug']):
            raise ValueError('adjust cannot change drug identity')
    if rule['kind'] == 'modification' and not rule.get('base_formula_id'):
        raise ValueError('modification requires a version-bound base_formula_id')
    return deepcopy(rule)


def _context(context):
    context = {} if context is None else context
    if not isinstance(context, dict) or set(context) - {'age_years', 'pregnancy', 'allergies', 'medications', 'simulation'}:
        raise ValueError('invalid context fields')
    if 'age_years' in context and _number(context['age_years'], 'age_years') < 0:
        raise ValueError('age_years cannot be negative')
    if 'pregnancy' in context and context['pregnancy'] not in ('yes', 'no', 'unknown'):
        raise ValueError('invalid pregnancy state')
    for key in ('allergies', 'medications'):
        if key in context:
            _strings(context[key], key)
    if 'simulation' in context and type(context['simulation']) is not bool:
        raise ValueError('simulation must be boolean')
    return context


def _facts(facts):
    indexed, ignored = {}, []
    for item in _list(facts, 'facts'):
        fields = {'key', 'state', 'raw', 'source', 'observed_at', 'scope', 'verified', 'value', 'unit', 'subject'}
        if not isinstance(item, dict) or set(item) - fields:
            raise ValueError('invalid fact fields')
        _text(item.get('key'), 'fact key')
        if not isinstance(item.get('state'), str) or item['state'] not in _STATES or type(item.get('verified')) is not bool:
            raise ValueError('invalid fact state or verified flag')
        if item.get('scope', 'current') not in ('current', 'history'):
            raise ValueError('invalid fact scope')
        if 'source' in item and item['source'] not in ('patient', 'clinician', 'test'):
            raise ValueError('invalid fact source')
        if item.get('subject', 'patient') not in ('patient', 'family', 'other', 'unknown'):
            raise ValueError('invalid fact subject')
        if 'observed_at' in item:
            try:
                _text(item['observed_at'], 'observed_at')
                datetime.fromisoformat(item['observed_at'].replace('Z', '+00:00'))
            except (ValueError, TypeError) as exc:
                raise ValueError('observed_at must be ISO8601') from exc
        if 'unit' in item:
            _text(item['unit'], 'unit')
        value = item.get('value')
        if value is not None:
            if isinstance(value, (int, float)):
                _number(value, 'fact value')
            elif isinstance(value, str):
                if value.strip().lower().lstrip('+-') in {'nan', 'snan', 'inf', 'infinity'}:
                    raise ValueError('non-finite fact value')
                if len(value) > 10000:
                    raise ValueError('fact value too long')
            else:
                raise ValueError('invalid fact value')
        if not item['verified'] or item.get('scope', 'current') != 'current' or item.get('subject', 'patient') != 'patient':
            ignored.append(deepcopy(item))
        else:
            indexed.setdefault(item['key'], []).append(item)
    return indexed, ignored


def _evaluate(expr, indexed):
    if 'fact' in expr:
        key = expr['fact']
        sources = indexed.get(key, [])
        comparable = sources
        if key.startswith('dose:') and 'op' in expr:
            comparable = [item for item in sources if item.get('unit') == expr['unit']]
        known = [item for item in comparable if item['state'] != 'unknown']
        signatures = {(item['state'], str(item.get('value')), item.get('unit')) for item in known}
        conflict = any(item['state'] == 'conflict' for item in known) or len(signatures) > 1
        value = None
        if known and not conflict:
            item = known[0]
            if 'op' not in expr:
                value = item['state'] == expr.get('state', 'present')
            elif item['state'] == 'present' and item.get('unit') == expr['unit'] and item.get('value') is not None:
                try:
                    left, right = _number(item['value'], 'fact value'), _number(expr['value'], 'comparison value')
                    value = {'gt': left > right, 'gte': left >= right, 'lt': left < right,
                             'lte': left <= right, 'eq': left == right}[expr['op']]
                except ValueError:
                    pass
        return {'expression': deepcopy(expr), 'value': value, 'missing': [key] if value is None and not conflict else [],
                'conflicts': [key] if conflict else [], 'facts': deepcopy(sources)}
    operation = next(iter(expr))
    children = [_evaluate(expr['not'], indexed)] if operation == 'not' else [_evaluate(child, indexed) for child in expr[operation]]
    values = [child['value'] for child in children]
    if operation == 'not':
        value = None if values[0] is None else not values[0]
    elif operation == 'all':
        value = False if False in values else None if None in values else True
    else:
        value = True if True in values else None if None in values else False
    return {'expression': deepcopy(expr), 'value': value, 'children': children,
            'missing': sorted({key for child in children for key in child['missing']}),
            'conflicts': sorted({key for child in children for key in child['conflicts']})}


def _candidate(rule, indexed, context):
    required = _evaluate(rule['required'], indexed)
    excluded = _evaluate(rule['excluded'], indexed) if rule.get('excluded') is not None else {'value': False, 'missing': [], 'conflicts': []}
    support = [_evaluate(expr, indexed) for expr in rule['support']]
    traces = [required, excluded, *support]
    missing = sorted({key for trace in traces for key in trace['missing']})
    conflicts = sorted({key for trace in traces for key in trace['conflicts']})
    scope = rule['scope']
    age_missing = any(key in scope for key in ('min_age', 'max_age')) and 'age_years' not in context
    out_of_scope = False
    if not age_missing and 'age_years' in context:
        age = _number(context['age_years'], 'age_years')
        out_of_scope = ('min_age' in scope and age < _number(scope['min_age'], 'min_age')) or ('max_age' in scope and age > _number(scope['max_age'], 'max_age'))
    if out_of_scope:
        status = 'not_applicable'
    elif conflicts:
        status = 'conflict'
    elif age_missing:
        status = 'pending'
        missing = sorted(set(missing) | {'age_years'})
    elif required['value'] is False or excluded['value'] is True:
        status = 'not_matched'
    elif required['value'] is None or excluded['value'] is None:
        status = 'pending'
    else:
        status = 'matched'
    return {'rule_id': rule['id'], 'title': rule['title'], 'status': status,
            'required': required, 'excluded': excluded, 'support': support,
            'missing': missing, 'conflicts': conflicts, 'evidence_ids': deepcopy(rule['evidence_ids']),
            'formula_id': rule.get('formula_id'),
            'formula': deepcopy(rule['formula']) if status == 'matched' and rule['kind'] == 'pattern' else []}


def analyze(facts: list[dict], rules: list[dict], context: dict | None = None) -> dict:
    context = _context(context)
    indexed, ignored = _facts(facts)
    published, skipped = [], []
    for rule in _list(rules, 'rules'):
        if not isinstance(rule, dict):
            raise ValueError('rule must be an object')
        if rule.get('status') in ('draft', 'withdrawn'):
            skipped.append({'rule_id': rule.get('id'), 'status': rule['status']})
            continue
        published.append(validate_rule(rule))
    candidates = [_candidate(rule, indexed, context) for rule in published]
    urgent = any(rule['kind'] == 'red_flag' and item['status'] == 'matched' for rule, item in zip(published, candidates))
    if urgent:
        for item in candidates:
            item['formula'] = []
    formula = [drug for item in candidates for drug in item['formula']]
    safety = check_formula(formula, context, [rule for rule in published if rule['kind'] == 'safety'])
    questions = sorted({key for item in candidates for key in item['missing'] + item['conflicts']})
    return {'candidates': candidates, 'urgent': urgent, 'questions': questions, 'safety': safety,
            'trace': {'ignored_facts': ignored, 'ignored_rules': skipped,
                      'rule_versions': [{'id': rule['id'], 'version': rule['version']} for rule in published]}}


def apply_modifications(formula: list[dict], modifications: list[dict], facts: list[dict], base_formula_id: str = '', context: dict | None = None) -> dict:
    _formula(formula)
    context = _context(context)
    indexed, _ = _facts(facts)
    result = {'formula': deepcopy(formula), 'applied': [], 'conflicts': [], 'pending': []}
    actions = []
    for raw in _list(modifications, 'modifications'):
        if isinstance(raw, dict) and raw.get('status') in ('draft', 'withdrawn'):
            continue
        rule = validate_rule(raw)
        if rule['kind'] != 'modification':
            raise ValueError('expected modification rule')
        if not base_formula_id or rule['base_formula_id'] != base_formula_id:
            result['conflicts'].append({'rule_id': rule['id'], 'reason': 'base_formula_version_mismatch'})
            continue
        candidate = _candidate(rule, indexed, context)
        if candidate['status'] in ('pending', 'conflict'):
            result['pending'].append(candidate)
        elif candidate['status'] == 'matched':
            actions.extend((rule['id'], action) for action in rule['actions'])
    touched = {}
    for rule_id, action in actions:
        identities = {_identity(action.get('target', action.get('drug')))}
        if action['operation'] == 'replace':
            identities.add(_identity(action['drug']))
        for identity in identities:
            previous = touched.setdefault(identity, [])
            if previous and (action['operation'] != 'add' or any(op != 'add' for op in previous)):
                result['conflicts'].append({'rule_id': rule_id, 'reason': 'mutually_exclusive_actions', 'target': list(identity)})
            previous.append(action['operation'])
    if result['conflicts'] or result['pending']:
        return result
    working = deepcopy(formula)
    applied = []
    for rule_id, action in actions:
        operation = action['operation']
        identity = _identity(action.get('target', action.get('drug')))
        matches = [i for i, item in enumerate(working) if _identity(item) == identity]
        if len(matches) > 1 or (operation != 'add' and not matches):
            result['conflicts'].append({'rule_id': rule_id, 'reason': 'ambiguous_or_missing_target', 'target': list(identity)})
            break
        if operation == 'remove':
            working.pop(matches[0])
        elif operation == 'add' and not matches:
            working.append(deepcopy(action['drug']))
        elif operation == 'add':
            old, new = working[matches[0]], action['drug']
            if old['unit'] != new['unit'] or old['basis'] != new['basis']:
                result['conflicts'].append({'rule_id': rule_id, 'reason': 'unit_or_basis_mismatch'})
                break
            with localcontext() as precision:
                precision.prec = 250
                old['amount'] = format(Decimal(old['amount']) + Decimal(new['amount']), 'f')
            try:
                _drug(old)
            except ValueError:
                result['conflicts'].append({'rule_id': rule_id, 'reason': 'combined_amount_exceeds_limits'})
                break
            old['evidence_ids'] = sorted(set(old['evidence_ids'] + new['evidence_ids']))
        else:
            new = action['drug']
            if operation == 'replace' and any(_identity(item) == _identity(new) for i, item in enumerate(working) if i != matches[0]):
                result['conflicts'].append({'rule_id': rule_id, 'reason': 'replacement_identity_collision'})
                break
            working[matches[0]] = deepcopy(new)
        applied.append({'rule_id': rule_id, 'action': deepcopy(action)})
    if not result['conflicts']:
        result['formula'], result['applied'] = working, applied
    return result


def _safety_facts(formula, context):
    facts = []
    def add(key, state='present', **extra):
        facts.append(dict(key=key, state=state, verified=True, **extra))
    if 'age_years' in context:
        add('age_years', value=context['age_years'], unit='years')
    if context.get('pregnancy') in ('yes', 'no'):
        add('pregnancy', 'present' if context['pregnancy'] == 'yes' else 'absent')
    for name in context.get('allergies', []):
        add('allergy:' + name)
    for name in context.get('medications', []):
        add('medication:' + name)
    doses = {}
    for item in formula:
        add('drug:' + item['name'])
        add('drug:' + item['name'] + ':' + item['processing'])
        key = (item['basis'], item['name'], item['processing'], item['unit'])
        with localcontext() as precision:
            precision.prec = 250
            doses[key] = doses.get(key, Decimal(0)) + Decimal(item['amount'])
    for (basis, name, processing, unit), amount in doses.items():
        add('dose:' + basis + ':' + name + ':' + processing, value=format(amount, 'f'), unit=unit)
    return _facts(facts)[0]


def check_formula(formula: list[dict], context: dict | None = None, safety_rules: list[dict] | None = None) -> dict:
    _formula(formula)
    context = _context(context)
    indexed = _safety_facts(formula, context)
    issues, coverage, uncovered = [], [], []
    for item in formula:
        if item['name'] in context.get('allergies', []):
            issues.append({'drug': item['name'], 'reason': 'recorded_allergy'})
    applicable = []
    for raw in _list([] if safety_rules is None else safety_rules, 'safety_rules'):
        if isinstance(raw, dict) and raw.get('status') in ('draft', 'withdrawn'):
            continue
        rule = validate_rule(raw)
        if rule['kind'] != 'safety':
            raise ValueError('expected safety rule')
        applicable.append(rule)
        candidate = _candidate(rule, indexed, context)
        coverage.append({'rule_id': rule['id'], 'version': rule['version'], 'scope': deepcopy(rule['scope']),
                         'evidence_ids': deepcopy(rule['evidence_ids']), 'result': candidate})
        if candidate['status'] == 'matched':
            issues.append({'rule_id': rule['id'], 'reason': rule['description'], 'evidence_ids': deepcopy(rule['evidence_ids'])})
        elif candidate['status'] in ('pending', 'conflict'):
            uncovered.append({'rule_id': rule['id'], 'reason': 'conditions_incomplete', 'missing': candidate['missing'], 'conflicts': candidate['conflicts']})
    if not applicable:
        uncovered.append({'reason': 'safety_library_missing'})
    # The contract has no certified coverage manifest; isolated rules cannot prove full safety coverage.
    uncovered.extend({'area': area, 'reason': 'coverage_not_established'} for area in _SAFETY_AREAS)
    return {'status': 'risk' if issues else 'incomplete', 'issues': issues, 'coverage': coverage, 'uncovered': uncovered}
