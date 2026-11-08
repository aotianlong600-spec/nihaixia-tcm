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
