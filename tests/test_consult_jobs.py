import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("scenario", ["follow_up", "assessment", "bad_reference", "interrupted", "cancel", "stale"])
def test_personal_ai_request_end_to_end(tmp_path, scenario):
    from app.main import create_app

    entered, release = threading.Event(), threading.Event()
    captured = []
    result = {"stage": "follow_up", "summary": "合成协议返回，不是治疗建议", "questions": [{"key": "sweat", "question": "是否出汗？", "reason": "对照来源"}],
              "syndromes": [], "formulas": [], "risks": [], "limitations": [], "evidence_ids": []}
    if scenario == "assessment":
        result.update(stage="assessment", questions=[], evidence_ids=["formula:guizhi_tang"], formulas=[{
            "formula_id": "guizhi_tang", "name": "桂枝汤", "reason": "仅测试已有来源药量回填", "components": [],
            "modifications": [], "preparation": None, "evidence_ids": ["formula:guizhi_tang"]}])
    if scenario == "bad_reference":
        result["evidence_ids"] = ["invented-source"]

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            captured.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            first = {"id": "synthetic", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)}, "finish_reason": None}]}
            try:
                self.wfile.write(("data: " + json.dumps(first) + "\n\n").encode())
                self.wfile.flush()
                entered.set()
                if scenario == "interrupted":
                    self.close_connection = True
                    return
                if scenario == "stale":
                    assert release.wait(12)
                final = {"id": "synthetic", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                self.wfile.write(("data: " + json.dumps(final) + "\n\ndata: [DONE]\n\n").encode())
                self.wfile.flush()
                self.close_connection = True
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    try:
        with TestClient(create_app(tmp_path), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            headers = {"X-CSRF-Token": client.get("/api/session").json()["csrf_token"]}
            response = client.put("/api/model/config", json={"base_url": f"http://127.0.0.1:{provider.server_port}/v1", "model": "synthetic",
                "api_key": "fake-protocol-key", "enabled": True, "allow_external": True, "allow_evidence": True}, headers=headers)
            assert response.status_code == 200
            case = client.post("/api/consultations", json={}, headers=headers).json()
            assert client.post(f"/api/consultations/{case['id']}/messages", json={"text": "合成协议输入：查桂枝汤原文"}, headers=headers).status_code == 200
            response = client.post("/api/model/jobs", json={"purpose": "consult", "consultation_id": case["id"], "allow_send": True}, headers=headers)
            assert response.status_code == 200, response.text
            job_id = response.json()["id"]
            if scenario == "cancel":
                client.post(f"/api/model/jobs/{job_id}/cancel", json={}, headers=headers)
            if scenario == "stale":
                assert entered.wait(12)
                assert client.put(f"/api/consultations/{case['id']}", json={"expected_revision": 2, "intake": {"chief_complaint": "changed input"}}, headers=headers).status_code == 200
                release.set()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                job = client.get(f"/api/model/jobs/{job_id}").json()
                if job["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.05)
            expected = "cancelled" if scenario == "cancel" else "failed" if scenario in {"bad_reference", "interrupted"} else "completed"
            assert job["status"] == expected, job
            assert "fake-protocol-key" not in json.dumps(job)
            record = client.get(f"/api/consultations/{case['id']}").json()
            if expected == "completed":
                assert len(record["messages"]) == 2
                assert record["messages"][1]["role"] == "assistant"
                assert record["messages"][1]["result"]["summary"] == result["summary"]
                assert record["messages"][1]["evidence"]
                assert job["validated"] is (scenario != "stale")
                assert record["messages"][1]["stale"] is (scenario == "stale")
                if scenario == "assessment":
                    assert next(c for c in record["messages"][1]["result"]["formulas"][0]["components"] if c["name"] == "桂枝")["source_dose"] == "三两"
            else:
                assert len(record["messages"]) == 1
                assert job["text"] == ""
        if expected == "completed":
            with TestClient(create_app(tmp_path), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as restarted:
                restarted.get("/api/session")
                saved_job = restarted.get(f"/api/model/jobs/{job_id}")
                assert saved_job.status_code == 200
                assert saved_job.json()["result"]["summary"] == result["summary"]
                assert saved_job.json()["stale"] is (scenario == "stale")
        assert all(str(tmp_path) not in body and case["id"] not in body for body in captured)
    finally:
        release.set()
        provider.shutdown()
        provider.server_close()
