"""Source-bound deterministic decision packages; no clinical approval workflow."""
import hashlib
import json
from copy import deepcopy
from app import engine, library

LAYERS = {'classic_clause','ni_commentary','ni_case','compiler_annotation','reference_author','open_source_summary','ai_inference'}
KINDS = {'support','necessary','exclusion','course','differential','treatment','identity','processing','dose','preparation','modification','interpretation'}


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def initialize(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS decision_packages (id TEXT NOT NULL, version INTEGER NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (id,version))')
    conn.execute("CREATE TRIGGER IF NOT EXISTS decision_packages_no_replace BEFORE INSERT ON decision_packages WHEN EXISTS (SELECT 1 FROM decision_packages WHERE id=NEW.id AND version=NEW.version) BEGIN SELECT RAISE(ABORT, 'immutable decision package'); END")
    conn.execute("CREATE TRIGGER IF NOT EXISTS decision_packages_no_update BEFORE UPDATE ON decision_packages BEGIN SELECT RAISE(ABORT, 'immutable decision package'); END")
    conn.execute("CREATE TRIGGER IF NOT EXISTS decision_packages_no_delete BEFORE DELETE ON decision_packages BEGIN SELECT RAISE(ABORT, 'immutable decision package'); END")


def _unique(items, key):
    engine._list(items, key)
    result = {}
    for item in items:
        if not isinstance(item, dict): raise ValueError('invalid ' + key)
        name = engine._text(item.get(key), key)
        if name in result: raise ValueError('duplicate ' + key)
        result[name] = item
    return result


def _source_issues(conn, package):
    issues = []
    for a in package['anchors']:
        try:
            unit = library.get_unit(conn, None, a['source_id'], a['unit_no'])
            raw = unit and unit.get('raw_text')
            if not isinstance(raw, str) or _hash(raw) != a['unit_sha256'] or raw[a['start']:a['end']] != a['quote'] or a['end'] > len(raw):
                issues.append({'anchor_id': a['id'], 'reason': '原始单元或锚点不匹配'})
        except (ValueError, KeyError, TypeError):
            issues.append({'anchor_id': a.get('id'), 'reason': '原始单元不可读取'})
    return issues


def _validate(conn, p, check_source=True):
    if not isinstance(p, dict) or p.get('format_version') != 1 or type(p.get('version')) is not int or p['version'] < 1: raise ValueError('invalid package version')
    engine._text(p.get('id'), 'id'); engine._text(p.get('title'), 'title')
    anchors = _unique(p.get('anchors'), 'id'); claims = _unique(p.get('claims'), 'id')
    formulas = _unique(p.get('formulas'), 'version_id'); nodes = _unique(p.get('nodes'), 'id')
    _unique(p.get('edges'), 'id'); _unique(p.get('modifications'), 'id')
    for a in anchors.values():
        for k in ('source_id','quote','unit_sha256','attribution','version_label'): engine._text(a.get(k), k)
        if a.get('layer') not in LAYERS or type(a.get('unit_no')) is not int or a['unit_no'] < 1 or type(a.get('start')) is not int or type(a.get('end')) is not int or a['start'] < 0 or a['end'] <= a['start']: raise ValueError('invalid anchor')
    if check_source and _source_issues(conn,p): raise ValueError('source anchor mismatch')
    for c in claims.values():
        engine._text(c.get('text'), 'claim text'); engine._text(c.get('scope'), 'scope')
        if c.get('kind') not in KINDS or c.get('inference') not in ('literal','interpretation','visual_transcription'): raise ValueError('invalid claim')
        engine._strings(c.get('limitations'), 'limitations')
        engine._strings(c.get('anchor_ids'), 'anchor_ids')
        if not c.get('anchor_ids') or any(x not in anchors for x in c['anchor_ids']): raise ValueError('unanchored claim')
    def refs(ids, kinds=None, required=True, source=False, global_condition=False):
        engine._strings(ids, 'claim_ids')
        if (required and not ids) or any(x not in claims or (kinds and claims[x]['kind'] not in kinds) for x in ids): raise ValueError('invalid claim reference')
        allowed = {'classic_clause','ni_commentary','reference_author','compiler_annotation'}
        if not global_condition: allowed.add('ni_case')
        if source and any(not any(anchors[a]['layer'] in allowed for a in claims[x]['anchor_ids']) for x in ids): raise ValueError('claim lacks eligible source layer')
    def component(c):
        if not isinstance(c, dict) or not isinstance(c.get('provenance'), dict): raise ValueError('invalid component')
        for field, kinds in (('name',{'identity'}),('processing',{'processing'}),('source_dose',{'dose'}),('source_unit',{'dose'})):
            value = c.get(field)
            if value is not None: engine._text(value, field)
            if field == 'name' and value is None: raise ValueError('missing name')
            ids = c['provenance'].get(field)
            refs(ids, kinds, value is not None, source=True)
            if value is None and ids: raise ValueError('unknown field has provenance')
    for f in formulas.values():
        engine._text(f.get('name'),'formula name'); engine._text(f.get('catalog_id'),'catalog id')
        refs(f.get('identity_claim_ids'), {'identity'}, source=True)
        for c in engine._list(f.get('components'),'components'): component(c)
        for item in engine._list(f.get('preparation'),'preparation'):
            engine._text(item.get('text'),'preparation'); refs(item.get('claim_ids'), {'preparation'}, source=True)
        engine._strings(f.get('limitations'),'limitations')
    for n in nodes.values():
        engine._text(n.get('label'),'node label'); engine._text(n.get('scope'),'scope')
        if n.get('kind') not in ('pattern','syndrome','treatment') or (n.get('formula_version_id') is not None and n['formula_version_id'] not in formulas): raise ValueError('invalid node')
        refs(n.get('scope_claim_ids'), required=False)
        refs(n.get('treatment_claim_ids', []), {'treatment'}, required=False, source=True)
        _unique(n.get('conditions'),'id')
        for c in n['conditions']:
            role = c.get('role')
            kinds = {'required': {'necessary'}, 'support': {'support'}, 'exclude': {'exclusion'}, 'course': {'course'}}
            if role not in kinds: raise ValueError('invalid role')
            engine._expr(c.get('expr')); refs(c.get('claim_ids'), kinds[role], source=role != 'support', global_condition=role != 'support')
            if role == 'required' and any(claims[x]['inference'] != 'literal' for x in c['claim_ids']): raise ValueError('necessary must be literal')
        _unique(n.get('cases', []), 'id')
        for case in n.get('cases', []):
            engine._text(case.get('label'), 'case label'); engine._text(case.get('scope'), 'case scope')
            engine._expr(case.get('expr'))
            refs(case.get('claim_ids'), {'support','course','differential','interpretation'}, source=True)
        for q in engine._list(n.get('questions'),'questions'):
            for k in ('key','question','reason'): engine._text(q.get(k),k)
            refs(q.get('claim_ids'))
        engine._strings(n.get('limitations'),'limitations')
    adjacency = {x: [] for x in nodes}
    for e in p['edges']:
        if e.get('from') not in nodes or e.get('to') not in nodes or e.get('relation') not in ('differential','refines','coexists','treatment'): raise ValueError('invalid edge')
        refs(e.get('claim_ids'), source=e['relation'] == 'treatment'); engine._text(e.get('note'),'note')
        adjacency[e['from']].append(e['to'])
    visiting, visited = set(), set()
    def visit(x):
        if x in visiting: raise ValueError('cyclic graph')
        if x in visited: return
        visiting.add(x)
        for y in adjacency[x]: visit(y)
        visiting.remove(x); visited.add(x)
    for node in nodes: visit(node)
    for m in p['modifications']:
        if m.get('base_version_id') not in formulas or (m.get('target_version_id') is not None and m['target_version_id'] not in formulas): raise ValueError('invalid modification version')
        engine._expr(m.get('trigger')); refs(m.get('claim_ids'), {'modification'}, source=True)
        engine._strings(m.get('limitations'),'limitations')
        for action in engine._list(m.get('actions'),'actions'):
            op = action.get('operation')
            if op not in ('add','remove','replace','adjust'): raise ValueError('invalid operation')
            refs(action.get('claim_ids'), {'modification'}, source=True)
            if op != 'add': engine._text(action.get('target_name'),'target name')
            if op != 'remove': component(action.get('component'))


def import_package(conn, payload):
    _validate(conn,payload)
    data = _encode(payload); digest_value = _hash(data)
    row = conn.execute('SELECT digest FROM decision_packages WHERE id=? AND version=?', (payload['id'],payload['version'])).fetchone()
    if row and row[0] != digest_value: raise ValueError('immutable package version')
    if not row: conn.execute('INSERT INTO decision_packages VALUES (?,?,?,?)',(payload['id'],payload['version'],digest_value,data))
    return {k: len(payload[k]) for k in ('anchors','claims','formulas','nodes','edges','modifications')}


def load_packages(conn):
    packages = []
    for id, version, stored_digest, payload in conn.execute('SELECT id,version,digest,payload FROM decision_packages ORDER BY id,version'):
        try:
            snapshot = json.loads(payload)
            valid = isinstance(snapshot, dict) and snapshot.get('id') == id and snapshot.get('version') == version and _hash(_encode(snapshot)) == stored_digest
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError('decision package integrity mismatch')
        _validate(conn, snapshot, check_source=False)
        packages.append({'id': id, 'version': version, 'digest': stored_digest, 'snapshot': snapshot})
    return packages


def _digest(packages):
    return _hash(_encode([(p['id'],p['version'],p['digest']) for p in packages]))


def digest(conn):
    return _digest(load_packages(conn))


def _coverage(packages):
    active = {}
    for package in packages: active[package['id']] = package
    return {'packages': len(active), 'installed_versions': len(packages), 'active_packages': len(active), 'nodes': sum(len(p['snapshot']['nodes']) for p in active.values()), 'mapped_formulas': sum(len(p['snapshot']['formulas']) for p in active.values()), 'status': 'partial' if active else 'uncovered'}


def coverage(conn):
    return _coverage(load_packages(conn))


def _latest(packages, package_id=None):
    latest = {}
    for p in packages:
        if package_id is None or p['id'] == package_id: latest[p['id']] = p
    return list(latest.values())


def _questions(nodes, edges):
    grouped = {}
    for node in nodes:
        if node['status'] in ('excluded', 'source_invalid'):
            continue
        traces = node['conditions'] + node['case_traces']
        for question in node['questions']:
            key = question['key']
            causes = [c for c in traces if key in c['trace']['conflicts'] or
                      (c['trace']['value'] is None and key in c['trace']['missing'])]
            if not causes:
                continue
            # Preserve distinct source wording; a shared fact key is not a shared medical claim.
            item = grouped.setdefault((key, question['question']), {
                **deepcopy(question), 'package_id': node['package_id'], 'package_version': node['package_version'],
                'node_ids': [], 'source_bindings': [], 'priority': {
                    'clarify_conflict': False, 'source_constraint': False, 'differential_refs': [],
                    'basis': 'source_graph_structure_not_diagnostic_probability'}})
            if node['id'] not in item['node_ids']:
                item['node_ids'].append(node['id'])  # Legacy display IDs; bindings carry the qualified identity.
            item['source_bindings'].append({
                'package_id': node['package_id'], 'package_version': node['package_version'], 'node_id': node['id'],
                'node_status': node['status'], 'scope': node['scope'], 'question': question['question'],
                'reason': question['reason'], 'claim_ids': deepcopy(question['claim_ids']),
                'condition_refs': [{'id': c['id'], 'role': c.get('role', 'case'), 'claim_ids': deepcopy(c['claim_ids']),
                                    'state': 'conflict' if key in c['trace']['conflicts'] else 'unknown'} for c in causes]})
            priority = item['priority']
            priority['clarify_conflict'] |= any(key in c['trace']['conflicts'] for c in causes)
            priority['source_constraint'] |= any(c.get('role') in ('required', 'exclude', 'course') for c in causes)
            for edge in edges:
                if (edge['relation'] != 'differential' or edge['package_id'] != node['package_id']
                        or edge['package_version'] != node['package_version'] or node['id'] not in (edge['from'], edge['to'])
                        or any(edge[k] in ('excluded', 'source_invalid') for k in ('from_status', 'to_status'))):
                    continue
                ref = {k: deepcopy(edge[k]) for k in ('package_id', 'package_version', 'id', 'from', 'to', 'claim_ids')}
                if ref not in priority['differential_refs']:
                    priority['differential_refs'].append(ref)
    return sorted(grouped.values(), key=lambda q: (
        q['priority']['clarify_conflict'], q['priority']['source_constraint'],
        len(q['priority']['differential_refs']), len(q['source_bindings'])), reverse=True)


def evaluate(conn, facts, package_id=None):
    indexed, ignored = engine._facts(facts)
    registry = load_packages(conn)
    packages = _latest(registry, package_id)
    result = dict(packages=packages,nodes=[],edges=[],questions=[],formulas=[],anchors=[],claims=[],ignored_facts=ignored,source_issues=[],safety={'status':'incomplete'},coverage=_coverage(registry),registry_digest=_digest(registry))
    for package in packages:
        p = package['snapshot']; issues = _source_issues(conn,p)
        result['source_issues'].extend([dict(package_id=p['id'], **i) for i in issues])
        for field in ('anchors','claims','formulas'):
            result[field].extend([{**deepcopy(item), 'package_id':p['id'], 'package_version':p['version']} for item in p[field]])
        statuses = {}
        for n in p['nodes']:
            traces = [dict(deepcopy(c), trace=engine._evaluate(c['expr'],indexed)) for c in n['conditions']]
            cases = [dict(deepcopy(c), trace=engine._evaluate(c['expr'],indexed)) for c in n.get('cases', [])]
            conflicts = {x for c in traces + cases for x in c['trace']['conflicts']}
            if issues: status = 'source_invalid'
            elif conflicts: status = 'conflict'
            elif any((c['role'] in ('required','course') and c['trace']['value'] is False) or (c['role'] == 'exclude' and c['trace']['value'] is True) for c in traces): status = 'excluded'
            elif any(c['trace']['value'] is None for c in traces if c['role'] in ('required','course','exclude')): status = 'pending'
            elif any(c['trace']['value'] is True for c in cases): status = 'compatible'
            elif any(c['trace']['value'] is None for c in cases): status = 'pending'
            elif any(c['role'] != 'exclude' and c['trace']['value'] is True for c in traces): status = 'clue'
            else: status = 'pending'
            statuses[n['id']] = status
            result['nodes'].append({**deepcopy(n),'package_id':p['id'],'package_version':p['version'],'status':status,'conditions':traces,'case_traces':cases})
        for e in p['edges']:
            result['edges'].append({**deepcopy(e),'package_id':p['id'],'package_version':p['version'],'from_status':statuses[e['from']],'to_status':statuses[e['to']], 'retained_parent': e['relation'] == 'refines' and statuses[e['to']] in ('pending','excluded','conflict','clue') and statuses[e['from']] in ('compatible','pending','conflict','clue')})
    result['questions'] = _questions(result['nodes'], result['edges'])
    return result


def preview_modifications(conn, package_id, base_version_id, modification_ids, facts, package_version=None):
    indexed, ignored = engine._facts(facts)
    engine._strings(modification_ids, 'modification_ids')
    registry = load_packages(conn)
    if package_version is not None and (type(package_version) is not int or package_version < 1): raise ValueError('invalid package version')
    packages = _latest(registry, package_id) if package_version is None else [p for p in registry if p['id'] == package_id and p['version'] == package_version]
    if not packages: raise ValueError('package not found')
    p = packages[0]['snapshot']; issues = _source_issues(conn,p)
    formulas = {f['version_id']: f for f in p['formulas']}
    mods = {m['id']: m for m in p['modifications']}
    if base_version_id not in formulas or len(set(modification_ids)) != len(modification_ids) or any(x not in mods for x in modification_ids): raise ValueError('unknown version or modification')
    base = deepcopy(formulas[base_version_id]['components']); proposed = deepcopy(base)
    conflicts, missing, traces, diff, touched = [], [], [], [], set()
    selected = [mods[x] for x in modification_ids]
    if issues: conflicts.append('来源原文失效')
    if any(not c.get('name') or not c.get('processing') for c in base):
        conflicts.append('基方药味或炮制身份不明确')
    for m in selected:
        trace = engine._evaluate(m['trigger'],indexed)
        traces.append({'id':m['id'],'trace':trace})
        missing.extend(trace['missing'])
        if m['base_version_id'] != base_version_id: conflicts.append('基方版本不一致: ' + m['id'])
        if trace['conflicts']: conflicts.extend(trace['conflicts'])
        if trace['value'] is not True: conflicts.append('触发条件未明确满足: ' + m['id'])
        for a in m['actions']:
            op = a['operation']; name = a.get('target_name'); processing = a.get('target_processing')
            component = deepcopy(a.get('component'))
            target = [i for i,c in enumerate(proposed) if c['name'] == name and c.get('processing') == processing] if name else []
            involved = [(name,processing)] if name else []
            if component and op in ('add','replace'): involved.append((component['name'],component.get('processing')))
            if any(x in touched for x in involved): conflicts.append('动作涉及重复身份')
            touched.update(involved)
            if op != 'add' and (not processing or len(target) != 1):
                conflicts.append('目标身份或炮制不明确: ' + str(name)); continue
            if op in ('add','replace') and any(c['name'] == component['name'] and c.get('processing') == component.get('processing') for c in proposed):
                conflicts.append('新增身份已存在: ' + component['name']); continue
            before = deepcopy(proposed[target[0]]) if target else None
            if op == 'remove': proposed.pop(target[0])
            elif op == 'add': proposed.append(component)
            elif op == 'replace': proposed[target[0]] = component
            else:
                if component['name'] != name or component.get('processing') != processing:
                    conflicts.append('调整改变药味或炮制身份'); continue
                proposed[target[0]] = component
            diff.append({'modification_id':m['id'],'operation':op,'before':before,'after':component if op != 'remove' else None})
    def values(components):
        return sorted([tuple((c.get(k) or '') for k in ('name','processing','source_dose','source_unit')) for c in components])
    for m in selected:
        target = m.get('target_version_id')
        if target and values(proposed) != values(formulas[target]['components']):
            conflicts.append('目标版本有未解释差异: ' + target)
            diff.append({'target_version_id':target,'computed':deepcopy(proposed),'target':deepcopy(formulas[target]['components'])})
    return {'package_id':p['id'],'package_version':p['version'],'base_version_id':base_version_id,
            'components':base if conflicts else proposed,'diff':diff,'applied':[] if conflicts else deepcopy(selected),
            'unapplied':[dict(deepcopy(m),reason='整组回退：' + '；'.join(dict.fromkeys(conflicts))) for m in selected] if conflicts else [],
            'missing':sorted(set(missing)),'conflicts':list(dict.fromkeys(conflicts)), 'traces':traces,
            'ignored_facts':ignored,'source_issues':issues,'safety':{'status':'incomplete'}}
