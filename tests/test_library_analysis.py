import pytest
from fastapi.testclient import TestClient

from app import library_analysis


def test_cold_extremities_and_weak_pulse_rank_sini_tang_first():
    result = library_analysis.analyze(facts=[fact(term) for term in ("怕冷", "手脚冰凉", "脉微细")], limit=5)
    assert result["present"]
    assert result["present_labels"]
    assert result["items"]
    assert result["items"][0]["formula_id"] == "sini_tang"
    top = result["items"][0]
    assert top["matched_terms"]
    assert top["evidence"]
    assert "score_breakdown" in top
    assert "probability" not in top and "confidence" not in top
    assert "不是概率" in result["score_explanation"]


def test_shaoyang_case_ranks_xiaochaihu_first_and_exposes_modifications():
    result = library_analysis.analyze(facts=[fact(term) for term in ("往来寒热", "胸胁苦满", "心烦喜呕")], limit=5)
    assert result["items"]
    top = result["items"][0]
    assert top["formula_id"] == "xiaochaihu_tang"
    assert top["modifications"]
    assert all(rule["source"]["locator"] for rule in top["modifications"])
    assert all(action["herb"] for rule in top["modifications"] for action in rule["actions"])


def test_free_text_and_facts_are_normalized():
    free = library_analysis.analyze([], [], "怕冷 手脚冰凉 脉微细", limit=5)
    assert free["items"] and free["items"][0]["formula_id"] == "sini_tang"
    facts = library_analysis.analyze(
        [], [], "",
        facts=[{"key": "怕冷", "state": "present", "verified": True, "scope": "current", "subject": "patient"}],
        limit=5,
    )
    assert facts["present"]
    assert facts["items"]
    empty = library_analysis.analyze([], [], "", limit=5)
    assert empty["items"] == []
    unknown = library_analysis.analyze(["完全不存在体征"], limit=5)
    assert unknown["unmatched"] == ["完全不存在体征"]


def fact(key, state="present", **extra):
    return {"key": key, "state": state, "verified": True, "scope": "current", "subject": "patient", **extra}


def test_free_text_is_a_retrieval_hint_without_confirming_patient_findings():
    result = library_analysis.analyze(text="我父亲以前怕冷，现在没有发热")
    assert result["present"] == [] and result["absent"] == []
    assert result["retrieval_terms"]
    assert result["items"] and all(item["retrieval_only"] for item in result["items"])
    assert all(item["score_breakdown"]["modifications"] == 0 for item in result["items"])


@pytest.mark.parametrize("facts", [
    [fact("怕冷", "conflict")],
    [fact("怕冷"), fact("怕冷", "absent")],
    [fact("手脚冰凉"), fact("手脚冰冷", "absent")],
])
def test_conflicting_findings_cannot_add_candidate_or_modification_scores(facts):
    result = library_analysis.analyze(facts=facts, text="怕冷 手脚冰凉")
    assert result["conflicts"]
    assert not (set(result["present"]) & set(result["conflicts"]))
    assert not (set(result["retrieval_terms"]) & set(result["conflicts"]))
    for item in result["items"]:
        assert not (set(item["matched_terms"]) & set(result["conflicts"]))


def test_unknown_history_other_and_unverified_findings_are_not_denials_or_positive_facts():
    result = library_analysis.analyze(facts=[
        fact("怕冷", "unknown"), fact("口渴", scope="history"),
        fact("发热", subject="family"), fact("腹痛", verified=False),
    ])
    assert result["present"] == [] and result["absent"] == []
    assert result["unknown"] and result["unverified_terms"]
    assert result["items"] == []


def test_only_current_confirmed_findings_drive_scores_and_keep_composition_versions_separate():
    result = library_analysis.analyze(facts=[fact("往来寒热"), fact("胸胁苦满"), fact("心烦喜呕")], limit=5)
    top = result["items"][0]
    assert top["formula_id"] == "xiaochaihu_tang" and not top["retrieval_only"]
    assert top["composition_versions"]
    assert all(version["source_id"] and version["block_sha256"] for version in top["composition_versions"])
    assert all(rule["application_status"] == "unapplied" for rule in top["modifications"])


@pytest.fixture
def analysis_client(tmp_path):
    from app.main import create_app
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        csrf = {"X-CSRF-Token": client.get("/api/session").json()["csrf_token"]}
        yield client, csrf


def test_library_analysis_api_routes(analysis_client):
    client, csrf = analysis_client
    summary = client.get("/api/library/analysis/summary")
    assert summary.status_code == 200
    assert summary.json()["formulas_with_evidence"] == 274
    response = client.post("/api/library/analysis", json={"symptoms": ["怕冷", "手脚冰凉", "脉微细"], "limit": 5}, headers=csrf)
    assert response.status_code == 200
    assert response.json()["items"][0]["formula_id"] == "sini_tang"
    text = client.post("/api/library/analysis", json={"text": "往来寒热 胸胁苦满 心烦喜呕", "limit": 5}, headers=csrf)
    assert text.status_code == 200
    assert text.json()["items"][0]["formula_id"] == "xiaochaihu_tang"
