"""Portable JSON-schema validation for Android Chaquopy.

The fixed schemas and normalization metadata in resources/portable_schemas.json
are generated at build time from the real desktop Pydantic models by
scripts/export_portable_schemas.py. At runtime this module needs only the
standard library and fastjsonschema (no pydantic-core, FastAPI or native PDF
libraries).
"""
from copy import deepcopy
import json
from pathlib import Path
import re
import math
from decimal import Decimal, InvalidOperation

import fastjsonschema
from fastjsonschema.exceptions import JsonSchemaValueException

SCHEMA_PATH = Path(__file__).resolve().parent / "resources" / "portable_schemas.json"
_DOCUMENT = None
_COMPILED = {}
_SAFE_PART = re.compile(r"[A-Za-z0-9_]{1,64}\Z")


class _InvalidInput(Exception):
    """Internal marker for normalization rules that the JSON schema cannot express."""


def _document():
    global _DOCUMENT
    if _DOCUMENT is None:
        if not SCHEMA_PATH.is_file():
            raise RuntimeError("便携校验结构尚未生成，请运行 scripts/export_portable_schemas.py")
        document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("schemas"), dict) or not isinstance(document.get("models"), dict):
            raise RuntimeError("便携校验结构文件格式无效")
        _DOCUMENT = document
    return _DOCUMENT


def _schema_name(document, name):
    if not isinstance(name, str) or not name:
        raise ValueError("未知的便携校验结构")
    resolved = document.get("aliases", {}).get(name, name)
    if resolved not in document["schemas"]:
        raise ValueError("未知的便携校验结构")
    return resolved


def _normalize_model(document, name, value):
    if not isinstance(value, dict):
        return value
    model = document["models"].get(name)
    if model is None:
        return value
    fields = model.get("fields", {})
    result = {}
    for key, item in value.items():
        spec = fields.get(key)
        if spec is None:
            if model.get("extra") == "forbid":
                # Keep unknown keys so the fixed schema rejects them; do not silently drop.
                result[key] = deepcopy(item)
            continue
        result[key] = _normalize_field(document, spec, item, model)
    for key, spec in fields.items():
        if key not in result and "default" in spec:
            result[key] = deepcopy(spec["default"])
    return result


def _normalize_field(document, spec, value, model):
    kind = spec.get("kind")
    strip = bool(model.get("strip"))
    if value is None:
        if spec.get("nullable"):
            return None
        if kind == "list" and model.get("null_lists_to_empty"):
            return []
        return None
    if kind in ('int', 'float'):
        if kind == 'int' and spec.get('strict') and type(value) is not int:
            raise _InvalidInput()
        if isinstance(value, bool) and spec.get('strict'):
            raise _InvalidInput()
        if not spec.get('strict'):
            try:
                if kind == 'int' and isinstance(value, (str, float, bool)):
                    number = Decimal(str(int(value) if isinstance(value, bool) else value))
                    if not number.is_finite() or number != number.to_integral_value():
                        raise _InvalidInput()
                    value = int(number)
                elif kind == 'float' and isinstance(value, (str, int, bool)):
                    value = float(value)
            except (ValueError, InvalidOperation, OverflowError):
                raise _InvalidInput() from None
        if kind == 'float' and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if isinstance(value, float) and not math.isfinite(value):
            raise _InvalidInput()
        return value
    if kind == 'bool' and not spec.get('strict'):
        if value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            token = value.casefold()
            if token in ('1', 'true', 't', 'yes', 'y', 'on'):
                return True
            if token in ('0', 'false', 'f', 'no', 'n', 'off'):
                return False
    if kind == "str":
        return value.strip() if strip and isinstance(value, str) else value
    if kind == "list":
        if not isinstance(value, list):
            return value
        items = spec.get("items", {"kind": "any"})
        return [_normalize_field(document, items, item, model) for item in value]
    if kind == "model":
        return _normalize_model(document, spec.get("model"), value)
    return value


def _safe_message(name, path=()):
    parts = [str(part) for part in path if isinstance(part, (str, int)) and _SAFE_PART.fullmatch(str(part))]
    suffix = "：" + ".".join(parts) if parts else ""
    return "输入不符合" + name + "结构" + suffix


def _compiled(document, name):
    compiled = _COMPILED.get(name)
    if compiled is None:
        compiled = fastjsonschema.compile(document["schemas"][name])
        _COMPILED[name] = compiled
    return compiled


def validate(schema_name, value):
    """Validate and normalize one value, returning a new dict; input is not mutated."""
    document = _document()
    name = _schema_name(document, schema_name)
    if not isinstance(value, dict):
        raise ValueError(_safe_message(name))
    try:
        data = _normalize_model(document, name, deepcopy(value))
        _compiled(document, name)(data)
    except _InvalidInput:
        raise ValueError(_safe_message(name)) from None
    except JsonSchemaValueException as exc:
        raise ValueError(_safe_message(name, getattr(exc, "path", ()))) from None
    except Exception:
        # Never echo inputs, provider values or schema internals.
        raise ValueError(_safe_message(name)) from None
    return data
