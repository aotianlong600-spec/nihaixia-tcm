"""Generate fixed, trusted JSON schemas for the portable Android validator.

Build-time only: imports the real desktop Pydantic models and writes
app/resources/portable_schemas.json. Deterministic output; no remote $refs.
Run from the repository root:

    python scripts/export_portable_schemas.py
"""
import json
from pathlib import Path
import sys
import types
from typing import Literal, Union, get_args, get_origin

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from app.personal import (Component, ConsultResult, DecisionInput, DecisionPreview,
                          EditConsultation, FormulaProposal, Intake, MatchInput,
                          MessageInput, ModelPayload, Modification, NewConsultation,
                          Question, Syndrome)
from app.model import JobInput, ModelConfig, ProfileInput, ProfileUpdate

SCHEMA_PATH = ROOT / "app" / "resources" / "portable_schemas.json"
MODELS = (
    ("Intake", Intake), ("NewConsultation", NewConsultation),
    ("EditConsultation", EditConsultation), ("MessageInput", MessageInput),
    ("MatchInput", MatchInput), ("Question", Question), ("Syndrome", Syndrome),
    ("Component", Component), ("Modification", Modification),
    ("FormulaProposal", FormulaProposal), ("ConsultResult", ConsultResult),
    ("DecisionInput", DecisionInput), ("DecisionPreview", DecisionPreview),
    ("ModelConfig", ModelConfig), ("ProfileInput", ProfileInput),
    ("ProfileUpdate", ProfileUpdate), ("JobInput", JobInput),
)
ALIASES = {f"model.{name}": name for name in ("ModelConfig", "ProfileInput", "ProfileUpdate", "JobInput")}
_MISSING = object()


def _json_value(value):
    if isinstance(value, BaseModel):
        value = value.model_dump()
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return _MISSING
    return value


def _default(field):
    if field.default_factory is not None:
        try:
            return _json_value(field.default_factory())
        except Exception:
            return _MISSING
    if field.default is not PydanticUndefined:
        return _json_value(field.default)
    return _MISSING


def _type_spec(annotation):
    if annotation is type(None):
        return {"kind": "any", "nullable": True}
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, types.UnionType):
        present = [item for item in args if item is not type(None)]
        if len(present) == 1:
            spec = _type_spec(present[0])
            spec["nullable"] = True
            return spec
        return {"kind": "any", "nullable": False}
    if origin is list:
        return {"kind": "list", "items": _type_spec(args[0]) if args else {"kind": "any"}, "nullable": False}
    if origin is Literal:
        return {"kind": "literal", "nullable": False}
    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return {"kind": "model", "model": annotation.__name__, "nullable": False}
        if annotation is str:
            return {"kind": "str", "nullable": False}
        if annotation is bool:
            return {"kind": "bool", "nullable": False}
        if annotation is int:
            return {"kind": "int", "nullable": False}
        if annotation is float:
            return {"kind": "float", "nullable": False}
        if annotation is dict:
            return {"kind": "dict", "nullable": False}
    return {"kind": "any", "nullable": False}


def _field_spec(field):
    spec = _type_spec(field.annotation)
    spec['strict'] = any(getattr(item, 'strict', False) for item in field.metadata)
    default = _default(field)
    if default is not _MISSING:
        spec["default"] = default
    return spec


def _model_metadata(model):
    config = model.model_config
    return {
        "extra": config.get("extra") or "ignore",
        "strip": bool(config.get("str_strip_whitespace", False)),
        "null_lists_to_empty": issubclass(model, ModelPayload),
        "fields": {name: _field_spec(field) for name, field in model.model_fields.items()},
    }


def build():
    """Return the deterministic schema document without writing it."""
    schemas, metadata = {}, {}
    for name, model in MODELS:
        schemas[name] = model.model_json_schema(mode="validation")
        metadata[name] = _model_metadata(model)
    return {
        "format_version": 1,
        "schemas": dict(sorted(schemas.items())),
        "aliases": dict(sorted(ALIASES.items())),
        "models": dict(sorted(metadata.items())),
    }


def main():
    document = build()
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return SCHEMA_PATH


if __name__ == "__main__":
    print(main())
