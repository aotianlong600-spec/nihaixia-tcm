"""Local AI provider configuration store with safe secret masking and preset registry."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import urlparse


PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "id": "deepseek",
        "label": "DeepSeek 官方",
        "protocol": "openai_compat",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "suggested_models": ["deepseek-chat", "deepseek-reasoner"],
        "requires_key": True,
        "env_vars": ["DEEPSEEK_API_KEY", "TCM_AI_API_KEY"],
        "note": "支持 deepseek-chat 与 deepseek-reasoner（思考过程自动折叠展示）。",
    },
    "openai": {
        "id": "openai",
        "label": "OpenAI 官方 / 兼容",
        "protocol": "openai_compat",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4.1-mini",
        "suggested_models": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"],
        "requires_key": True,
        "env_vars": ["OPENAI_API_KEY", "TCM_AI_API_KEY"],
        "note": "标准 OpenAI Chat Completions 流式接口。",
    },
    "gemini": {
        "id": "gemini",
        "label": "Google Gemini",
        "protocol": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "default_model": "gemini-2.5-flash",
        "suggested_models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        "requires_key": True,
        "env_vars": ["GEMINI_API_KEY", "GOOGLE_API_KEY", "TCM_AI_API_KEY"],
        "note": "原生 Gemini streamGenerateContent SSE 接口。",
    },
    "anthropic": {
        "id": "anthropic",
        "label": "Anthropic Claude",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-20250514",
        "suggested_models": ["claude-sonnet-4-20250514", "claude-3-7-sonnet-latest", "claude-3-5-haiku-latest"],
        "requires_key": True,
        "env_vars": ["ANTHROPIC_API_KEY", "TCM_AI_API_KEY"],
        "note": "原生 Claude Messages 流式接口。",
    },
    "ollama": {
        "id": "ollama",
        "label": "Ollama 本地模型（免 Key）",
        "protocol": "openai_compat",
        "base_url": "http://127.0.0.1:11434/v1",
        "default_model": "qwen2.5:14b",
        "suggested_models": ["qwen2.5:14b", "qwen2.5:7b", "deepseek-r1:14b"],
        "requires_key": False,
        "env_vars": [],
        "note": "完全离线本地推理；启动 Ollama 后点击“获取模型”即可选中。",
    },
    "custom": {
        "id": "custom",
        "label": "自定义 OpenAI 兼容 / 中转站",
        "protocol": "openai_compat",
        "base_url": "",
        "default_model": "",
        "suggested_models": [],
        "requires_key": True,
        "env_vars": ["TCM_AI_API_KEY", "OPENAI_API_KEY"],
        "note": "适配 SiliconFlow、OpenRouter、Qwen、Moonshot、vLLM 或任意 /v1 网关。",
    },
}

PROTOCOLS = {"openai_compat", "gemini", "anthropic"}
PERSONA_STYLES = {"master_balanced", "colloquial_lecture", "academic_strict"}
CONFIG_FILENAME = "ai_settings.json"


def mask_api_key(secret: str) -> str:
    value = (secret or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def validate_base_url(url: str, *, allow_empty: bool = False) -> str:
    cleaned = (url or "").strip().rstrip("/")
    if not cleaned:
        if allow_empty:
            return ""
        raise ValueError("Base URL 不能为空")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL 必须是以 http:// 或 https:// 开头的有效地址")
    return cleaned


def _clamp_float(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, num))


def _clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, num))


def _default_config() -> dict[str, Any]:
    preset = PROVIDER_PRESETS["deepseek"]
    return {
        "provider": preset["id"],
        "protocol": preset["protocol"],
        "base_url": preset["base_url"],
        "model": preset["default_model"],
        "api_key": "",
        "persona_style": "master_balanced",
        "temperature": 0.45,
        "max_tokens": 4096,
        "timeout_sec": 120,
    }


def _config_path(data_dir: Path) -> Path:
    return Path(data_dir).resolve() / CONFIG_FILENAME


def _read_raw(data_dir: Path) -> dict[str, Any]:
    path = _config_path(data_dir)
    base = _default_config()
    if not path.is_file():
        return base
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    if not isinstance(loaded, dict):
        return base
    merged = {**base, **{k: v for k, v in loaded.items() if k in base}}
    return merged


def _env_key_for(provider_id: str) -> str:
    preset = PROVIDER_PRESETS.get(provider_id, PROVIDER_PRESETS["custom"])
    for env_name in preset.get("env_vars", []):
        val = (os.environ.get(env_name) or "").strip()
        if val:
            return val
    return ""


def normalize_config(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(existing or _default_config())
    provider_id = str(payload.get("provider") or base["provider"]).strip().lower()
    if provider_id not in PROVIDER_PRESETS:
        raise ValueError(f"不支持的提供商: {provider_id}")
    preset = PROVIDER_PRESETS[provider_id]

    protocol = str(payload.get("protocol") or preset["protocol"]).strip().lower()
    if protocol not in PROTOCOLS:
        raise ValueError(f"不支持的协议类型: {protocol}")

    raw_url = payload.get("base_url")
    if raw_url is None:
        raw_url = base["base_url"] if provider_id == base.get("provider") and base.get("base_url") else preset["base_url"]
    base_url = validate_base_url(str(raw_url), allow_empty=(provider_id == "custom" and not str(raw_url or "").strip()))

    model = str(payload.get("model") if payload.get("model") is not None else (
        base["model"] if provider_id == base.get("provider") and base.get("model") else preset["default_model"]
    )).strip()

    clear_key = bool(payload.get("clear_api_key"))
    incoming_key = payload.get("api_key")
    if clear_key:
        api_key = ""
    elif isinstance(incoming_key, str) and incoming_key.strip():
        api_key = incoming_key.strip()
    else:
        api_key = str(base.get("api_key") or "").strip()

    style = str(payload.get("persona_style") or base["persona_style"]).strip()
    if style not in PERSONA_STYLES:
        style = "master_balanced"

    return {
        "provider": provider_id,
        "protocol": protocol,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "persona_style": style,
        "temperature": round(_clamp_float(payload.get("temperature"), base["temperature"], 0.0, 1.5), 2),
        "max_tokens": _clamp_int(payload.get("max_tokens"), base["max_tokens"], 256, 16384),
        "timeout_sec": _clamp_int(payload.get("timeout_sec"), base["timeout_sec"], 10, 300),
    }


def save_config(data_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    existing = _read_raw(data_dir)
    normalized = normalize_config(payload, existing=existing)
    path = _config_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        temp_path = Path(tmp.name)
        try:
            json.dump(normalized, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            tmp.close()
            os.replace(temp_path, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        finally:
            temp_path.unlink(missing_ok=True)
    return get_public_config(data_dir)


def resolve_runtime_config(data_dir: Path, override: dict[str, Any] | None = None) -> dict[str, Any]:
    saved = _read_raw(data_dir)
    merged = normalize_config(override, existing=saved) if override else saved
    saved_key = str(merged.get("api_key") or "").strip()
    env_key = "" if saved_key else _env_key_for(merged["provider"])
    effective_key = saved_key or env_key
    key_source = "saved" if saved_key else ("env" if env_key else "none")
    preset = PROVIDER_PRESETS.get(merged["provider"], PROVIDER_PRESETS["custom"])
    requires_key = bool(preset.get("requires_key", True))
    ready = bool(merged["base_url"] and merged["model"] and (effective_key or not requires_key))
    return {
        **merged,
        "api_key": effective_key,
        "key_source": key_source,
        "requires_key": requires_key,
        "ready": ready,
    }


def get_public_config(data_dir: Path) -> dict[str, Any]:
    resolved = resolve_runtime_config(data_dir)
    secret = resolved.pop("api_key", "")
    return {
        **resolved,
        "has_api_key": bool(secret),
        "api_key_masked": mask_api_key(secret),
        "presets": list(PROVIDER_PRESETS.values()),
    }
