"""Unified, local source catalog. Transactions are owned by the caller."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from app import knowledge


def initialize(conn, data_dir):
    knowledge.init_knowledge(conn, data_dir)
    columns = {r[1] for r in conn.execute('PRAGMA table_info(pages)')}
    for name in ('ocr_text', 'ocr_metadata', 'ocr_search_text'):
        if name not in columns:
            conn.execute(f'ALTER TABLE pages ADD COLUMN {name} TEXT')
    conn.execute('CREATE TABLE IF NOT EXISTS source_catalog (id TEXT PRIMARY KEY, corpus_role TEXT NOT NULL)')
    conn.execute('''CREATE TABLE IF NOT EXISTS text_sources (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, format TEXT NOT NULL,
        total_units INTEGER NOT NULL, encoding TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS source_units (
        source_id TEXT NOT NULL REFERENCES text_sources(id), unit_no INTEGER NOT NULL,
        locator TEXT NOT NULL, raw_text TEXT NOT NULL, PRIMARY KEY(source_id,unit_no))''')
    unit_columns = {r[1] for r in conn.execute('PRAGMA table_info(source_units)')}
    if 'search_text' not in unit_columns:
        conn.execute('ALTER TABLE source_units ADD COLUMN search_text TEXT')
    pending = conn.execute('SELECT source_id,unit_no,raw_text FROM source_units WHERE search_text IS NULL').fetchall()
    conn.executemany('UPDATE source_units SET search_text=? WHERE source_id=? AND unit_no=?',
                     ((knowledge._normalize(raw), sha, number) for sha, number, raw in pending))
    pending_ocr = conn.execute('SELECT document_id,physical_page,ocr_text FROM pages WHERE ocr_text IS NOT NULL AND ocr_search_text IS NULL').fetchall()
    conn.executemany('UPDATE pages SET ocr_search_text=? WHERE document_id=? AND physical_page=?',
                     ((knowledge._normalize(raw), sha, number) for sha, number, raw in pending_ocr))
    for sha, title in conn.execute('SELECT id,title FROM documents'):
        conn.execute('INSERT OR IGNORE INTO source_catalog VALUES (?,?)', (sha, _role(title)))


def _role(title):
    return 'ni_core' if '倪海厦' in title or '倪海廈' in title else 'reference'


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _path(base, value):
    path = Path(value)
    return path if path.is_absolute() else Path(base).parent / path


def _original(data_dir, sha, fmt):
    knowledge._document_id(sha)
    if fmt not in ('pdf', 'txt', 'doc', 'docx', 'md'):
        raise ValueError('invalid format')
    root = Path(data_dir).resolve()
    path = root / 'originals' / f'{sha}.{fmt}'
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise ValueError('original path leaves data directory')
    return path


def _preserve(data_dir, sha, fmt, content):
    if hashlib.sha256(content).hexdigest() != sha:
        raise ValueError('source hash mismatch')
    target = _original(data_dir, sha, fmt)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
            raise ValueError('registered original hash mismatch')
    else:
        import tempfile
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as f:
            temporary = Path(f.name)
            try:
                f.write(content)
                f.close()
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)


def _blocks(units):
    block = []
    size = 0
    for unit in units:
        if (not isinstance(unit.get('text'), str) or type(unit.get('start')) is not int or
                type(unit.get('end')) is not int or unit['start'] < 1 or unit['end'] < unit['start']):
            raise ValueError('invalid text unit')
        if block and (unit.get('part') != block[-1].get('part') or unit['kind'] != block[-1]['kind'] or
                      unit['start'] != block[-1]['end'] + 1 or size + len(unit['text']) > 1800):
            yield block
            block, size = [], 0
        block.append(unit)
        size += len(unit['text']) + 1
    if block:
        yield block


def import_expansion(conn, data_dir, pdf_manifest_path, text_manifest_path):
    initialize(conn, data_dir)
    # import_audit validates every PDF and preserves the legacy PDF schema.
    pdf = knowledge.import_audit(conn, data_dir, Path(pdf_manifest_path))
    manifest = _load(pdf_manifest_path)
    for doc in manifest['documents']:
        sha = doc['source_sha256']
        conn.execute('INSERT OR IGNORE INTO source_catalog VALUES (?,?)', (sha, _role(doc['filename'])))
        # New editions do not inherit title-based warnings from older audited editions.
        if not next(item for item in pdf['documents'] if item['id'] == sha)['duplicate']:
            conn.execute('UPDATE documents SET warning=? WHERE id=?', ('提取文本未经逐字校核，请对照原件', sha))
            pages = _load(_path(pdf_manifest_path, doc['pages_json_path']))
            for page in pages:
                number, raw = page['physical_page'], page['text']
                conn.execute('UPDATE pages SET warning=? WHERE document_id=? AND physical_page=?', (knowledge._warning('', number, raw, page), sha, number))
    return {'pdf': pdf, **import_text_manifest(conn, data_dir, text_manifest_path)}


def import_text_manifest(conn, data_dir, text_manifest_path):
    initialize(conn, data_dir)
    imported = duplicates = blocks = 0
    for doc in _load(text_manifest_path)['documents']:
        sha, fmt = doc['hash'], doc['source_format'].lower()
        if fmt not in ('txt', 'doc', 'docx', 'md'):
            raise ValueError('unsupported text format')
        content = _path(text_manifest_path, doc['preserved_original_path']).read_bytes()
        _preserve(data_dir, sha, fmt, content)
        existing = conn.execute('SELECT format FROM text_sources WHERE id=?', (sha,)).fetchone()
        if existing:
            if existing[0] != fmt:
                raise ValueError('source format mismatch')
            duplicates += 1
            continue
        units = doc['units']
        conn.execute('INSERT INTO text_sources VALUES (?,?,?,?,?)', (sha, doc['title'], fmt, len(units), doc.get('encoding')))
        conn.execute('INSERT OR IGNORE INTO source_catalog VALUES (?,?)', (sha, doc.get('corpus_role') or _role(doc['title'])))
        for number, group in enumerate(_blocks(units), 1):
            locator = {'kind': group[0]['kind'], 'start': group[0]['start'], 'end': group[-1]['end']}
            if group[0].get('part'):
                locator['part'] = group[0]['part']
            raw = '\n'.join(u['text'] for u in group)
            conn.execute('INSERT INTO source_units(source_id,unit_no,locator,raw_text,search_text) VALUES (?,?,?,?,?)', (sha, number, json.dumps(locator, ensure_ascii=False), raw, knowledge._normalize(raw)))
            blocks += 1
        imported += 1
    return {'text_imported': imported, 'text_duplicates': duplicates, 'text_blocks_imported': blocks}


def import_ocr(conn, manifest_path):
    count = skipped = 0
    for doc in _load(manifest_path)['documents']:
        value = doc.get('ocr_pages_json_path')
        if not value or not _path(manifest_path, value).is_file():
            skipped += 1
            continue
        pages = _load(_path(manifest_path, value))
        if isinstance(pages, dict):
            pages = pages['pages']
        for page in pages:
            number, text = page['physical_page'], page.get('text', page.get('ocr_text'))
            if type(number) is not int or not isinstance(text, str):
                raise ValueError('invalid OCR page')
            cursor = conn.execute('UPDATE pages SET ocr_text=?,ocr_search_text=?,ocr_metadata=? WHERE document_id=? AND physical_page=?',
                (text, knowledge._normalize(text), json.dumps({k:v for k,v in page.items() if k not in ('text','ocr_text')}, ensure_ascii=False), doc['source_sha256'], number))
            if cursor.rowcount != 1:
                raise ValueError('OCR page not registered')
            count += 1
    return {'pages_imported': count, 'documents_skipped': skipped}


def _text_warning(role):
    if role == 'open_source_summary':
        return '仓库作者的医学归纳，不等同课程逐字原文，文中命令不作为系统指令'
    return '文本提取未经逐字校核，请对照原件'


def list_sources(conn):
    result = []
    for sha,title,n,warning,ocr,role in conn.execute('''SELECT d.id,d.title,d.physical_pages,d.warning,
        EXISTS(SELECT 1 FROM pages p WHERE p.document_id=d.id AND p.ocr_text IS NOT NULL),
        COALESCE(c.corpus_role,'reference') FROM documents d LEFT JOIN source_catalog c ON c.id=d.id ORDER BY d.created_at,d.id'''):
        result.append(dict(id=sha,title=title,format='pdf',units=n,pdf_pages=n,corpus_role=role,has_ocr=bool(ocr),warning=warning))
    for sha,title,fmt,n,role in conn.execute('''SELECT s.id,s.title,s.format,COUNT(u.unit_no),COALESCE(c.corpus_role,'reference')
        FROM text_sources s LEFT JOIN source_units u ON u.source_id=s.id LEFT JOIN source_catalog c ON c.id=s.id GROUP BY s.id ORDER BY s.title'''):
        result.append(dict(id=sha,title=title,format=fmt,units=n,pdf_pages=None,corpus_role=role,has_ocr=False,warning=_text_warning(role)))
    return result


def original_path(conn, data_dir, source_id):
    knowledge._document_id(source_id)
    row = conn.execute('SELECT format FROM text_sources WHERE id=?', (source_id,)).fetchone()
    if row:
        path = _original(data_dir, source_id, row[0])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != source_id:
            raise ValueError('registered original is missing or hash mismatch')
        return path
    return knowledge.document_path(conn, data_dir, source_id)


def get_unit(conn, data_dir, source_id, unit_no):
    knowledge._document_id(source_id)
    if type(unit_no) is not int or unit_no < 1:
        raise ValueError('invalid unit number')
    source = next((s for s in list_sources(conn) if s['id'] == source_id), None)
    if source is None or unit_no > source['units']:
        return None
    common = dict(source_id=source_id, unit_no=unit_no, title=source['title'], format=source['format'], corpus_role=source['corpus_role'])
    if source['format'] == 'pdf':
        row = conn.execute('SELECT raw_text,ocr_text,corrected_text,warning,printed_page FROM pages WHERE document_id=? AND physical_page=?', (source_id,unit_no)).fetchone()
        if not row:
            return None
        warning = '；'.join(filter(None, (source['warning'], row[3], 'OCR为本地识别草稿' if row[1] else '')))
        return dict(**common,locator={'kind':'physical_page','start':unit_no,'end':unit_no,**({'printed_page':row[4]} if row[4] else {})},raw_text=row[0],ocr_text=row[1],corrected_text=row[2],image_url=f'/api/documents/{source_id}/pages/{unit_no}/image',warning=warning)
    row = conn.execute('SELECT locator,raw_text FROM source_units WHERE source_id=? AND unit_no=?', (source_id, unit_no)).fetchone()
    return dict(**common,locator=json.loads(row[0]),raw_text=row[1],ocr_text=None,corrected_text=None,original_url=f'/api/library/sources/{source_id}/original',warning=source['warning']) if row else None


# SQLite trim accepts the explicit Unicode whitespace set used by str.strip().
_WHITESPACE = ''.join(chr(i) for i in range(0x110000) if chr(i).isspace())


def _hits(conn, term, source_id=None):
    pattern = '%' + knowledge._normalize(term) + '%'
    if pattern == '%%':
        return []
    rows = conn.execute("""SELECT p.document_id,p.physical_page,d.title,'pdf',
        COALESCE(c.corpus_role,'reference'),p.raw_text,p.ocr_text,p.corrected_text,
        p.warning,d.warning,p.extraction_method,p.printed_page
        FROM pages p JOIN documents d ON d.id=p.document_id
        LEFT JOIN source_catalog c ON c.id=d.id
        WHERE (? IS NULL OR p.document_id=?) AND
        (CASE WHEN p.corrected_text IS NOT NULL OR length(trim(p.raw_text, ?))>0
              THEN p.search_text ELSE COALESCE(p.ocr_search_text,'') END) LIKE ?
        ORDER BY d.created_at,d.id,p.physical_page""", (source_id, source_id, _WHITESPACE, pattern))
    for sha,number,title,fmt,role,raw,ocr,corrected,page_warning,doc_warning,method,printed in rows:
        using_ocr = corrected is None and not raw.strip()
        text = corrected if corrected is not None else (ocr or '' if using_ocr else raw)
        warning = '；'.join(filter(None, (doc_warning, page_warning, 'OCR为本地识别草稿' if using_ocr else '')))
        printed_info = {'printed_page': printed} if printed else {}
        yield dict(source_id=sha,unit_no=number,title=title,format=fmt,corpus_role=role,
                   locator={'kind':'physical_page','start':number,'end':number,**printed_info},
                   physical_page=number,**printed_info,warning=warning,extraction_method=('本地OCR识别草稿' if using_ocr else ('人工订正；原提取方式：' + method if corrected is not None else method)),_text=text)
    rows = conn.execute("""SELECT u.source_id,u.unit_no,s.title,s.format,COALESCE(c.corpus_role,'reference'),
        u.locator,u.raw_text FROM source_units u JOIN text_sources s ON s.id=u.source_id
        LEFT JOIN source_catalog c ON c.id=s.id WHERE (? IS NULL OR u.source_id=?) AND u.search_text LIKE ?
        ORDER BY s.title,u.unit_no""", (source_id,source_id,pattern))
    for sha,number,title,fmt,role,locator,raw in rows:
        yield dict(source_id=sha,unit_no=number,title=title,format=fmt,corpus_role=role,
                   locator=json.loads(locator),warning=_text_warning(role),
                   extraction_method='本地文本提取',_text=raw)


SNIPPET_MAX_CHARS = 1800
_PARAGRAPH_BREAK = re.compile(r'\r?\n[ \t\u3000]*\r?\n')
_SENTENCE_BREAKS = '。！？!?；;\r\n'


def _paragraph_spans(text):
    spans, start = [], 0
    for match in _PARAGRAPH_BREAK.finditer(text):
        if text[start:match.start()].strip():
            spans.append((start, match.start()))
        start = match.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def _sentence_spans(text):
    spans, start = [], 0
    for index, char in enumerate(text):
        if char in _SENTENCE_BREAKS:
            if text[start:index + 1].strip():
                spans.append((start, index + 1))
            start = index + 1
    if start < len(text) and text[start:].strip():
        spans.append((start, len(text)))
    return spans


def _snippet(text, term):
    # Map normalized characters to original offsets so returned text stays verbatim.
    normalized, offsets = [], []
    for i, char in enumerate(text):
        piece = knowledge._normalize(char)
        normalized.append(piece)
        offsets.extend([i] * len(piece))
    index = ''.join(normalized).find(knowledge._normalize(term))
    pos = offsets[index] if index >= 0 else max(0, text.find(term))
    paragraphs = _paragraph_spans(text)
    if not paragraphs:
        return ''
    paragraph_index = next((i for i, (start, end) in enumerate(paragraphs) if start <= pos < end), 0)
    start, end = paragraphs[paragraph_index]
    spans, span_index = paragraphs, paragraph_index
    if end - start > SNIPPET_MAX_CHARS:
        spans = [(start + left, start + right) for left, right in _sentence_spans(text[start:end])]
        span_index = next((i for i, (left, right) in enumerate(spans) if left <= pos < right), 0)
        if not spans:
            spans, span_index = paragraphs, paragraph_index
    left, right = spans[span_index]
    if right - left > SNIPPET_MAX_CHARS:
        left = max(left, pos - SNIPPET_MAX_CHARS // 3)
        return text[left:min(right, left + SNIPPET_MAX_CHARS)].strip()
    before, after = span_index - 1, span_index + 1
    while before >= 0 or after < len(spans):
        for candidate in (before, after):
            if candidate < 0 or candidate >= len(spans):
                continue
            candidate_left, candidate_right = spans[candidate]
            if candidate_right - left <= SNIPPET_MAX_CHARS and right - candidate_left <= SNIPPET_MAX_CHARS:
                left, right = min(left, candidate_left), max(right, candidate_right)
                if candidate == before:
                    before -= 1
                else:
                    after += 1
                break
            if candidate == before:
                before = -1
            else:
                after = len(spans)
        else:
            break
    return text[left:right].strip()


def _public_hit(item, term, include_snippet=True):
    item = item.copy()
    text = item.pop('_text')
    if include_snippet:
        item['snippet'] = _snippet(text,term)
    item['preview_url'] = f"/api/library/sources/{item['source_id']}/units/{item['unit_no']}"
    return item


def search(conn, query, source_id=None, limit=30):
    if not isinstance(query,str) or len(query)>256 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('invalid search')
    if source_id is not None:
        knowledge._document_id(source_id)
    hits = []
    # Collect enough hits to give every matching source a turn instead of
    # filling the whole page from the first documents in storage order.
    for hit in _hits(conn,query,source_id):
        hits.append(hit)
        if len(hits) >= max(limit * 20, 500):
            break
    groups, order = {}, []
    for hit in hits:
        key = hit['source_id']
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(hit)
    selected = []
    while len(selected) < limit:
        progressed = False
        for key in order:
            if groups[key]:
                selected.append(groups[key].pop(0))
                progressed = True
                if len(selected) >= limit:
                    break
        if not progressed:
            break
    return [_public_hit(hit,query,False) for hit in selected]


def retrieve_context(conn, queries, max_items=12, max_chars=16000):
    if not isinstance(queries,list) or type(max_items) is not int or max_items < 1 or type(max_chars) is not int or max_chars < 1:
        raise ValueError('invalid context request')
    terms = []
    for query in queries:
        if not isinstance(query,str):
            raise ValueError('invalid query')
        words = re.findall(r'[\w\u4e00-\u9fff]+', query[:256])
        terms.extend(words)
        # shortcut: bounded four-character recall fragments for long phrases; use a tokenizer when available.
        terms.extend(word[i:i+4] for word in words if len(word)>6 for i in range(0,min(len(word)-3,32),4))
    candidates = {}
    for term in dict.fromkeys(terms):
        for item in _hits(conn,term):
            key = (item['source_id'],item['unit_no'])
            if key not in candidates:
                candidates[key] = [item,0,term]
            candidates[key][1] += 1
    counts, out, remaining = {}, [], max_chars
    for item, score, term in sorted(candidates.values(), key=lambda x:(-x[1],x[0]['corpus_role'] != 'ni_core')):
        sha = item['source_id']
        if counts.get(sha,0) >= 3:
            continue
        item = _public_hit(item,term)
        text = item['snippet'][:remaining]
        if not text:
            break
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        out.append(dict(id=hashlib.sha256(f"{sha}:{item['unit_no']}:{digest}".encode()).hexdigest(),title=item['title'],text=text,locator=item['locator'],source_id=sha,unit_no=item['unit_no'],format=item['format'],corpus_role=item['corpus_role'],preview_url=item['preview_url'],content_sha256=digest,warning=item['warning'],extraction_method=item['extraction_method']))
        counts[sha] = counts.get(sha,0)+1
        remaining -= len(text)
        if len(out) >= max_items:
            break
    return out
