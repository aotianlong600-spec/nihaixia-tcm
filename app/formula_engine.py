"""Local source-backed formula retrieval; scores are retrieval heuristics."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def _library():
    return json.loads((Path(__file__).parent / 'resources' / 'open_formula_library.json').read_text(encoding='utf-8'))


def load_library():
    return deepcopy(_library())


def get_formula(formula_id):
    return next((deepcopy(f) for f in _library()['formulas'] if f['id'] == formula_id), None)


def match_patterns(facts, query='', limit=8):
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        return []
    states = {}
    for f in facts:
        if f.get('verified') is True and f.get('scope', 'current') == 'current' and f.get('subject', 'patient') == 'patient' and f.get('state') in ('present', 'absent'):
            states.setdefault(f.get('key'), set()).add(f['state'])
    library = load_library()
    formulas = {f['id']: f for f in library['formulas']}
    candidates = []
    for p in library['patterns']:
        f = formulas.get(p['formula_id'])
        if not f:
            continue
        matched, missing, contradictions = [], [], []
        score = 0
        for groups, weight in ((p.get('required', []), 3), (p.get('reference', []), 1)):
            for group in groups:
                hits = [s for s in group if states.get(s) == {'present'}]
                negatives = [s for s in group if states.get(s) == {'absent'}]
                label = ' / '.join(group)
                if hits:
                    matched.append(' / '.join(hits)); score += weight
                elif negatives and len(negatives) == len(group):
                    contradictions.append(label); score -= weight
                elif weight == 3:
                    missing.append(label)
        # Query only retrieves; it never counts as confirmed clinical evidence.
        searchable = ' '.join([p['name'], p.get('syndrome', ''), f.get('syndrome', '')] + [s for g in p.get('required', []) + p.get('reference', []) for s in g])
        term = query.strip()
        query_hit = bool(term and (term in searchable or any(t and t in searchable for t in (term.removeprefix('不'), term.removeprefix('无'), term.removeprefix('没有')))))
        if not matched and not contradictions and not query_hit:
            continue
        candidates.append(dict(id=p['id'], formula_id=f['id'], name=p['name'], syndrome=p.get('syndrome', ''), six_meridian=p.get('six_meridian', ''), matched_features=matched, missing_features=missing, contradictions=contradictions, score=score, score_explanation='线索检索排序分，不是诊断概率', components=deepcopy(f['components']), modification_notes=deepcopy(f.get('modification_notes', [])), contraindications=deepcopy(f.get('contraindications', [])), source_refs=list(dict.fromkeys(p.get('source_refs', []) + f.get('source_refs', [])))))
    return sorted(candidates, key=lambda c: c['score'], reverse=True)[:limit]


def preview_modifications(formula_id, modifications):
    """Preview only source-explicit changes without mutating the original formula."""
    formula = get_formula(formula_id)
    warnings = ['仅为文献/AI草案差异预览，不是个人日处方；原方剂量为来源原文，未作单位换算。',
                '仅覆盖来源明确支持的动作；未核验症状适用性、炮制、剂量或安全性。']
    result = {'components': deepcopy(formula['components']) if formula else [], 'applied': [], 'unapplied': [], 'conflicts': [], 'warnings': warnings}
    if not formula:
        result['unapplied'] = [dict(deepcopy(m), reason='未找到来源方剂') for m in modifications]
        return result

    base = formula['components']
    names = [c['name'] for c in base]
    touched = set()
    for m in modifications:
        action, herb, replacement = m.get('action'), m.get('herb'), m.get('replacement')
        involved = [herb] + ([replacement] if action == 'replace' and replacement else [])
        for name in involved:
            if name in touched:
                result['conflicts'].append(f'{name} 涉及重复或互斥动作')
            touched.add(name)
        if action in ('remove', 'replace', 'adjust') and names.count(herb) > 1:
            result['conflicts'].append(f'{herb} 在原方中有多条记录，无法确定炮制身份')
        if action == 'add' and herb in names:
            result['conflicts'].append(f'{herb} 已在原方中，不能重复添加')
        if action in ('remove', 'replace', 'adjust') and herb not in names:
            result['conflicts'].append(f'{herb} 不在原方中，无法执行 {action}')
        if action == 'replace' and replacement in names:
            result['conflicts'].append(f'{replacement} 已在原方中，不能重复替换添加')
    if result['conflicts']:
        result['unapplied'] = [dict(deepcopy(m), reason='存在冲突，整组回退原方') for m in modifications]
        return result

    for m in modifications:
        action, herb, replacement = m.get('action'), m.get('herb'), m.get('replacement')
        sources = [n for n in formula.get('modification_notes', [])
                   if n.get('type') == action and herb in n.get('herbName', '').split('、')
                   and (action != 'replace' or (replacement and n.get('replaceWith') == replacement))]
        if len(sources) != 1:
            result['unapplied'].append(dict(deepcopy(m), reason='来源未明确支持此动作或来源记录不唯一'))
            continue
        source = sources[0]
        description = source.get('description', '')
        if action == 'add' and ('去' in description or '加重' in description or '替换' in description):
            result['unapplied'].append(dict(deepcopy(m), reason='来源动作字段与描述含其他动作，无法安全拆分', source_ref=source.get('source_ref')))
            continue
        if action not in ('add', 'remove', 'replace', 'adjust'):
            result['unapplied'].append(dict(deepcopy(m), reason='不支持此动作'))
            continue
        components = result['components']
        if action in ('remove', 'replace'):
            components[:] = [c for c in components if c['name'] != herb]
        if action in ('add', 'replace'):
            components.append({'name': replacement if action == 'replace' else herb, 'processing': None, 'source_dose': None, 'source_unit': None, 'source_ref': source.get('source_ref')})
        if action == 'adjust':
            for component in components:
                if component['name'] == herb:
                    component['source_dose'] = None
                    component['source_unit'] = None
        result['applied'].append(dict(deepcopy(m), source_ref=source.get('source_ref')))
    return result
