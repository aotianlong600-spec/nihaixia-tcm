from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    from app.main import create_app

    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield client


def login(client):
    response = client.get("/api/session")
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def create_visit(client, headers, **overrides):
    patient = client.post("/api/patients", json={"code": "SIM-001"}, headers=headers).json()
    payload = {
        "patient_id": patient["id"], "chief_complaint": "合成算法测试",
        "facts": [{"key": "demo_cold", "state": "present", "verified": True},
                  {"key": "demo_sweat", "state": "absent", "verified": True},
                  {"key": "demo_thirst", "state": "absent", "verified": True}],
        "context": {"simulation": False},
    }
    payload.update(overrides)
    response = client.post("/api/visits", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def rule_payload(rule_id="draft-1"):
    return {"rule": {
        "id": rule_id, "version": 1, "title": "合成审核测试", "kind": "pattern",
        "synthetic": True,
        "scope": {"description": "仅合成工程测试"},
        "required": {"fact": "demo_cold"}, "support": [], "excluded": None,
        "evidence_ids": [], "formula": [], "actions": [], "description": "不是医学规则",
    }}


def test_local_session_csrf_and_origin_boundaries(client):
    assert client.get("/api/status").json()["mode"] == "personal"
    assert client.get("/api/patients").status_code == 401
    assert client.get("/api/session", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/session", headers={"Host": "evil.example"}).status_code == 400
    headers = login(client)
    assert client.post("/api/patients", json={"code": "x"}).status_code == 403
    assert client.post("/api/patients", json={"code": "x"}, headers={**headers, "Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/patients", json={"code": "x"}, headers=headers).status_code == 200


def test_visit_update_marks_analysis_stale_and_rejects_old_decision(client):
    headers = login(client)
    visit = create_visit(client, headers)
    response = client.post(f"/api/visits/{visit['id']}/analyze", json={"expected_revision": 1}, headers=headers)
    assert response.status_code == 200, response.text
    analysis = response.json()
    assert analysis["visit_revision"] == 1
    assert analysis["input_snapshot"]["facts"][0]["key"] == "demo_cold"
    updated = client.put(f"/api/visits/{visit['id']}", json={
        "expected_revision": 1, "chief_complaint": "更改后",
        "facts": [], "context": {"simulation": True}, "clinician": "测试审核者",
    }, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert client.post(f"/api/visits/{visit['id']}/analyze", json={"expected_revision": 1}, headers=headers).status_code == 409
    details = client.get(f"/api/visits/{visit['id']}").json()
    assert details["analyses"][0]["stale"] is True
    assert details["analyses"][0]["input_snapshot"]["facts"][0]["key"] == "demo_cold"
    assert client.post(f"/api/analyses/{analysis['id']}/decision", json={
        "decision": "adopt", "clinician": "测试审核者", "notes": "不得采用旧输入结果",
    }, headers=headers).status_code == 409


def test_followup_starts_empty_and_does_not_copy_previous_facts(client):
    headers = login(client)
    first = create_visit(client, headers)
    followup = client.post("/api/visits", json={
        "patient_id": first["patient_id"], "previous_visit_id": first["id"],
        "chief_complaint": "合成复诊", "facts": [], "context": {"simulation": True},
        "clinician": "测试审核者",
    }, headers=headers)
    assert followup.status_code == 200
    assert followup.json()["facts"] == []
    assert followup.json()["previous_visit_id"] == first["id"]
    timeline = client.get(f"/api/patients/{first['patient_id']}/timeline").json()["items"]
    assert len(timeline) == 2
    assert any(v["facts"] == [] for v in timeline)


def test_rules_activate_without_approval_and_preserve_old_drafts(client):
    headers = login(client)
    payload = rule_payload()
    created = client.post("/api/rules", json=payload, headers=headers)
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "published"
    draft = rule_payload("saved-draft")
    draft["rule"]["status"] = "draft"
    assert client.post("/api/rules", json=draft, headers=headers).json()["status"] == "draft"
    assert client.post("/api/rules/saved-draft/activate", headers=headers).json()["status"] == "published"
    paths = {route.path for route in client.app.routes}
    assert "/api/rules/{rule_id}/review" not in paths
    assert "/api/rules/{rule_id}/publish" not in paths
    placeholder = rule_payload("incomplete-rule")
    placeholder["rule"]["required"] = {"fact": "__clinical_rule_not_defined__"}
    assert client.post("/api/rules", json=placeholder, headers=headers).status_code == 409
    payload["rule"]["title"] = "覆盖已发布规则"
    assert client.post("/api/rules", json=payload, headers=headers).status_code == 409
    assert client.post("/api/rules/draft-1/withdraw", headers=headers).status_code == 200
    rules = client.get("/api/rules").json()["items"]
    assert next(r for r in rules if r["id"] == "draft-1")["status"] == "withdrawn"


def test_decision_is_separate_and_modified_formula_is_checked(client):
    headers = login(client)
    visit = create_visit(client, headers)
    analysis = client.post(f"/api/visits/{visit['id']}/analyze", json={"expected_revision": 1}, headers=headers).json()
    decision = client.post(f"/api/analyses/{analysis['id']}/decision", json={
        "decision": "modify",
        "final_formula": [{"name": "合成测试成分", "processing": "测试", "amount": "1.5", "unit": "g", "basis": "per_dose", "evidence_ids": []}],
    }, headers=headers)
    assert decision.status_code == 200, decision.text
    assert decision.json()["risk_check"]["status"] in ["incomplete", "risk"]
    details = client.get(f"/api/visits/{visit['id']}").json()
    assert len(details["decisions"]) == 1
    assert "final_formula" not in details["analyses"][0]["result"]


def test_blank_case_code_is_rejected_without_requiring_simulation_or_signature(client):
    headers = login(client)
    assert client.post("/api/patients", json={"code": "  "}, headers=headers).status_code == 422
    patient = client.post("/api/patients", json={"code": "SIM-002"}, headers=headers).json()
    payload = {"patient_id": patient["id"], "context": {"simulation": False}}
    created = client.post("/api/visits", json=payload, headers=headers)
    assert created.status_code == 200
    assert created.json()["clinician"] == ""
    existing = create_visit(client, headers, clinician="历史记录人")
    edited = client.put(f"/api/visits/{existing['id']}", json={"expected_revision": 1}, headers=headers)
    assert edited.status_code == 200
    assert edited.json()["clinician"] == "历史记录人"


def test_model_config_never_returns_key_and_external_explanation_requires_consent(client):
    headers = login(client)
    config = {"base_url": "https://api.example.com/v1", "model": "test-model",
              "api_key": "synthetic-secret-test-only", "enabled": True,
              "allow_external": False, "allow_evidence": False}
    response = client.put("/api/model/config", json=config, headers=headers)
    assert response.status_code == 200, response.text
    result = client.get("/api/model/config").json()
    assert result["has_key"] is True
    assert "synthetic-secret-test-only" not in str(result)
    assert "api_key" not in result
    visit = create_visit(client, headers)
    analysis = client.post(f"/api/visits/{visit['id']}/analyze", json={"expected_revision": 1}, headers=headers).json()
    assert client.post("/api/model/jobs", json={"purpose": "explain", "analysis_id": analysis["id"], "allow_send": True}, headers=headers).status_code == 403


def test_changed_source_context_invalidates_prior_rule_evidence_and_decision(client, tmp_path):
    import pypdfium2

    headers = login(client)
    pdf_path = tmp_path / "synthetic.pdf"
    with pypdfium2.PdfDocument.new() as pdf:
        pdf.new_page(200, 200)
        pdf.save(pdf_path)
    uploaded = client.post("/api/documents", files={"file": ("synthetic.pdf", pdf_path.read_bytes(), "application/pdf")}, headers=headers)
    assert uploaded.status_code == 200, uploaded.text
    document_id = uploaded.json()["id"]
    image = client.get(f"/api/documents/{document_id}/pages/1/image")
    assert image.status_code == 200
    assert image.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert client.get(f"/api/documents/{document_id}/pages/0/image").status_code == 404
    review_url = f"/api/documents/{document_id}/pages/1/review"
    original = "Synthetic statement. Original surrounding context."
    review = {"corrected_text": original, "kind": "synthetic", "printed_page": "1"}
    assert client.post(review_url, json=review, headers=headers).status_code == 200
    evidence = client.post("/api/evidence", json={"document_id": document_id, "physical_page": 1,
        "quote": "Synthetic statement.", "kind": "synthetic"}, headers=headers).json()
    payload = rule_payload("source-context-rule")
    payload["rule"].update(synthetic=False, evidence_ids=[evidence["id"]])
    bad_dose = rule_payload("bad-nested-evidence")
    bad_dose["rule"].update(synthetic=False, evidence_ids=[evidence["id"]], formula=[{
        "name": "合成剂量", "processing": "测试", "amount": "1", "unit": "g", "basis": "per_dose", "evidence_ids": ["nonexistent-dose-evidence"]}])
    assert client.post("/api/rules", json=bad_dose, headers=headers).status_code == 409
    assert client.post("/api/rules", json=payload, headers=headers).status_code == 200
    visit = create_visit(client, headers)
    analysis = client.post(f"/api/visits/{visit['id']}/analyze", json={"expected_revision": 1}, headers=headers).json()
    review["corrected_text"] = "Synthetic statement. Changed surrounding context that reverses interpretation."
    assert client.post(review_url, json=review, headers=headers).status_code == 200
    response = client.post(f"/api/analyses/{analysis['id']}/decision", json={"decision": "adopt", "clinician": "测试审核者", "notes": "旧证据不可继续采用"}, headers=headers)
    assert response.status_code == 409
    fresh = client.post(f"/api/visits/{visit['id']}/analyze", json={"expected_revision": 1}, headers=headers).json()
    assert any(item["rule_id"] == "source-context-rule" for item in fresh["result"]["publication_warnings"])
    assert analysis["evidence_snapshot"][0]["corrected_text"] == original


def test_invalid_fact_is_rejected_before_creating_visit(client):
    headers = login(client)
    patient = client.post("/api/patients", json={"code": "SIM-INVALID"}, headers=headers).json()
    response = client.post("/api/visits", json={"patient_id": patient["id"], "chief_complaint": "合成",
        "facts": [{"key": "x", "state": "present", "verified": True, "observed_at": "not-a-date"}],
        "context": {"simulation": True}, "clinician": "测试"}, headers=headers)
    assert response.status_code in [400, 422]
    assert client.get("/api/visits").json()["items"] == []


def test_nonexistent_nested_dose_evidence_blocks_rule_activation(client):
    headers = login(client)
    payload = rule_payload("bad-dose-evidence")
    payload["rule"].update(synthetic=False, evidence_ids=["missing-top"], formula=[{
        "name": "合成", "processing": "测试", "amount": "1", "unit": "g", "basis": "per_dose", "evidence_ids": ["missing-dose"]}])
    payload["rule"]["status"] = "draft"
    assert client.post("/api/rules", json=payload, headers=headers).status_code == 200
    assert client.post("/api/rules/bad-dose-evidence/activate", headers=headers).status_code == 409


def test_decision_and_visit_edit_have_one_atomic_order(client, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import app.main as main

    headers = login(client)
    visit = create_visit(client, headers)
    analysis = client.post(f"/api/visits/{visit['id']}/analyze", json={"expected_revision": 1}, headers=headers).json()
    entered, release = threading.Event(), threading.Event()
    check = main.check_formula

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return check(*args, **kwargs)

    monkeypatch.setattr(main, "check_formula", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        decision = pool.submit(client.post, f"/api/analyses/{analysis['id']}/decision", json={"decision": "adopt", "clinician": "测试", "notes": "并发"}, headers=headers)
        assert entered.wait(5)
        edit = pool.submit(client.put, f"/api/visits/{visit['id']}", json={"expected_revision": 1, "chief_complaint": "改变", "facts": [], "context": {"simulation": True}, "clinician": "测试"}, headers=headers)
        try:
            # A concurrent edit must wait for the checked decision transaction to finish.
            with pytest.raises(TimeoutError):
                edit.result(timeout=0.2)
        finally:
            release.set()
        assert decision.result(timeout=5).status_code == 200
        assert edit.result(timeout=5).status_code == 200


def test_model_does_not_send_analysis_with_withdrawn_rule(client):
    headers = login(client)
    visit = create_visit(client, headers)
    analysis = client.post(f"/api/visits/{visit['id']}/analyze", json={"expected_revision": 1}, headers=headers).json()
    assert client.post("/api/rules/synthetic-pattern-a-v1/withdraw", json={"reviewer": "测试", "note": "不再使用"}, headers=headers).status_code == 200
    assert client.put("/api/model/config", json={"base_url": "http://127.0.0.1:9/v1", "model": "synthetic", "enabled": True, "allow_external": True, "allow_evidence": False}, headers=headers).status_code == 200
    response = client.post("/api/model/jobs", json={"purpose": "explain", "analysis_id": analysis["id"], "allow_send": True}, headers=headers)
    assert response.status_code == 409
