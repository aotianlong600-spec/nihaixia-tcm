import pytest


def test_dpapi_keeps_secret_off_disk_and_round_trips(tmp_path):
    from app.secrets import read_secret, write_secret

    target = tmp_path / "model-secret.dpapi"
    write_secret(target, "synthetic-never-real-key")
    assert b"synthetic-never-real-key" not in target.read_bytes()
    assert read_secret(target) == "synthetic-never-real-key"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://example.com/v1", "https://user:secret@example.com/v1", "https://example.com/v1?key=secret", "http://127.0.0.2/v1"])
def test_provider_url_rejects_unsafe_or_ambiguous_destinations(url):
    from app.model import validate_url

    with pytest.raises(ValueError):
        validate_url(url)


def test_provider_url_accepts_explicit_https_and_loopback_only_http():
    from app.model import validate_url

    assert validate_url("https://api.example.com/v1/") == "https://api.example.com/v1"
    assert validate_url("http://127.0.0.1:19999/v1") == "http://127.0.0.1:19999/v1"


def test_model_payload_omits_identity_raw_chief_complaint_and_unapproved_evidence():
    from app.model import explain_payload

    analysis = {"input_snapshot": {"patient_id": "secret-id", "chief_complaint": "private-chief",
                "facts": [{"key": "sweating", "state": "present", "verified": True, "scope": "current", "raw": "private raw text", "source": "patient"}]},
                "result": {"candidates": [{"rule_id": "r1", "title": "candidate"}], "urgent": False},
                "evidence_snapshot": [{"id": "e1", "quote": "copyrighted-original"}]}
    payload = explain_payload(analysis, False)
    assert "private" not in payload
    assert "secret-id" not in payload
    assert "copyrighted-original" not in payload
    assert "sweating" in payload
    assert "copyrighted-original" in explain_payload(analysis, True)


def test_bridge_error_messages_are_actionable_and_never_reflect_provider_values():
    from app.model import bridge_error_message

    assert "推理参数" in bridge_error_message({"status": 400, "provider_param": "reasoning.effort"})
    assert "重新登录" in bridge_error_message({"status": 401})
    assert "模型ID" in bridge_error_message({"status": 404})
    assert "额度" in bridge_error_message({"status": 429})
    assert "10分钟" in bridge_error_message({"status": 429, "retry_after": 600})
    assert "10分钟" not in bridge_error_message({"status": 429, "retry_after": 999999})
    assert "HTTP 503" in bridge_error_message({"status": 503})
    assert "未完成" in bridge_error_message({})
    assert "private-provider-value" not in bridge_error_message(
        {"status": 400, "provider_param": "private-provider-value", "provider_code": "private-provider-value"})


def test_model_output_rejects_unknown_citation_and_malformed_json():
    from app.model import validate_explanation

    assert validate_explanation('{"summary":"合成解释","questions":[],"evidence_ids":["e1"]}', {"e1"})["summary"] == "合成解释"
    for text in ['not-json', '{"summary":"x","questions":[],"evidence_ids":["made-up"]}', '{"summary":"x","questions":"bad","evidence_ids":[]}']:
        with pytest.raises(ValueError):
            validate_explanation(text, {"e1"})


@pytest.mark.parametrize("scenario", ["complete", "interrupted", "cancel", "bad_citation", "cancel_during_validation", "stale_during_stream"])
def test_python_jobs_require_complete_valid_response_and_honor_cancel(tmp_path, scenario, monkeypatch):
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import sqlite3
    import threading
    import time
    from fastapi.testclient import TestClient
    from app.main import create_app

    captured = []
    validating, release = threading.Event(), threading.Event()
    if scenario == "cancel_during_validation":
        import app.model as model
        validate = model.validate_explanation

        def paused_validation(text, ids):
            result = validate(text, ids)
            validating.set()
            assert release.wait(5)
            return result

        monkeypatch.setattr(model, "validate_explanation", paused_validation)

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            captured.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            answer = '{"summary":"synthetic","questions":[],"evidence_ids":["invented"]}' if scenario == "bad_citation" else '{"summary":"synthetic","questions":[],"evidence_ids":[]}' if scenario in {"cancel_during_validation", "stale_during_stream"} else "Connection works."
            events = [{"id": "test", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"role": "assistant", "content": answer}, "finish_reason": None}]}]
            try:
                self.wfile.write(("data: " + json.dumps(events[0]) + "\n\n").encode())
                self.wfile.flush()
                if scenario == "interrupted":
                    self.close_connection = True
                    return
                if scenario == "cancel":
                    time.sleep(1)
                if scenario == "stale_during_stream":
                    validating.set()
                    assert release.wait(5)
                end = {"id": "test", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                self.wfile.write(("data: " + json.dumps(end) + "\n\ndata: [DONE]\n\n").encode())
                self.wfile.flush()
                self.close_connection = True
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TestClient(create_app(tmp_path), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            csrf = {"X-CSRF-Token": client.get("/api/session").json()["csrf_token"]}
            config = {"base_url": f"http://127.0.0.1:{server.server_port}/v1", "model": "synthetic",
                      "api_key": "fake-protocol-key", "reasoning_effort": "high", "enabled": True, "allow_external": scenario in {"bad_citation", "cancel_during_validation", "stale_during_stream"}, "allow_evidence": False}
            assert client.put("/api/model/config", json=config, headers=csrf).status_code == 200
            request = {"purpose": "test"}
            if scenario == "complete":
                active = client.get('/api/model/config').json()
                request.update(expected_profile_id=active['profile_id'], expected_profile_revision=active['profile_revision'])
            if scenario in {"bad_citation", "cancel_during_validation", "stale_during_stream"}:
                patient = client.post("/api/patients", json={"code": "PRIVATE-CODE"}, headers=csrf).json()
                visit = client.post("/api/visits", json={"patient_id": patient["id"], "chief_complaint": "PRIVATE-CHIEF", "facts": [], "context": {"simulation": True}, "clinician": "PRIVATE-CLINICIAN"}, headers=csrf).json()
                analysis = client.post(f"/api/visits/{visit['id']}/analyze", json={"expected_revision": 1}, headers=csrf).json()
                request = {"purpose": "explain", "analysis_id": analysis["id"], "allow_send": True}
            response = client.post("/api/model/jobs", json=request, headers=csrf)
            assert response.status_code == 200, response.text
            job_id = response.json()["id"]
            assert response.json()["reasoning_effort"] == "high"
            if scenario == "complete":
                assert client.put("/api/model/config", json={**config, "api_key": None, "reasoning_effort": "low"}, headers=csrf).status_code == 200
            if scenario == "cancel_during_validation":
                assert validating.wait(5)
            if scenario == "stale_during_stream":
                assert validating.wait(5)
                assert client.put(f"/api/visits/{visit['id']}", json={"expected_revision": 1, "chief_complaint": "changed", "facts": [], "context": {"simulation": True}, "clinician": "测试"}, headers=csrf).status_code == 200
                release.set()
            if scenario in {"cancel", "cancel_during_validation"}:
                assert client.post(f"/api/model/jobs/{job_id}/cancel", json={}, headers=csrf).status_code == 200
                release.set()
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                result = client.get(f"/api/model/jobs/{job_id}").json()
                if result["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.05)
            expected = "completed" if scenario in {"complete", "stale_during_stream"} else "cancelled" if scenario in {"cancel", "cancel_during_validation"} else "failed"
            assert result["status"] == expected, result
            assert result["validated"] is (scenario == "complete")
            assert "fake-protocol-key" not in json.dumps(result)
            with sqlite3.connect(tmp_path / "clinical.sqlite3") as conn:
                assert conn.execute("SELECT COUNT(*) FROM model_calls WHERE status='completed'").fetchone()[0] == (1 if scenario in {"complete", "stale_during_stream"} else 0)
            assert all("PRIVATE-" not in body for body in captured)
            if scenario != "cancel":
                assert captured
            assert all(json.loads(body)["reasoning_effort"] == "high" for body in captured)
        if scenario in {"complete", "stale_during_stream"}:
            with TestClient(create_app(tmp_path), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as restarted:
                restarted.get("/api/session")
                history = restarted.get(f"/api/model/jobs/{job_id}")
                assert history.status_code == 200
                assert history.json()["reasoning_effort"] == "high"
                assert history.json()["validated"] is (scenario == "complete")
                if scenario == "stale_during_stream":
                    assert history.json()["stale"] is True
    finally:
        release.set()
        server.shutdown()
        server.server_close()
