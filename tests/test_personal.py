import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def personal_client(tmp_path):
    from app.main import create_app
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        csrf = {"X-CSRF-Token": client.get("/api/session").json()["csrf_token"]}
        yield client, csrf


def test_personal_intake_and_messages_need_no_rule_approval_or_clinician(personal_client):
    client, csrf = personal_client
    created = client.post("/api/consultations", json={}, headers=csrf)
    assert created.status_code == 200
    case = created.json()
    assert case["revision"] == 1 and case["messages"] == []
    intake = {"chief_complaint": "合成问诊输入", "symptoms": ["头痛"], "age_years": None, "sex": "unknown"}
    saved = client.put(f"/api/consultations/{case['id']}", json={"expected_revision": 1, "intake": intake}, headers=csrf)
    assert saved.status_code == 200
    assert saved.json()["revision"] == 2
    assert client.put(f"/api/consultations/{case['id']}", json={"expected_revision": 1, "intake": {}}, headers=csrf).status_code == 409
    message = client.post(f"/api/consultations/{case['id']}/messages", json={"text": "想了解桂枝汤的条文"}, headers=csrf)
    assert message.status_code == 200
    restored = client.get(f"/api/consultations/{case['id']}").json()
    assert restored["messages"][0]["role"] == "user"
    assert restored["messages"][0]["text"] == "想了解桂枝汤的条文"
    assert restored["revision"] == 3
    context = client.get(f"/api/consultations/{case['id']}/context")
    assert context.status_code == 200
    assert any(f["name"].startswith("桂枝汤") for f in context.json()["formula_candidates"])
    job = client.post("/api/model/jobs", json={"purpose": "consult", "consultation_id": case["id"], "allow_send": True}, headers=csrf)
    assert job.status_code in (403, 409)
    assert len(client.get(f"/api/consultations/{case['id']}").json()["messages"]) == 1


def test_personal_library_and_formula_routes_expose_real_catalog(personal_client):
    client, csrf = personal_client
    overview = client.get("/api/personal/overview")
    assert overview.status_code == 200
    assert overview.json()["formula_count"] == 314
    formulas = client.get("/api/formulas", params={"q": "桂枝汤", "limit": 30}).json()["items"]
    selected = next(f for f in formulas if f["name"] == "桂枝汤")
    assert client.get(f"/api/formulas/{selected['id']}").json()["name"] == "桂枝汤"
    assert client.get("/api/library/sources").json() == {"items": []}
    assert client.post("/api/formulas/match", json={"facts": [], "query": "桂枝汤", "limit": 8}, headers=csrf).status_code == 200


def empty_result():
    return {"stage": "follow_up", "summary": "请补充当前信息", "questions": [{"key": "sweat", "question": "是否出汗？", "reason": "区分文献线索"}],
            "syndromes": [], "formulas": [], "risks": [], "limitations": [], "evidence_ids": []}


def test_consult_validation_rejects_invented_sources_and_preserves_original_dose():
    from app.personal import validate_consult_result
    from app.formula_engine import get_formula

    context = {"formula_candidates": [get_formula("guizhi_tang")], "evidence": [{"id": "source-1", "text": "合成来源"}]}
    payload = empty_result()
    assert validate_consult_result(json.dumps(payload), context)["stage"] == "follow_up"
    payload["evidence_ids"] = ["invented"]
    with pytest.raises(ValueError):
        validate_consult_result(json.dumps(payload), context)
    payload = empty_result()
    payload.update(stage="assessment", questions=[], evidence_ids=["source-1"], formulas=[{
        "formula_id": "guizhi_tang", "name": "桂枝汤", "reason": "合成协议测试非治疗建议", "components": [{"name": "桂枝", "processing": None, "source_dose": "999克", "source_unit": "g", "source_ref": "source-1"}],
        "modifications": [], "preparation": None, "evidence_ids": ["source-1"]}])
    result = validate_consult_result(json.dumps(payload), context)
    assert next(c for c in result["formulas"][0]["components"] if c["name"] == "桂枝")["source_dose"] == "三两"
    assert any("文献原量" in text for text in result["limitations"])
    payload["formulas"][0]["formula_id"] = "not-in-this-context"
    with pytest.raises(ValueError):
        validate_consult_result(json.dumps(payload), context)


def test_latest_user_message_is_not_silently_cut_before_important_tail(personal_client):
    from app import personal, storage
    from contextlib import closing

    client, csrf = personal_client
    case = client.post("/api/consultations", json={}, headers=csrf).json()
    text = "甲" * 9000 + "过敏信息测试尾标记"
    assert client.post(f"/api/consultations/{case['id']}/messages", json={"text": text}, headers=csrf).status_code == 200
    with closing(storage.connect(client.app.state.data_dir)) as conn:
        context, request, system = personal.prepare_task(conn, case["id"])
    assert json.loads(request)["对话"][-1]["content"].endswith("过敏信息测试尾标记")


def test_colloquial_words_expand_retrieval_without_inventing_patient_findings():
    from app.personal import retrieval_queries, facts_from_intake

    intake = {"chief_complaint": "怕冷，没汗，肚子胀", "symptoms": [], "facts": []}
    queries = retrieval_queries(intake, [])
    assert "恶寒" in queries and "畏寒" in queries and "无汗" in queries and "腹胀" in queries
    assert facts_from_intake(intake) == []
