import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.model_oauth import CODEX_BASE
from app.secrets import write_secret


def _client(app, **kwargs):
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000), **kwargs)
    client.get('/api/session')
    return client


def test_profile_endpoints_require_a_session(tmp_path):
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1', client=('127.0.0.1',50000)) as client:
        assert client.get('/api/model/profiles').status_code == 401
        assert client.post('/api/model/profiles',json=_profile()).status_code == 401


def test_delete_reports_incomplete_key_cleanup_without_reactivating(tmp_path,monkeypatch):
    app=create_app(tmp_path)
    with _client(app) as client:
        headers=_csrf(client)
        profile=client.post('/api/model/profiles',json=_profile(),headers=headers).json()
        client.post(f"/api/model/profiles/{profile['id']}/select",headers=headers)
        store=app.state.model_profiles
        key_path=store.key_path(profile['id'])
        monkeypatch.setattr(store,'_discard',lambda path:False)
        response=client.delete(f"/api/model/profiles/{profile['id']}",headers=headers)
        assert response.status_code==200
        assert response.json()['key_cleanup_incomplete'] is True
        assert key_path.exists()
        assert client.get('/api/model/profiles').json()['active_id'] is None


@pytest.mark.parametrize('change',['endpoint','mode'])
def test_changing_credential_recipient_requires_an_explicit_key(tmp_path,change):
    app=create_app(tmp_path)
    with _client(app) as client:
        headers=_csrf(client)
        profile=client.post('/api/model/profiles',json=_profile(),headers=headers).json()
        if change=='mode':
            codex={**_profile(),'auth_mode':'codex','api_key':None}
            assert client.put(f"/api/model/profiles/{profile['id']}",json=codex,headers=headers).status_code==200
        target={**_profile(),'base_url':'https://another.example/v1','api_key':None}
        response=client.put(f"/api/model/profiles/{profile['id']}",json=target,headers=headers)
        assert response.status_code==409
        assert app.state.model_profiles.read_key(profile['id'])=='synthetic-key'


def test_key_rotation_surfaces_old_blob_cleanup_failure(tmp_path,monkeypatch):
    app=create_app(tmp_path)
    with _client(app) as client:
        headers=_csrf(client)
        profile=client.post('/api/model/profiles',json=_profile(),headers=headers).json()
        store=app.state.model_profiles;old=store.key_path(profile['id'])
        monkeypatch.setattr(store,'_discard',lambda path:False)
        result=client.put(f"/api/model/profiles/{profile['id']}",json=_profile(key='synthetic-rotated-key'),headers=headers).json()
        assert result['key_cleanup_incomplete'] is True and old.exists()
        assert store.read_key(profile['id'])=='synthetic-rotated-key'


def test_delete_also_cleans_old_unversioned_profile_key(tmp_path,monkeypatch):
    app=create_app(tmp_path)
    with _client(app) as client:
        headers=_csrf(client);store=app.state.model_profiles
        profile=client.post('/api/model/profiles',json=_profile(),headers=headers).json()
        original=store.key_path(profile['id'])
        fallback=tmp_path/'model-keys'/f"{profile['id']}.dpapi"
        fallback.write_bytes(original.read_bytes())
        registry=json.loads(store.path.read_text(encoding='utf-8'))
        registry['items'][0].pop('key_ref')
        store.path.write_text(json.dumps(registry),encoding='utf-8')
        discard=store._discard;monkeypatch.setattr(store,'_discard',lambda path:False)
        assert client.put(f"/api/model/profiles/{profile['id']}",json=_profile(key='synthetic-new-key'),headers=headers).status_code==200
        monkeypatch.setattr(store,'_discard',discard)
        assert client.delete(f"/api/model/profiles/{profile['id']}",headers=headers).status_code==200
        assert not fallback.exists()


def _csrf(client):
    return {"X-CSRF-Token": client.get("/api/session").json()["csrf_token"]}


def _profile(name="合成配置", key="synthetic-key", base_url="https://api.example.com/v1"):
    return {"name": name, "auth_mode": "api_key", "base_url": base_url, "model": "synthetic-model",
            "enabled": True, "allow_external": False, "allow_evidence": False, "api_key": key}


def test_thinking_effort_round_trip_and_old_registry_default(tmp_path):
    app = create_app(tmp_path)
    with _client(app) as client:
        headers = _csrf(client)
        first = client.post('/api/model/profiles', json={**_profile('甲'), 'reasoning_effort': 'high'}, headers=headers)
        assert first.status_code == 200
        first = first.json()
        second = client.post('/api/model/profiles', json={**_profile('乙'), 'reasoning_effort': 'low'}, headers=headers).json()
        for profile, effort in [(first, 'high'), (second, 'low')]:
            assert client.post(f"/api/model/profiles/{profile['id']}/select", headers=headers).json()['reasoning_effort'] == effort
        path = tmp_path / 'model-profiles.json'
        registry = json.loads(path.read_text(encoding='utf-8'))
        for item in registry['items']:
            item.pop('reasoning_effort')
        path.write_text(json.dumps(registry), encoding='utf-8')
        before = path.read_bytes()
        assert client.get('/api/model/config').json()['reasoning_effort'] == 'auto'
        assert path.read_bytes() == before  # Reading an old registry must not rewrite user settings.
        assert client.post('/api/model/profiles', json={**_profile(), 'reasoning_effort':'invented'}, headers=headers).status_code == 422
        registry['items'][0]['reasoning_effort'] = None
        path.write_text(json.dumps(registry), encoding='utf-8')
        assert client.get('/api/model/profiles').status_code == 400


def test_consultation_selection_must_still_match_before_credentials_are_read(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    with _client(app) as client:
        headers = _csrf(client)
        profile = client.post('/api/model/profiles', json=_profile(), headers=headers).json()
        selected = client.post(f"/api/model/profiles/{profile['id']}/select", headers=headers).json()
        revision = selected['profile_revision']
        monkeypatch.setattr(app.state.model_profiles, 'read_key', lambda *args: pytest.fail('Stale UI must not retrieve a credential'))
        assert client.put(f"/api/model/profiles/{profile['id']}", json={**_profile(), 'reasoning_effort':'high'}, headers=headers).status_code == 200
        stale = {'purpose':'test', 'expected_profile_id':profile['id'], 'expected_profile_revision':revision}
        response = client.post('/api/model/jobs', json=stale, headers=headers)
        assert response.status_code == 409
        assert '配置已更改' in response.json()['detail']
        current = client.get('/api/model/config').json()
        assert current['profile_revision'] > revision
        wrong = {**stale, 'expected_profile_id':'0'*32, 'expected_profile_revision':current['profile_revision']}
        assert client.post('/api/model/jobs', json=wrong, headers=headers).status_code == 409
        assert client.post('/api/model/jobs', json={**stale, 'expected_profile_revision':False}, headers=headers).status_code == 422


def test_quick_model_update_cannot_restore_stale_sending_consent(tmp_path):
    with _client(create_app(tmp_path)) as client:
        headers = _csrf(client)
        allowed = {**_profile(), 'allow_external':True, 'allow_evidence':True}
        profile = client.post('/api/model/profiles', json=allowed, headers=headers).json()
        selected = client.post(f"/api/model/profiles/{profile['id']}/select", headers=headers).json()
        endpoint = f"/api/model/profiles/{profile['id']}"
        assert client.put(endpoint, json=_profile(), headers=headers).status_code == 200
        stale = {**allowed, 'reasoning_effort':'high', 'expected_profile_revision':selected['profile_revision']}
        assert client.put(endpoint, json=stale, headers=headers).status_code == 409
        current = client.get('/api/model/config').json()
        assert current['allow_external'] is False and current['allow_evidence'] is False
        update = {**_profile(), 'reasoning_effort':'low', 'expected_profile_revision':current['profile_revision']}
        assert client.put(endpoint, json=update, headers=headers).status_code == 200
        assert client.get('/api/model/config').json()['reasoning_effort'] == 'low'


def test_lazy_migration_preserves_legacy_settings_and_key(tmp_path):
    app = create_app(tmp_path)
    write_secret(tmp_path / "model-secret.dpapi", "synthetic-legacy-key")
    (tmp_path / "model-config.json").write_text(json.dumps({
        "auth_mode": "api_key", "base_url": "https://legacy.example/v1", "model": "legacy-model",
        "enabled": True, "allow_external": False, "allow_evidence": True}), encoding="utf-8")
    assert not (tmp_path / "model-profiles.json").exists()
    with _client(app) as client:
        assert not (tmp_path / "model-profiles.json").exists()
        config = client.get("/api/model/config").json()
        assert config["profile_id"] == "legacy"
        assert config["profile_name"] == "原有配置"
        assert config["has_key"] is True
        assert config["model"] == "legacy-model"
        assert config["base_url"] == "https://legacy.example/v1"
        assert config["allow_evidence"] is True
        profiles = client.get("/api/model/profiles").json()
        assert profiles["active_id"] == "legacy"
        assert profiles["items"] == [{"id": "legacy", "name": "原有配置", "auth_mode": "api_key",
            "base_url": "https://legacy.example/v1", "model": "legacy-model", "enabled": True,
            "allow_external": False, "allow_evidence": True, "reasoning_effort": "auto", "has_key": True}]
        assert (tmp_path / "model-config.json").exists()


def test_malformed_legacy_flags_fail_closed(tmp_path):
    app = create_app(tmp_path)
    (tmp_path / "model-config.json").write_text(json.dumps({
        "auth_mode": "api_key", "base_url": "https://legacy.example/v1", "model": "legacy-model",
        "enabled": "false", "allow_external": "false", "allow_evidence": False}), encoding="utf-8")
    with _client(app) as client:
        assert client.get("/api/model/config").status_code == 400
        assert client.get("/api/model/profiles").status_code == 400
    assert not (tmp_path / "model-profiles.json").exists()


def test_creation_does_not_activate_and_keys_are_isolated(tmp_path):
    app = create_app(tmp_path)
    store = app.state.model_profiles
    with _client(app) as client:
        headers = _csrf(client)
        first = client.post("/api/model/profiles", json=_profile("甲", "synthetic-key-a"), headers=headers).json()
        second = client.post("/api/model/profiles", json=_profile("乙", "synthetic-key-b"), headers=headers).json()
        assert first["id"] != second["id"]
        assert first["has_key"] is True and second["has_key"] is True
        first_key, second_key = store.key_path(first["id"]), store.key_path(second["id"])
        assert first_key != second_key
        assert store.read_key(first["id"]) == "synthetic-key-a"
        assert store.read_key(second["id"]) == "synthetic-key-b"
        assert client.get("/api/model/profiles").json()["active_id"] is None
        assert client.get("/api/model/config").json()["profile_id"] is None
        assert client.post("/api/model/jobs", json={"purpose": "test"}, headers=headers).status_code == 409

        payload = _profile("甲改", "   ")
        updated = client.put(f"/api/model/profiles/{first['id']}", json=payload, headers=headers).json()
        assert updated["name"] == "甲改" and updated["has_key"] is True
        assert store.key_path(first["id"]) == first_key
        assert store.read_key(first["id"]) == "synthetic-key-a"


def test_select_delete_and_no_automatic_fallback(tmp_path):
    app = create_app(tmp_path)
    store = app.state.model_profiles
    with _client(app) as client:
        headers = _csrf(client)
        first = client.post("/api/model/profiles", json=_profile("甲"), headers=headers).json()
        second = client.post("/api/model/profiles", json=_profile("乙"), headers=headers).json()
        first_key, second_key = store.key_path(first["id"]), store.key_path(second["id"])
        selected = client.post(f"/api/model/profiles/{first['id']}/select", headers=headers).json()
        assert selected["profile_id"] == first["id"]
        assert selected["profile_name"] == "甲"
        assert client.delete(f"/api/model/profiles/{second['id']}", headers=headers).json() == {
            "deleted_id": second["id"], "active_id": first["id"]}
        assert not second_key.exists()
        assert client.delete(f"/api/model/profiles/{first['id']}", headers=headers).json() == {
            "deleted_id": first["id"], "active_id": None}
        assert not first_key.exists()
        config = client.get("/api/model/config").json()
        assert config["profile_id"] is None and config["profile_name"] is None
        assert client.post("/api/model/jobs", json={"purpose": "test"}, headers=headers).status_code == 409
        assert client.post(f"/api/model/profiles/{second['id']}/select", headers=headers).status_code == 404


def test_codex_profiles_share_fixed_endpoint_and_single_account(tmp_path):
    with _client(create_app(tmp_path)) as client:
        headers = _csrf(client)
        payload = _profile("Codex甲")
        payload.update(auth_mode="codex", base_url="https://evil.example/v1", api_key=None)
        created = client.post("/api/model/profiles", json=payload, headers=headers).json()
        assert created["auth_mode"] == "codex" and created["base_url"] == CODEX_BASE
        assert created["has_key"] is False
        with_key = _profile("Codex乙")
        with_key.update(auth_mode="codex", base_url="", api_key="synthetic-rejected")
        assert client.post("/api/model/profiles", json=with_key, headers=headers).status_code == 400


@pytest.mark.parametrize("bad_id", ["not-a-uuid", "0" * 31, "g" * 32, "..%2Fmodel-profiles.json",
                                    "A" * 32, "12345678-1234-1234-1234-123456789abc"])
def test_invalid_profile_ids_are_rejected(tmp_path, bad_id):
    with _client(create_app(tmp_path)) as client:
        headers = _csrf(client)
        created = client.post("/api/model/profiles", json=_profile(), headers=headers).json()
        before=(tmp_path/'model-profiles.json').read_bytes()
        rejected={400,404,405} if '%2f' in bad_id.lower() else {400,404}
        assert client.post(f"/api/model/profiles/{bad_id}/select", headers=headers).status_code in rejected
        assert client.put(f"/api/model/profiles/{bad_id}", json=_profile(), headers=headers).status_code in rejected
        assert client.delete(f"/api/model/profiles/{bad_id}", headers=headers).status_code in rejected
        assert (tmp_path/'model-profiles.json').read_bytes()==before
        assert (tmp_path / "model-profiles.json").exists()
        assert client.get(f"/api/model/profiles/{created['id']}").status_code in {404, 405}


def _registry_item(**overrides):
    item = {"id": "a" * 32, "name": "合成", "auth_mode": "api_key", "base_url": "https://api.example.com/v1",
            "model": "synthetic-model", "enabled": False, "allow_external": False, "allow_evidence": False}
    item.update(overrides)
    return item


@pytest.mark.parametrize("document", ["{not-json",
                                      json.dumps({"version": 2, "revision": 1, "active_id": None, "items": []}),
                                      json.dumps({"version": True, "revision": 1, "active_id": None, "items": []}),
                                      json.dumps({"version": 1, "revision": "x", "active_id": None, "items": []}),
                                      json.dumps({"version": 1, "revision": 1, "active_id": None,
                                                  "items": [_registry_item(base_url="https://user:pass@example.com/v1")]}),
                                      json.dumps({"version": 1, "revision": 1, "active_id": None,
                                                  "items": [_registry_item(enabled="false")]}),
                                      json.dumps({"version": 1, "revision": 1, "active_id": None,
                                                  "items": [_registry_item(key_ref="../escape")]})])
def test_corrupt_registry_fails_closed(tmp_path, document):
    (tmp_path / "model-profiles.json").write_text(document, encoding="utf-8")
    with _client(create_app(tmp_path)) as client:
        assert client.get("/api/model/profiles").status_code == 400
        assert client.get("/api/model/config").status_code == 400


def test_registry_change_while_building_request_returns_409(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    with _client(app) as client:
        headers = _csrf(client)
        first = client.post("/api/model/profiles", json=_profile("甲"), headers=headers).json()
        second = client.post("/api/model/profiles", json=_profile("乙"), headers=headers).json()
        client.post(f"/api/model/profiles/{first['id']}/select", headers=headers)
        store = app.state.model_profiles
        original = store.snapshot
        calls = []

        def racing_snapshot():
            value = original()
            if not calls:
                calls.append(True)
                store.select(second["id"])
            return value

        monkeypatch.setattr(store, "snapshot", racing_snapshot)
        response = client.post("/api/model/jobs", json={"purpose": "test"}, headers=headers)
        assert response.status_code == 409


def test_key_rotation_registry_failure_keeps_old_configuration(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    store = app.state.model_profiles
    with _client(app, raise_server_exceptions=False) as client:
        headers = _csrf(client)
        profile = client.post("/api/model/profiles", json=_profile("甲", "synthetic-key-old"), headers=headers).json()
        client.post(f"/api/model/profiles/{profile['id']}/select", headers=headers)
        old_key_path = store.key_path(profile["id"])
        assert store.read_key(profile["id"]) == "synthetic-key-old"
        old_blobs = {path.name for path in (tmp_path / "model-keys").iterdir()}
        original_write = store._write

        def failing_write(registry):
            raise OSError("synthetic disk full")

        monkeypatch.setattr(store, "_write", failing_write)
        response = client.put(f"/api/model/profiles/{profile['id']}",
                              json=_profile("甲", "synthetic-key-new", "https://new.example/v1"), headers=headers)
        assert response.status_code >= 500
        monkeypatch.setattr(store, "_write", original_write)

        config = client.get("/api/model/config").json()
        assert config["base_url"] == "https://api.example.com/v1"
        assert store.key_path(profile["id"]) == old_key_path
        assert store.read_key(profile["id"]) == "synthetic-key-old"
        assert {path.name for path in (tmp_path / "model-keys").iterdir()} == old_blobs


def test_deleting_active_profile_cancels_its_running_job(tmp_path):
    started, release = threading.Event(), threading.Event()

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            event = {"id": "test", "object": "chat.completion.chunk",
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Connection works."}, "finish_reason": None}]}
            try:
                self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return
            started.set()
            release.wait(10)
            self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with _client(create_app(tmp_path)) as client:
            headers = _csrf(client)
            payload = _profile(base_url=f"http://127.0.0.1:{server.server_port}/v1")
            profile = client.post("/api/model/profiles", json=payload, headers=headers).json()
            client.post(f"/api/model/profiles/{profile['id']}/select", headers=headers)
            job = client.post("/api/model/jobs", json={"purpose": "test"}, headers=headers).json()
            assert started.wait(10)
            assert client.delete(f"/api/model/profiles/{profile['id']}", headers=headers).status_code == 200
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                result = client.get(f"/api/model/jobs/{job['id']}").json()
                if result["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.05)
            assert result["status"] == "cancelled"
    finally:
        release.set()
        server.shutdown()
        server.server_close()
