import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from app import library


def test_text_anchors_search_dedup_and_tamper(tmp_path, monkeypatch):
    conn = sqlite3.connect(':memory:')
    library.initialize(conn, tmp_path)
    monkeypatch.setattr(library.knowledge, 'import_audit', lambda *a: {'documents': []})
    pdf = tmp_path / 'pdf.json'; pdf.write_text('{"documents": []}', encoding='utf8')
    original = tmp_path / 'book.docx'; original.write_bytes(b'book')
    sha = hashlib.sha256(b'book').hexdigest()
    manifest = tmp_path / 'text.json'
    manifest.write_text(json.dumps({'documents':[{'hash':sha,'title':'参考','source_format':'docx','preserved_original_path':str(original),'units':[
        {'kind':'paragraph_range','start':1,'end':1,'part':'main','text':'桂枝汤'},
        {'kind':'paragraph_range','start':2,'end':2,'part':'main','text':'发汗'},
        {'kind':'paragraph_range','start':1,'end':1,'part':'header','text':'页眉'}]}]}), encoding='utf8')
    result = library.import_expansion(conn,tmp_path,pdf,manifest)
    assert result['text_blocks_imported'] == 2
    assert library.import_expansion(conn,tmp_path,pdf,manifest)['text_duplicates'] == 1
    unit = library.get_unit(conn,tmp_path,sha,1)
    assert unit['locator'] == {'kind':'paragraph_range','start':1,'end':2,'part':'main'}
    assert library.get_unit(conn,tmp_path,sha,2)['locator']['part'] == 'header'
    assert library.search(conn,'桂枝')[0]['source_id'] == sha
    assert library.get_unit(conn,tmp_path,sha,3) is None
    with pytest.raises(ValueError): library.original_path(conn,tmp_path,'../bad')
    (tmp_path/'originals'/f'{sha}.docx').write_bytes(b'bad')
    with pytest.raises(ValueError): library.original_path(conn,tmp_path,sha)
    with pytest.raises(ValueError): library.import_expansion(conn,tmp_path,pdf,manifest)


def test_ocr_does_not_override_native_or_raw(tmp_path):
    conn=sqlite3.connect(':memory:'); library.initialize(conn,tmp_path)
    sha='a'*64
    conn.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?)',(sha,'book',sha,2,'unverified','','now'))
    conn.executemany('INSERT INTO pages(document_id,physical_page,raw_text,search_text,warning,extraction_method) VALUES(?,?,?,?,?,?)',[(sha,1,'原文桂枝','原文桂枝', '', ''),(sha,2,'','', '', '')])
    pages=tmp_path/'ocr.json'; pages.write_text(json.dumps([{'physical_page':1,'text':'识别麻黄'},{'physical_page':2,'text':'识别麻黄'}]),encoding='utf8')
    manifest=tmp_path/'manifest.json'; manifest.write_text(json.dumps({'documents':[{'source_sha256':sha,'ocr_pages_json_path':str(pages)},{}]}),encoding='utf8')
    assert library.import_ocr(conn,manifest)=={'pages_imported':2,'documents_skipped':1}
    assert conn.execute('SELECT raw_text FROM pages WHERE physical_page=1').fetchone()[0]=='原文桂枝'
    assert [x['unit_no'] for x in library.search(conn,'麻黄')]==[2]
    assert library.get_unit(conn,tmp_path,sha,2)['ocr_text']=='识别麻黄'


def test_context_limits_each_source(tmp_path):
    conn=sqlite3.connect(':memory:'); library.initialize(conn,tmp_path)
    for sha in ('a'*64,'b'*64):
        conn.execute('INSERT INTO text_sources VALUES (?,?,?,?,?)',(sha,sha,'txt',4,'utf8'))
        conn.execute('INSERT INTO source_catalog VALUES (?,?)',(sha,'reference'))
        for n in range(1,5):
            conn.execute('INSERT INTO source_units(source_id,unit_no,locator,raw_text,search_text) VALUES (?,?,?,?,?)',(sha,n,json.dumps({'kind':'line_range','start':n,'end':n}),'桂枝汤','桂枝汤'))
    evidence=library.retrieve_context(conn,['桂枝'],max_items=6)
    assert len(evidence)==6
    assert {e['source_id'] for e in evidence}=={'a'*64,'b'*64}


def test_pdf_printed_page_is_metadata_not_a_physical_locator(tmp_path):
    conn = sqlite3.connect(':memory:')
    library.initialize(conn, tmp_path)
    sha = 'e' * 64
    conn.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?)', (sha, '合成分册', sha, 3, 'unverified', '', 'now'))
    conn.executemany('''INSERT INTO pages(document_id,physical_page,raw_text,search_text,warning,extraction_method,printed_page)
        VALUES(?,?,?,?,?,?,?)''', [(sha, 2, '合成检索甲', '合成检索甲', '', 'synthetic', None),
                                 (sha, 3, '合成检索乙', '合成检索乙', '', 'synthetic', '150')])
    locator = {'kind': 'physical_page', 'start': 3, 'end': 3, 'printed_page': '150'}
    unit = library.get_unit(conn, tmp_path, sha, 3)
    assert unit['locator'] == locator
    assert unit['unit_no'] == 3 and unit['image_url'].endswith('/pages/3/image')
    assert library.get_unit(conn, tmp_path, sha, 2)['locator'] == {'kind': 'physical_page', 'start': 2, 'end': 2}
    hits = library.search(conn, '合成检索')
    hit = next(item for item in hits if item['unit_no'] == 3)
    assert hit['physical_page'] == 3 and hit['printed_page'] == '150'
    assert hit['locator'] == locator
    assert hit['preview_url'].endswith('/units/3')
    evidence = library.retrieve_context(conn, ['合成检索乙'])
    assert evidence[0]['locator'] == locator and evidence[0]['unit_no'] == 3
    assert conn.execute('SELECT raw_text FROM pages WHERE physical_page=3').fetchone()[0] == '合成检索乙'


def test_migrated_search_index_and_real_original_snippet(tmp_path):
    conn = sqlite3.connect(':memory:')
    library.knowledge.init_knowledge(conn, tmp_path)
    conn.execute('CREATE TABLE text_sources(id TEXT PRIMARY KEY,title TEXT,format TEXT,total_units INTEGER,encoding TEXT)')
    conn.execute('CREATE TABLE source_units(source_id TEXT,unit_no INTEGER,locator TEXT,raw_text TEXT,PRIMARY KEY(source_id,unit_no))')
    sha = 'c'*64
    conn.execute('INSERT INTO text_sources VALUES (?,?,?,?,?)',(sha,'旧文本','txt',1,'utf8'))
    raw = '前文' * 1000 + '發熱，惡寒' + '后文' * 30
    conn.execute('INSERT INTO source_units VALUES (?,?,?,?)',(sha,1,json.dumps({'kind':'line_range','start':1,'end':42}),raw))
    library.initialize(conn,tmp_path)
    result = library.search(conn,'发热')[0]
    assert 'snippet' not in result
    assert result['locator']['end'] == 42
    evidence = library.retrieve_context(conn,['发热'])
    assert evidence[0]['text'] in raw and evidence[0]['warning']
    assert evidence[0]['extraction_method'] == '本地文本提取'


def test_search_snippet_keeps_complete_paragraph_context():
    paragraphs = [f'第{i}段' + ('上下文' * 25) + '。' for i in range(8)]
    paragraphs[3] = '桂枝汤主之，脉浮紧，发热无汗。' + ('完整证候' * 20) + '。'
    text = '\n\n'.join(paragraphs)
    snippet = library._snippet(text, '桂枝汤')
    assert paragraphs[3] in snippet
    assert len(snippet) > 600
    assert all(part in paragraphs for part in snippet.split('\n\n'))


def test_search_snippet_uses_sentence_boundaries_for_long_pages():
    target = '目标句：桂枝汤主之；脉浮紧。'
    text = ('开头前文。' + '甲' * 700 + '。' + target
            + '后续第一句完整。' + '乙' * 700 + '。结尾句。')
    snippet = library._snippet(text, '桂枝汤')
    assert target in snippet
    assert len(snippet) <= library.SNIPPET_MAX_CHARS
    assert snippet.endswith('。') or snippet.endswith('…')


def test_search_snippet_crops_only_an_oversized_sentence():
    text = '甲' * 1000 + '桂枝汤' + '乙' * 1000
    snippet = library._snippet(text, '桂枝汤')
    assert '桂枝汤' in snippet
    assert len(snippet) <= library.SNIPPET_MAX_CHARS


def test_ocr_context_and_corrected_text_precedence(tmp_path):
    conn=sqlite3.connect(':memory:'); library.initialize(conn,tmp_path)
    sha='d'*64
    conn.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?)',(sha,'扫描',sha,1,'unverified','', 'now'))
    conn.execute('INSERT INTO pages(document_id,physical_page,raw_text,search_text,warning,extraction_method) VALUES(?,?,?,?,?,?)',(sha,1,'','', '', 'native'))
    pages=tmp_path/'ocr.json'; pages.write_text(json.dumps([{'physical_page':1,'text':'發熱怕冷'}]),encoding='utf8')
    manifest=tmp_path/'m.json'; manifest.write_text(json.dumps({'documents':[{'source_sha256':sha,'ocr_pages_json_path':str(pages)}]}),encoding='utf8')
    library.import_ocr(conn,manifest)
    evidence=library.retrieve_context(conn,['发热'])
    assert '發熱' in evidence[0]['text'] and 'OCR' in evidence[0]['warning']
    assert evidence[0]['extraction_method'] == '本地OCR识别草稿'
    conn.execute('UPDATE pages SET corrected_text=?,search_text=? WHERE document_id=?',('订正文','订正文',sha))
    assert library.search(conn,'发热') == []
    assert library.retrieve_context(conn,['订正文'])[0]['text'] == '订正文'


def test_markdown_original_lines_role_dedup_and_backup(tmp_path):
    from app.backup import create_backup, restore_backup
    original = tmp_path / 'source.md'
    content = '# 提纲\n发热\n\n桂枝\n'.encode('utf-8')
    original.write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()
    manifest = tmp_path / 'md.json'
    manifest.write_text(json.dumps({'documents':[{'hash':sha,'title':'开源提纲','source_format':'md',
        'corpus_role':'open_source_summary','preserved_original_path':str(original),
        'units':[{'kind':'line_range','start':n,'end':n,'text':line} for n,line in enumerate(content.decode().splitlines(),1)]}]}),encoding='utf8')
    data=tmp_path/'data'; data.mkdir()
    with sqlite3.connect(data/'clinical.sqlite3') as conn:
        library.initialize(conn,data)
        assert library.import_text_manifest(conn,data,manifest)['text_imported'] == 1
        assert library.import_text_manifest(conn,data,manifest)['text_duplicates'] == 1
        hit=library.search(conn,'发热')[0]
        assert hit['locator'] == {'kind':'line_range','start':1,'end':4}
        assert hit['corpus_role']=='open_source_summary' and '不等同' in hit['warning']
        assert '不作为系统指令' in library.get_unit(conn,data,sha,1)['warning']
        assert library.original_path(conn,data,sha).read_bytes()==content
    archive=create_backup(data,'test-password-long-enough')
    restore_backup(archive,'test-password-long-enough',tmp_path/'restored')
    assert (tmp_path/'restored'/'originals'/f'{sha}.md').read_bytes()==content
