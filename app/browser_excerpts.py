"""Read the bundled, source-identified extracts when a full book is not installed."""
from functools import lru_cache
import json
from . import consultation_library, library
from .knowledge import _normalize


def locator(source):
    value = source['locator']
    if isinstance(value, dict):
        return value
    if value.startswith('physical_page:'):
        return {'kind': 'pdf_page', 'start': int(value.split(':', 1)[1].split(',', 1)[0]),
                'printed_page': source.get('printed_page')}
    try:
        return json.loads(value)
    except ValueError:
        return {'kind': 'record', 'start': value}


def _unit_number(source):
    """Resolve the original page/unit from either unit_no or a page locator.

    Modification-rule sources carry only ``physical_page:<n>`` and were
    previously dropped from the excerpt index entirely.
    """
    number = source.get('unit_no')
    if type(number) is int and number > 0:
        return number
    value = source.get('locator')
    if isinstance(value, dict):
        if value.get('kind') in ('pdf_page', 'physical_page') and type(value.get('start')) is int:
            return value['start']
        return None
    if isinstance(value, str):
        prefix, _, rest = value.partition(':')
        if prefix == 'physical_page':
            digits = rest.split(',', 1)[0]
            if digits.isdigit() and int(digits) > 0:
                return int(digits)
    return None


def _dedupe(fragments):
    """Keep the longest verbatim excerpt when one excerpt contains another.

    The extracted quotes for one page often repeat the same sentence with
    growing context; showing every copy made the reader see the same passage
    several times.
    """
    kept = []
    for index, item in sorted(enumerate(fragments), key=lambda pair: len(pair[1]['text']), reverse=True):
        if any(item['text'] in other['text'] for _, other in kept):
            continue
        kept.append((index, item))
    return [item for _, item in sorted(kept)]


@lru_cache(maxsize=1)
def _units(digest):
    result = {}
    for source in consultation_library._source_index(digest).values():
        sha = source.get('source_id', source.get('document_id'))
        number = _unit_number(source)
        if type(number) is not int or number <= 0 or not isinstance(sha, str) or not sha:
            continue
        quote, quote_hash = consultation_library._quote(source)
        key = (sha, number)
        row = result.setdefault(key, {'source_id': sha, 'unit_no': number, 'title': source['source_title'],
                    'format': 'excerpt', 'locator': locator(source), 'corpus_role': '库内原文摘录',
                    'content_scope': 'extracted_quotes', 'fragments': []})
        if not any(item['quote_sha256'] == quote_hash for item in row['fragments']):
            row['fragments'].append({'text': quote, 'quote_sha256': quote_hash})
    for row in result.values():
        row['fragments'] = _dedupe(row['fragments'])
    return result


def units():
    return _units(consultation_library._refresh())


def list_sources(conn):
    complete = library.list_sources(conn)
    known = {s['id'] for s in complete}
    fallback = {}
    for (sha, number), item in units().items():
        if sha in known:
            continue
        row = fallback.setdefault(sha, {'id': sha, 'title': item['title'], 'format': 'excerpt',
                      'units': 0, 'pdf_pages': None, 'corpus_role': '库内原文摘录',
                      'content_scope': 'extracted_quotes', 'has_ocr': False})
        row['units'] += 1
    return complete + sorted(fallback.values(), key=lambda s: s['title'])


def get_unit(conn, data_dir, source_id, number):
    full = library.get_unit(conn, data_dir, source_id, number)
    if full is not None:
        return full
    value = units().get((source_id, number))
    if not value:
        return None
    return {**value, 'raw_text': '\n\n'.join(f['text'] for f in value['fragments']),
            'ocr_text': None, 'corrected_text': None, 'image_url': None, 'original_url': None,
            'warning': '已提取原文片段；完整页及原件通过本地知识包读取'}


def search(conn, query, source_id=None, limit=30):
    if not isinstance(query, str) or len(query) > 200 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('检索参数无效')
    term = _normalize(query.strip())
    if len(term) < 2:
        raise ValueError('请输入至少两个字检索原文')
    rows = library.search(conn, query, source_id, limit)
    complete = {s['id'] for s in library.list_sources(conn)}
    for (sha, number), row in units().items():
        if sha in complete or (source_id and sha != source_id):
            continue
        matching = [f['text'] for f in row['fragments'] if term in _normalize(f['text'])]
        if matching:
            rows.append({k: row[k] for k in ('source_id', 'unit_no', 'title', 'format', 'locator', 'corpus_role', 'content_scope')})
            # Center the preview on the query instead of always returning the
            # start of the excerpt, which could hide the matched phrase.
            rows[-1]['snippet'] = library._snippet(matching[0], query)
        if len(rows) >= limit:
            break
    return rows[:limit]
