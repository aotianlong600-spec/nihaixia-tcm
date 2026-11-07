"""Synthetic-only checks for the portable clinical core and schema validation."""
import builtins
from copy import deepcopy
import importlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _generator():
    path = ROOT / "scripts" / "export_portable_schemas.py"
    spec = importlib.util.spec_from_file_location("portable_schema_generator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def portable(monkeypatch):
    from app import portable_validation
    monkeypatch.setattr(portable_validation, "_DOCUMENT", _generator().build())
    monkeypatch.setattr(portable_validation, "_COMPILED", {})
    return portable_validation


def test_portable_core_imports_without_desktop_or_native_modules():
    blocked = {"fastapi", "pydantic", "pydantic_core", "pdfplumber", "pypdfium2"}
    real_import = builtins.__import__
    saved = {name: module for name, module in list(sys.modules.items())
             if name == "app" or name.startswith("app.")}

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in blocked:
            raise ImportError("blocked desktop/native dependency: " + name)
        return real_import(name, *args, **kwargs)

    for name in saved:
        sys.modules.pop(name, None)
    builtins.__import__ = guarded
    try:
        core = importlib.import_module("app.consultation_core")
        assert core.ANALYSIS_REVISION == 2
        assert "用户已确认记录项" in core.CONSULT_SYSTEM
        assert callable(core.validate_result) and callable(core.prepare_task)
        assert callable(core.book_components) and callable(core.save_assistant_result)
        for name in ("app.library", "app.decision", "app.formula_engine", "app.storage"):
            assert importlib.import_module(name) is not None
    finally:
        builtins.__import__ = real_import
        for name in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def test_generated_schemas_are_deterministic_and_reference_only_local_defs():
    generator = _generator()
    first, second = generator.build(), generator.build()
    assert json.dumps(first, sort_keys=True, ensure_ascii=False) == json.dumps(second, sort_keys=True, ensure_ascii=False)
    names = set(first["schemas"])
    assert {"Intake", "ConsultResult", "DecisionPreview", "ModelConfig", "ProfileUpdate", "JobInput"} <= names

    def refs(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "$ref":
                    yield item
                else:
                    yield from refs(item)
        elif isinstance(value, list):
            for item in value:
                yield from refs(item)

    assert all(ref.startswith("#/") for ref in refs(first["schemas"]))


def test_intake_normalization_matches_pydantic_and_keeps_arbitrary_fact_fields(portable):
    from app.personal import Intake

    value = {
        "chief_complaint": "  合成头痛  ", "symptoms": [" 合成症状 "],
        "facts": [{"key": "合成事实", "state": "present", "verified": True, "custom": {"nested": [1]}}],
        "sex": "unknown",
    }
    expected = Intake.model_validate(deepcopy(value)).model_dump()
    assert portable.validate("Intake", value) == expected
    assert value["chief_complaint"] == "  合成头痛  "


def test_intake_unknown_keys_and_invalid_values_are_rejected(portable):
    from pydantic import ValidationError
    from app.personal import Intake

    for value in ({"unexpected": 1}, {"age_years": -1}, {"chief_complaint": "x" * 8001}):
        with pytest.raises(ValidationError):
            Intake.model_validate(value)
        with pytest.raises(ValueError):
            portable.validate("Intake", value)


def test_ai_result_normalization_matches_pydantic_and_does_not_mutate_input(portable):
    from app.personal import ConsultResult

    payload = {
        "stage": "assessment", "summary": "  合成摘要  ", "unexpected": {"ignored": True},
        "questions": [{"key": "q", "question": "合成问题？", "evidence_ids": None, "extra": 1}],
        "syndromes": [{"name": "合成证候", "supporting_symptoms": None, "contradictions": None,
                       "missing_information": None, "evidence_ids": None, "nested_extra": {"x": 1}}],
        "formulas": None, "risks": None, "limitations": None, "evidence_ids": None,
        "urgent": False,
    }
    snapshot = deepcopy(payload)
    normalized = portable.validate("ConsultResult", payload)
    assert payload == snapshot
    expected = ConsultResult.model_validate(deepcopy(payload)).model_dump()
    assert normalized == expected
    assert normalized["questions"][0]["evidence_ids"] == []
    assert normalized["syndromes"][0]["supporting_symptoms"] == []
    assert "unexpected" not in normalized and "nested_extra" not in normalized["syndromes"][0]


def test_portable_and_desktop_results_reach_the_same_clinical_validation(portable):
    from app import consultation_core
    from app.personal import ConsultResult

    payload = {"stage": "follow_up", "summary": "请补充当前信息", "questions": [
        {"key": "synthetic-sign", "question": "Synthetic sign present?", "reason": "Synthetic"}],
        "formulas": None, "syndromes": None, "risks": None, "limitations": None, "evidence_ids": None}
    context = {"formula_candidates": [], "evidence": []}
    desktop = consultation_core.validate_result(ConsultResult.model_validate(deepcopy(payload)).model_dump(), context)
    mobile = consultation_core.validate_result(portable.validate("ConsultResult", payload), context)
    assert mobile == desktop


@pytest.mark.parametrize("schema,value", [
    ("MessageInput", {"text": "合成", "expected_revision": True}),
    ("EditConsultation", {"expected_revision": True, "intake": {}}),
    ("ProfileUpdate", {"model": "synthetic-model", "name": "合成配置", "expected_profile_revision": True}),
    ("ProfileUpdate", {"model": "synthetic-model", "name": "合成配置", "expected_profile_revision": 1.0}),
])
def test_boolean_revisions_are_rejected_by_both_validators(portable, schema, value):
    from pydantic import ValidationError
    from app import model, personal

    classes = {"MessageInput": personal.MessageInput, "EditConsultation": personal.EditConsultation,
               "ProfileUpdate": model.ProfileUpdate}
    with pytest.raises(ValidationError):
        classes[schema].model_validate(deepcopy(value))
    with pytest.raises(ValueError):
        portable.validate(schema, value)


def test_unknown_schema_names_and_non_objects_are_rejected(portable):
    for schema, value in (("NoSuchSchema", {}), ("model.Unknown", {}), ("Intake", [])):
        with pytest.raises(ValueError):
            portable.validate(schema, value)
    assert portable.validate("model.ModelConfig", {"model": " synthetic "})["model"] == "synthetic"


def test_desktop_personal_api_keeps_missing_record_404(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        csrf = {"X-CSRF-Token": client.get("/api/session").json()["csrf_token"]}
        created = client.post("/api/consultations", json={}, headers=csrf)
        assert created.status_code == 200 and created.json()["revision"] == 1
        assert client.get(f"/api/consultations/{created.json()['id']}").status_code == 200
        missing = client.get("/api/consultations/missing")
        assert missing.status_code == 404 and missing.json()["detail"] == "问诊记录不存在"
