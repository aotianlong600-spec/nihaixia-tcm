from app import browser_excerpts, library, storage


def test_bundled_excerpts_are_readable_without_installing_private_originals(tmp_path):
    storage.initialize(tmp_path)
    with storage.connect(tmp_path) as conn:
        library.initialize(conn, tmp_path)
        sources = browser_excerpts.list_sources(conn)
        assert len(sources) == 16
        assert all(source['format'] == 'excerpt' for source in sources)
        result = browser_excerpts.search(conn, '桂枝汤', limit=5)
        assert result
        first = result[0]
        unit = browser_excerpts.get_unit(conn, tmp_path, first['source_id'], first['unit_no'])
        assert unit['content_scope'] == 'extracted_quotes'
        assert unit['fragments'] and '桂枝汤' in unit['raw_text']
        assert unit['original_url'] is None
        assert unit['locator']['kind']


def test_bundled_excerpts_keep_source_filter_and_original_unit_identity(tmp_path):
    storage.initialize(tmp_path)
    with storage.connect(tmp_path) as conn:
        library.initialize(conn, tmp_path)
        rows = browser_excerpts.search(conn, '柴胡', limit=10)
        assert rows
        selected = rows[0]['source_id']
        filtered = browser_excerpts.search(conn, '柴胡', selected, 10)
        assert filtered and all(row['source_id'] == selected for row in filtered)
        assert all(type(row['unit_no']) is int and row['unit_no'] > 0 for row in filtered)


def test_excerpt_search_preview_is_centered_on_the_match(tmp_path):
    storage.initialize(tmp_path)
    with storage.connect(tmp_path) as conn:
        library.initialize(conn, tmp_path)
        rows = browser_excerpts.search(conn, '桂枝汤', limit=30)
        excerpts = [row for row in rows if row['format'] == 'excerpt']
        assert excerpts
        assert all('桂枝汤' in row['snippet'] for row in excerpts)


def test_contained_excerpt_fragments_are_merged_without_duplicate_text(tmp_path):
    storage.initialize(tmp_path)
    with storage.connect(tmp_path) as conn:
        library.initialize(conn, tmp_path)
        rows = browser_excerpts.search(conn, '太阳中暍', limit=30)
        assert rows
        unit = browser_excerpts.get_unit(conn, tmp_path, rows[0]['source_id'], rows[0]['unit_no'])
        texts = [fragment['text'] for fragment in unit['fragments']]
        assert texts
        assert len(texts) == len(set(texts))
        assert not any(first in second for index, first in enumerate(texts)
                       for other, second in enumerate(texts) if index != other)


def test_modification_rule_excerpts_are_searchable(tmp_path):
    storage.initialize(tmp_path)
    with storage.connect(tmp_path) as conn:
        library.initialize(conn, tmp_path)
        rows = browser_excerpts.search(conn, '去半夏', limit=30)
        excerpts = [row for row in rows if row['format'] == 'excerpt']
        assert excerpts
        assert all('去半夏' in row['snippet'] for row in excerpts)
