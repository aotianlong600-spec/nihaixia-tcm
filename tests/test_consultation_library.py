from copy import deepcopy
import hashlib
import json

import pytest

from app import consultation_core as core, library, storage


@pytest.fixture
def consultation(tmp_path):
    storage.initialize(tmp_path)
    with storage.connect(tmp_path) as conn:
        library.initialize(conn, tmp_path)
        core.initialize(conn)
        intake = {"facts": [
            {"key": key, "state": "present", "verified": True, "scope": "current", "subject": "patient"}
            for key in ("往来寒热", "胸胁苦满", "心烦喜呕")
        ], "symptoms": []}
        at = storage.now()
        conn.execute("INSERT INTO consultations VALUES(?,?,?,?,?,?)", ("synthetic", "Synthetic", storage.encode(intake), 1, at, at))
        conn.commit()
        yield conn


def test_consultation_freezes_source_excerpts_without_requiring_the_full_library(consultation):
    context = core.build_context(consultation, "synthetic")
    assert context["library_analysis"]["items"][0]["formula_id"] == "xiaochaihu_tang"
    excerpts = [item for item in context["evidence"] if item["format"] == "library_excerpt"]
    assert excerpts and context["library_analysis_digest"]
    assert all(item["quote_sha256"] == hashlib.sha256(item["text"].encode()).hexdigest() for item in excerpts)
    assert all(item["source_id"] and item["source_title"] and item["locator"] for item in excerpts)
    assert core.task_warnings(consultation, context) == []
    assert {key for candidate in context["library_analysis"]["items"] for key in candidate["evidence_ids"]} <= {e["id"] for e in excerpts}


def test_model_receives_ni_library_candidates_composition_versions_and_bound_citations(consultation):
    context, encoded, system = core.prepare_task(consultation, "synthetic")
    payload = json.loads(encoded)
    assert payload["library_analysis"]["items"][0]["composition_versions"]
    assert payload["library_analysis"]["items"][0]["modifications"]
    assert any(e["format"] == "library_excerpt" for e in payload["evidence"])
    assert "library_analysis" in system


def test_edited_excerpt_and_changed_dataset_mark_frozen_results_stale(consultation, monkeypatch):
    from app import consultation_library
    context = core.build_context(consultation, "synthetic")
    altered = deepcopy(context)
    excerpt = next(e for e in altered["evidence"] if e["format"] == "library_excerpt")
    excerpt["text"] += " synthetic edit"
    assert core.task_warnings(consultation, altered)
    changed_identity = deepcopy(context)
    excerpt = next(e for e in changed_identity["evidence"] if e["format"] == "library_excerpt")
    excerpt["id"] = "library:forged"
    assert core.task_warnings(consultation, changed_identity)
    monkeypatch.setattr(consultation_library, "data_digest", lambda: "different-data")
    assert core.task_warnings(consultation, context)


def test_background_and_narrative_do_not_become_confirmed_library_facts(consultation):
    intake = {"chief_complaint": "家人以前怕冷，当前没有发热", "facts": [
        {"key": "腹痛", "state": "present", "verified": True, "scope": "history", "subject": "patient"},
        {"key": "怕冷", "state": "unknown", "verified": True},
    ]}
    consultation.execute("UPDATE consultations SET intake=? WHERE id='synthetic'", (storage.encode(intake),))
    context = core.build_context(consultation, "synthetic")
    analysis = context["library_analysis"]
    assert not analysis["present"] and not analysis["absent"]
    assert analysis["unknown"] and analysis["unverified_terms"]
    assert all(item["retrieval_only"] for item in analysis["items"])


def test_library_retrieval_candidates_are_valid_model_candidates_with_supplemental_catalog_identity(consultation):
    context = core.build_context(consultation, "synthetic")
    assert {item["formula_id"] for item in context["library_analysis"]["items"]} <= {item["formula_id"] for item in context["formula_candidates"]}
    ni_ids = [item["formula_id"] for item in context["library_analysis"]["items"]]
    assert [item["formula_id"] for item in context["formula_candidates"][:len(ni_ids)]] == ni_ids


def test_excerpt_modification_cannot_become_an_applied_catalog_action(consultation):
    from app.personal import validate_consult_result
    context = core.build_context(consultation, "synthetic")
    candidate = next(item for item in context["formula_candidates"] if item["name"] == "小柴胡汤")
    excerpt_id = next(e["id"] for e in context["evidence"] if e["format"] == "library_excerpt")
    payload = {"stage": "assessment", "summary": "Synthetic only", "questions": [], "syndromes": [],
               "formulas": [{"formula_id": candidate["formula_id"], "name": candidate["name"], "reason": "Synthetic",
                             "components": [], "modifications": [{"action": "add", "herb": "大黄", "source_note": "Synthetic", "trigger_symptoms": ["便秘"], "evidence_ids": [excerpt_id]}],
                             "evidence_ids": [excerpt_id]}], "risks": [], "limitations": [], "evidence_ids": [excerpt_id]}
    result = validate_consult_result(json.dumps(payload), context)
    preview = result["formulas"][0]["modification_preview"]
    assert preview["applied"] == [] and preview["unapplied"]
    assert result["formulas"][0]["modifications"][0]["application_status"] == "unapplied"


def test_confirming_absence_replaces_current_aliases_and_preserves_background(consultation):
    from app.consultation_library import confirm_fact
    background = [
        {"key": "手脚冰凉", "state": "present", "verified": True, "scope": "history"},
        {"key": "手脚冰冷", "state": "present", "verified": True, "subject": "other"},
        {"key": "手脚冰凉", "state": "present", "verified": False},
    ]
    intake = {"symptoms": ["手脚冰凉", "手脚冰冷", "头痛"], "facts": background + [
        {"key": "手脚冰凉", "state": "present", "verified": True},
        {"key": "手脚冰冷", "state": "conflict", "verified": True},
    ]}
    consultation.execute("UPDATE consultations SET intake=? WHERE id='synthetic'", (storage.encode(intake),))
    consultation.commit()
    frozen = core.build_context(consultation, "synthetic")
    record = confirm_fact(consultation, "synthetic", " 手脚冰凉 ", "absent", 1)
    assert record["revision"] == 2 and record["intake"]["symptoms"] == ["头痛"]
    assert record["intake"]["facts"][:3] == background
    current = record["intake"]["facts"][3:]
    assert len(current) == 1
    assert current[0]["key"] == "手脚冰冷" and current[0]["state"] == "absent"
    assert current[0]["verified"] is True and current[0]["scope"] == "current"
    assert current[0]["subject"] == "patient" and current[0]["source"] == "patient"
    resolved = core.build_context(consultation, "synthetic")["library_analysis"]
    assert "手脚冰冷" in resolved["absent"] and "手脚冰冷" not in resolved["present"]
    assert core.task_warnings(consultation, frozen)


def test_fact_confirmation_rejects_stale_revision_without_changing_the_record(consultation):
    from app.consultation_library import confirm_fact
    from app.domain import DomainError
    before = core.get_record(consultation, "synthetic")
    with pytest.raises(DomainError) as error:
        confirm_fact(consultation, "synthetic", "怕冷", "present", 2)
    assert error.value.status_code == 409
    assert core.get_record(consultation, "synthetic") == before


@pytest.mark.parametrize("term,state,revision", [
    ("", "present", 1), ("  ", "present", 1), ("症" * 201, "present", 1),
    (None, "present", 1), ("怕冷", "unknown", 1), ("怕冷", "conflict", 1),
    ("怕冷", "present", True), ("怕冷", "present", 0),
    ("怕冷", "present", "1"), ("怕冷", "present", 1.0),
])
def test_fact_confirmation_strictly_validates_input_without_mutating_data(consultation, term, state, revision):
    from app.consultation_library import confirm_fact
    from app.domain import DomainError
    before = core.get_record(consultation, "synthetic")
    with pytest.raises(DomainError) as error:
        confirm_fact(consultation, "synthetic", term, state, revision)
    assert error.value.status_code == 400
    assert core.get_record(consultation, "synthetic") == before


def test_fact_confirmation_keeps_an_unknown_term_as_a_literal_current_fact(consultation):
    from app.consultation_library import confirm_fact
    record = confirm_fact(consultation, "synthetic", "合成的新体征", "present", 1)
    assert record["intake"]["facts"][-1]["key"] == "合成的新体征"
    assert record["intake"]["facts"][-1]["state"] == "present"
    assert record["revision"] == 2
