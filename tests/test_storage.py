from concurrent.futures import ThreadPoolExecutor


def test_request_connection_survives_asgi_worker_handoff(tmp_path):
    from app.storage import connect, initialize

    initialize(tmp_path)
    conn = connect(tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(lambda: conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]).result() == 0
    finally:
        conn.close()
