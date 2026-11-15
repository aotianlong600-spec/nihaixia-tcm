"""Local AI provider configuration store with safe secret masking and preset registry."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
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
MAX_TOKENS_MIN = 256
MAX_TOKENS_CAP = 128000

VALID_REASONING_EFFORTS = ("auto", "none", "minimal", "low", "medium", "high", "xhigh")

REASONING_TIER_LIST: list[dict[str, str]] = [
    {"id": "auto", "label": "自动（模型默认）"},
    {"id": "none", "label": "关闭思考 / 直出 (none)"},
    {"id": "minimal", "label": "极轻思考 (minimal)"},
    {"id": "low", "label": "轻度思考 (low)"},
    {"id": "medium", "label": "均衡思考 (medium)"},
    {"id": "high", "label": "深度思考 (high)"},
    {"id": "xhigh", "label": "极限深度 (xhigh / max)"},
]

REASONING_MODEL_RULES: list[dict[str, Any]] = [
    {
        "id": "openai_non_reasoning",
        "protocols": ["openai_compat"],
        "model_regex": r"(?:^|/|\b)(?:gpt-4o|gpt-4\.1|gpt-4-turbo|gpt-3\.5|chatgpt-4o)",
        "exclude_regex": r"(?:codex|reasoner|thinking)",
        "efforts": ["auto"],
        "supports_reasoning": False,
        "protocol_mode": "none",
        "hint": "GPT-4o / 4.1 等非推理模型不支持思考档位，保持「自动」避免上游报错。",
    },
    {
        "id": "openai_codex_and_o3",
        "protocols": ["openai_compat"],
        "model_regex": r"(?:codex|(?:^|/|\b)(?:gpt-6|o3|o4-mini)(?:$|[-_.]))",
        "efforts": ["auto", "low", "medium", "high", "xhigh"],
        "supports_reasoning": True,
        "protocol_mode": "openai_reasoning",
        "hint": "Codex / o3 / o4-mini 支持 low / medium / high / xhigh，不支持关闭(none)。",
    },
    {
        "id": "openai_o1",
        "protocols": ["openai_compat"],
        "model_regex": r"(?:^|/|\b)o1(?:$|[-_.])",
        "efforts": ["auto", "low", "medium", "high"],
        "supports_reasoning": True,
        "protocol_mode": "openai_reasoning",
        "hint": "o1 系列支持 low / medium / high 思考强度（不支持 none 或 xhigh）。",
    },
    {
        "id": "openai_gpt5_1",
        "protocols": ["openai_compat"],
        "model_regex": r"(?:^|/|\b)gpt-5\.1(?:$|[-_.])",
        "exclude_regex": r"codex",
        "efforts": ["auto", "none", "low", "medium", "high"],
        "supports_reasoning": True,
        "protocol_mode": "openai_reasoning",
        "hint": "GPT-5.1 支持 none / low / medium / high 思考强度。",
    },
    {
        "id": "openai_gpt5_2plus",
        "protocols": ["openai_compat"],
        "model_regex": r"(?:^|/|\b)gpt-5\.[2-9]",
        "exclude_regex": r"codex",
        "efforts": ["auto", "none", "low", "medium", "high", "xhigh"],
        "supports_reasoning": True,
        "protocol_mode": "openai_reasoning",
        "hint": "GPT-5.2+ 支持 none / low / medium / high / xhigh 全档位推理控制。",
    },
    {
        "id": "openai_gpt5_base",
        "protocols": ["openai_compat"],
        "model_regex": r"(?:^|/|\b)gpt-5(?:$|[-_.])",
        "exclude_regex": r"(?:5\.|codex)",
        "efforts": ["auto", "minimal", "low", "medium", "high"],
        "supports_reasoning": True,
        "protocol_mode": "openai_reasoning",
        "hint": "GPT-5 初代支持 minimal / low / medium / high，不支持 none 或 xhigh。",
    },
    {
        "id": "deepseek_models",
        "protocols": ["openai_compat"],
        "providers": ["deepseek"],
        "model_regex": r"deepseek",
        "match_either_provider_or_model": True,
        "efforts": ["auto", "none", "low", "medium", "high", "xhigh"],
        "supports_reasoning": True,
        "protocol_mode": "deepseek",
        "hint": "DeepSeek 支持关闭(none)或分级 thinking + reasoning_effort（xhigh 对应官方 max）。",
    },
    {
        "id": "gemini_non_thinking",
        "protocols": ["gemini"],
        "model_regex": r"gemini-(?:1\.|2\.0)",
        "exclude_regex": r"thinking",
        "efforts": ["auto"],
        "supports_reasoning": False,
        "protocol_mode": "none",
        "hint": "Gemini 2.0 / 1.5 系列默认直接输出，无独立思考档位。",
    },
    {
        "id": "gemini_3plus",
        "protocols": ["gemini"],
        "model_regex": r"gemini-(?:[3-9]|\d{2})",
        "efforts": ["auto", "minimal", "low", "medium", "high"],
        "supports_reasoning": True,
        "protocol_mode": "gemini_level",
        "hint": "Gemini 3+ 原生使用 thinkingLevel（MINIMAL/LOW/MEDIUM/HIGH），不与 thinkingBudget 混传。",
    },
    {
        "id": "gemini_25_pro",
        "protocols": ["gemini"],
        "model_regex": r"gemini-2\.5-pro",
        "efforts": ["auto", "low", "medium", "high", "xhigh"],
        "supports_reasoning": True,
        "protocol_mode": "gemini_budget",
        "hint": "Gemini 2.5 Pro 强制启用思考，支持 low–xhigh thinkingBudget（不可选 none）。",
    },
    {
        "id": "gemini_budget_default",
        "protocols": ["gemini"],
        "efforts": ["auto", "none", "low", "medium", "high", "xhigh"],
        "supports_reasoning": True,
        "protocol_mode": "gemini_budget",
        "hint": "Gemini 2.5 Flash/Lite 支持关闭(0)或分级 thinkingBudget。",
    },
    {
        "id": "anthropic_non_thinking",
        "protocols": ["anthropic"],
        "model_regex": r"claude-(?:3-haiku|3-opus|3-sonnet|3-5-|3\.5-)",
        "exclude_regex": r"(?:3-7|sonnet-4|opus-4|haiku-4|claude-4)",
        "efforts": ["auto"],
        "supports_reasoning": False,
        "protocol_mode": "none",
        "hint": "早期 Claude 3 / 3.5 系列不支持扩展思考参数。",
    },
    {
        "id": "anthropic_thinking_default",
        "protocols": ["anthropic"],
        "efforts": ["auto", "none", "low", "medium", "high", "xhigh"],
        "supports_reasoning": True,
        "protocol_mode": "anthropic_thinking",
        "hint": "Claude 3.7 / 4+ 扩展思考开启时将自动确保 max_tokens > budget_tokens 并省略 temperature。",
    },
    {
        "id": "openai_compat_fallback",
        "protocols": ["openai_compat"],
        "efforts": ["auto", "none", "minimal", "low", "medium", "high", "xhigh"],
        "supports_reasoning": True,
        "protocol_mode": "openai_reasoning",
        "hint": "通用 OpenAI 兼容网关：选「自动」按模型默认；选具体档位将透传 reasoning_effort。",
    },
]


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


def _normalize_max_tokens(value: Any, default: int) -> int:
    """Normalize Max Tokens: 0/negative means unlimited (provider default)."""
    if value is None or value == "":
        return default
    try:
        num = int(float(value))
    except (TypeError, ValueError):
        return default
    if num <= 0:
        return 0
    return max(MAX_TOKENS_MIN, min(MAX_TOKENS_CAP, num))


def resolve_reasoning_profile(provider: str, protocol: str, model: str) -> dict[str, Any]:
    """Return capability metadata and allowed thinking/reasoning tiers for a model."""
    prov = (provider or "").strip().lower()
    proto = (protocol or "openai_compat").strip().lower()
    mod = (model or "").strip().lower()
    for rule in REASONING_MODEL_RULES:
        if rule.get("protocols") and proto not in rule["protocols"]:
            continue
        mod_rx = rule.get("model_regex") or ""
        excl_rx = rule.get("exclude_regex") or ""
        prov_list = rule.get("providers") or []
        if excl_rx and mod and re.search(excl_rx, mod, flags=re.IGNORECASE):
            continue
        if rule.get("match_either_provider_or_model"):
            matched = (prov in prov_list) or bool(mod_rx and mod and re.search(mod_rx, mod, flags=re.IGNORECASE))
            if not matched:
                continue
        else:
            if prov_list and prov not in prov_list:
                continue
            if mod_rx and not (mod and re.search(mod_rx, mod, flags=re.IGNORECASE)):
                continue
        return {
            "id": rule["id"],
            "efforts": list(rule["efforts"]),
            "supports_reasoning": bool(rule["supports_reasoning"]),
            "protocol_mode": rule["protocol_mode"],
            "hint": rule["hint"],
        }
    return {
        "id": "generic",
        "efforts": ["auto", "none", "minimal", "low", "medium", "high", "xhigh"],
        "supports_reasoning": True,
        "protocol_mode": "openai_reasoning",
        "hint": "选「自动」按模型默认；选具体档位将透传对应思考参数。",
    }


def normalize_reasoning_effort(value: Any, default: str, provider: str, protocol: str, model: str) -> str:
    """Coerce reasoning_effort value (including aliases) against model capabilities."""
    raw = str(value if value is not None else default or "auto").strip().lower()
    if raw == "max":
        raw = "xhigh"
    if raw not in VALID_REASONING_EFFORTS:
        raw = "auto"
    profile = resolve_reasoning_profile(provider, protocol, model)
    if raw not in profile["efforts"]:
        return "auto"
    return raw


def _default_config() -> dict[str, Any]:
    preset = PROVIDER_PRESETS["deepseek"]
    return {
        "provider": preset["id"],
        "protocol": preset["protocol"],
        "base_url": preset["base_url"],
        "model": preset["default_model"],
        "api_key": "",
        "persona_style": "master_balanced",
        "reasoning_effort": "auto",
        "temperature": 0.45,
        "max_tokens": 0,
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

    effort = normalize_reasoning_effort(
        payload.get("reasoning_effort"),
        str(base.get("reasoning_effort") or "auto"),
        provider_id,
        protocol,
        model,
    )

    return {
        "provider": provider_id,
        "protocol": protocol,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "persona_style": style,
        "reasoning_effort": effort,
        "temperature": round(_clamp_float(payload.get("temperature"), base["temperature"], 0.0, 1.5), 2),
        "max_tokens": _normalize_max_tokens(payload.get("max_tokens"), int(base.get("max_tokens", 0))),
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
    profile = resolve_reasoning_profile(resolved["provider"], resolved["protocol"], resolved["model"])
    return {
        **resolved,
        "has_api_key": bool(secret),
        "api_key_masked": mask_api_key(secret),
        "presets": list(PROVIDER_PRESETS.values()),
        "reasoning_tiers": REASONING_TIER_LIST,
        "reasoning_rules": REASONING_MODEL_RULES,
        "reasoning_profile": profile,
    }
