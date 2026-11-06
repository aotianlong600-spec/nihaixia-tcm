import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def personal_client(tmp_path):
    from app.main import create_app
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
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


def test_consult_validation_tolerates_unknown_keys_and_null_lists_from_model():
    from app.personal import validate_consult_result

    context = {"formula_candidates": [], "evidence": []}
    payload = empty_result()
    payload["confidence"] = 0.9
    payload["questions"] = None
    payload["syndromes"] = [{"name": "合成证候", "supporting_symptoms": None, "contradictions": None,
                             "missing_information": None, "evidence_ids": None, "unexpected": "ignored"}]
    payload["formulas"] = None
    payload["risks"] = None
    payload["limitations"] = None
    payload["evidence_ids"] = None
    result = validate_consult_result(json.dumps(payload), context)
    assert result["questions"] == [] and result["formulas"] == []
    assert result["syndromes"][0]["supporting_symptoms"] == [] and result["syndromes"][0]["evidence_ids"] == []
    assert "confidence" not in result and "unexpected" not in result["syndromes"][0]


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


def test_model_input_and_context_use_the_same_intake_revision(personal_client, monkeypatch):
    from app import personal, storage
    from contextlib import closing

    client, csrf = personal_client
    case = client.post("/api/consultations", json={"intake": {"chief_complaint": "旧输入"}}, headers=csrf).json()
    build = personal.build_context

    def update_between_reads(conn, key, *args):
        conn.execute("UPDATE consultations SET intake=?,revision=revision+1 WHERE id=?", (storage.encode({"chief_complaint": "新输入", "symptoms": [], "facts": []}), key))
        conn.commit()
        return build(conn, key, *args)

    monkeypatch.setattr(personal, "build_context", update_between_reads)
    with closing(storage.connect(client.app.state.data_dir)) as conn:
        frozen, request, system = personal.prepare_task(conn, case["id"])
        assert json.loads(request)["用户问诊单"] == frozen["intake_snapshot"]
        assert frozen["input_revision"] == 1
        assert personal.task_warnings(conn, frozen)


def test_book_formula_outside_seed_catalog_can_use_literal_source_but_not_invent_amounts():
    from app.personal import validate_consult_result

    context = {"formula_candidates": [], "evidence": [{"id": "book1", "text": "调和测试饮：测试甲三钱，测试乙二钱。"}]}
    payload = empty_result()
    payload.update(stage="assessment", questions=[], evidence_ids=["book1"], formulas=[{
        "formula_id": None, "name": "调和测试饮", "reason": "仅验证书证方案通路", "components": [
            {"name": "测试甲", "source_dose": "三钱", "source_ref": "book1"},
            {"name": "测试乙", "source_dose": "999克", "source_ref": "book1"}],
        "modifications": [], "preparation": None, "evidence_ids": ["book1"]}])
    result = validate_consult_result(json.dumps(payload), context)
    assert result["formulas"][0]["components"][0]["source_dose"] == "三钱"
    assert result["formulas"][0]["components"][1]["source_dose"] is None
    assert result["formulas"][0]["source_kind"] == "book_extraction"
    payload["formulas"][0]["name"] = "没有来源的幻方"
    with pytest.raises(ValueError):
        validate_consult_result(json.dumps(payload), context)


def test_named_formula_query_is_not_lost_inside_a_natural_question():
    from app.personal import retrieval_queries

    assert "滋水疏肝饮" in retrieval_queries({}, [{"role": "user", "text": "请帮我查一下滋水疏肝饮的组成是什么"}])
    assert "附子" in retrieval_queries({}, [{"role": "user", "text": "想了解附子的药性"}])


@pytest.mark.parametrize("source,dose,want", [
    ("测试甲3.5克，测试乙12克", "35克", None),
    ("测试甲3.5克，测试乙12克", "3.5克", "3.5克"),
    ("测试甲三钱，测试乙二钱", "二钱", None),
    ("测试甲、测试乙各三钱", "三钱", None),
])
def test_source_dose_never_loses_decimal_or_borrows_another_herb(source, dose, want):
    from app.personal import validate_consult_result

    context = {"formula_candidates": [], "evidence": [{"id": "book1", "text": "调和测试饮：" + source}]}
    payload = empty_result()
    payload.update(stage="assessment", questions=[], formulas=[{"formula_id": None, "name": "调和测试饮", "components": [
        {"name": "测试甲", "source_dose": dose}, {"name": "测试乙", "source_dose": None}], "evidence_ids": ["book1"]}])
    result = validate_consult_result(json.dumps(payload), context)
    assert result["formulas"][0]["components"][0]["source_dose"] == want


@pytest.mark.parametrize("source", [
    "调和测试饮：测试甲三钱。另方补气汤：测试乙12克。",
    "调和测试饮：测试甲三钱，另方补气汤：测试乙12克。",
    "补气汤：测试乙12克。调和测试饮：测试甲三钱。",
    "加味调和测试饮：测试乙12克。",
    "调和测试饮：测试甲三钱，补气汤由测试乙12克组成。",
    "调和测试饮：不含测试乙12克。",
])
def test_book_formula_cannot_borrow_components_from_another_formula(source):
    from app.personal import validate_consult_result

    context = {"formula_candidates": [], "evidence": [{"id": "book1", "text": source}]}
    payload = empty_result()
    payload.update(stage="assessment", questions=[], formulas=[{
        "formula_id": None, "name": "调和测试饮", "components": [
            {"name": "测试乙", "source_dose": "12克"}], "evidence_ids": ["book1"]}])
    result = validate_consult_result(json.dumps(payload), context)
    assert result["formulas"][0]["components"] == []
    assert result["formulas"][0]["source_kind"] == "book_reference"


def test_book_formula_does_not_assemble_multiple_source_versions():
    from app.personal import validate_consult_result

    context = {"formula_candidates": [], "evidence": [
        {"id": "book1", "text": "调和测试饮：测试甲三钱。"},
        {"id": "book2", "text": "调和测试饮：测试乙二钱。"}]}
    payload = empty_result()
    payload.update(stage="assessment", questions=[], formulas=[{
        "name": "调和测试饮", "components": [{"name": "测试甲"}, {"name": "测试乙"}], "evidence_ids": ["book1", "book2"]}])
    result = validate_consult_result(json.dumps(payload), context)
    assert result["formulas"][0]["components"] == []
    assert result["formulas"][0]["source_kind"] == "book_reference"


def test_book_formula_without_clear_composition_can_remain_a_reference_only():
    from app.personal import validate_consult_result

    context = {"formula_candidates": [], "evidence": [{"id": "book1", "text": "此处讨论调和测试饮的沿革，未列药物组成。"}]}
    payload = empty_result()
    payload.update(stage="assessment", questions=[], formulas=[{"name": "调和测试饮", "components": [], "evidence_ids": ["book1"]}])
    result = validate_consult_result(json.dumps(payload), context)
    assert result["formulas"][0]["components"] == []
    assert result["formulas"][0]["source_kind"] == "book_reference"
