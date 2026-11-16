"""Pure-Python async streaming client for OpenAI-compatible, DeepSeek, Gemini, Claude, and Ollama APIs."""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

from ai.config_store import (
    PROVIDER_PRESETS,
    normalize_reasoning_effort,
    resolve_reasoning_profile,
)
from ai.ni_persona import (
    build_vision_intake_prompt,
    normalize_image_inputs,
    parse_vision_intake_response,
)


class LLMClientError(RuntimeError):
    """Sanitized upstream LLM transport or protocol failure."""


def _openai_endpoint(base_url: str, suffix: str) -> str:
    clean = base_url.rstrip("/")
    if clean.endswith(suffix):
        return clean
    return f"{clean}{suffix}"


def _codex_endpoint(base_url: str) -> str:
    clean = (base_url or "https://chatgpt.com/backend-api").strip().rstrip("/")
    if clean.endswith("/codex/responses"):
        return clean
    if clean.endswith("/codex"):
        return f"{clean}/responses"
    if "/backend-api" in clean:
        return f"{clean}/codex/responses"
    return f"{clean}/backend-api/codex/responses"


def _anthropic_messages_url(base_url: str) -> str:
    clean = base_url.rstrip("/")
    if clean.endswith("/messages"):
        return clean
    if clean.endswith("/v1"):
        return f"{clean}/messages"
    return f"{clean}/v1/messages"


def _ollama_tags_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}/api/tags"


def _friendly_http_error(status: int, body_text: str, protocol: str = "") -> str:
    detail = ""
    try:
        parsed = json.loads(body_text)
        err = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(err, dict):
            detail = str(err.get("message") or err.get("detail") or "")
        elif isinstance(parsed, dict):
            detail = str(parsed.get("message") or parsed.get("detail") or "")
    except json.JSONDecodeError:
        detail = ""
    detail = (detail or body_text or "").strip().splitlines()[0][:240]
    if "x-opencode-session" in detail.lower() or "x-opencode-session" in (body_text or "").lower():
        return (
            f"OpenCode Go 订阅网关拒绝了非编程代理请求 (HTTP {status})：{detail}。"
            "（提示：OpenCode Go 仅限编程代理工具并强制校验 x-opencode-session 路由头；"
            "中医问诊请改用 DeepSeek、OpenAI 兼容网关、Gemini、Claude、OpenCode Zen 通用按量接口，或直接关闭 Key 使用本地免 Key 推演）"
        )
    lower_all = f"{detail} {body_text or ''}".lower()
    if any(k in lower_all for k in ("image_url", "does not support image", "unknown variant", "multimodal", "vision")):
        return (
            f"当前所选模型或网关不支持图片识别 (HTTP {status})：{detail}。"
            "（提示：请切换到支持视觉的模型如 gpt-4o / gpt-4.1 / gemini-2.5-flash / claude-sonnet-4 / qwen-vl，或改用手动点选四诊标签）"
        )
    if status == 401:
        if protocol == "codex_oauth":
            return f"Codex 登录凭证已失效或权限不足 (HTTP 401)：请重新使用设备码或浏览器登录 OpenAI Codex。{detail}".strip()
        return f"认证失败 (HTTP 401)：请检查 API Key 是否有效或有余额。{detail}".strip()
    if status == 403:
        return f"权限或区域受限 (HTTP 403)：{detail}".strip()
    if status == 404:
        return f"接口或模型不存在 (HTTP 404)：请检查 Base URL 与模型名称。{detail}".strip()
    if status == 429:
        if protocol == "codex_oauth":
            return f"Codex 订阅当前模型额度或频率受限 (HTTP 429)：请稍候再试或切换为 gpt-5.3-codex / gpt-5.1-codex-mini。{detail}".strip()
        return f"请求频率或额度受限 (HTTP 429)：{detail}".strip()
    return f"上游模型返回错误 (HTTP {status})：{detail}".strip()


async def _read_error_text(response: httpx.Response) -> str:
    try:
        raw = await response.aread()
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _build_client(timeout_sec: int) -> httpx.AsyncClient:
    timeout = httpx.Timeout(connect=15.0, read=float(timeout_sec), write=30.0, pool=15.0)
    return httpx.AsyncClient(timeout=timeout, trust_env=True, follow_redirects=True)


async def _iter_sse_json(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    content_type = (response.headers.get("content-type") or "").lower()
    if "application/json" in content_type and "text/event-stream" not in content_type:
        body = (await response.aread()).decode("utf-8", errors="replace")
        try:
            yield {"__full_json__": json.loads(body)}
        except json.JSONDecodeError:
            pass
        return

    event_name = ""
    data_lines: list[str] = []
    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip("\r")
        if not line:
            if data_lines:
                payload_str = "\n".join(data_lines).strip()
                if payload_str and payload_str != "[DONE]":
                    try:
                        parsed = json.loads(payload_str)
                        if isinstance(parsed, dict) and event_name and "__event__" not in parsed:
                            parsed["__event__"] = event_name
                        yield parsed if isinstance(parsed, dict) else {"value": parsed}
                    except json.JSONDecodeError:
                        pass
                data_lines.clear()
                event_name = ""
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        payload_str = "\n".join(data_lines).strip()
        if payload_str and payload_str != "[DONE]":
            try:
                parsed = json.loads(payload_str)
                if isinstance(parsed, dict):
                    if event_name and "__event__" not in parsed:
                        parsed["__event__"] = event_name
                    yield parsed
            except json.JSONDecodeError:
                pass


_OPENAI_FIXED_TEMP_PROFILES = {
    "openai_codex_and_o3",
    "openai_o1",
    "openai_gpt5_base",
    "openai_gpt5_1",
    "openai_gpt5_2plus",
}
_GEMINI_LEVEL_MAP = {"minimal": "MINIMAL", "low": "LOW", "medium": "MEDIUM", "high": "HIGH"}
_GEMINI_BUDGET_MAP = {"none": 0, "low": 1024, "medium": 4096, "high": 8192, "xhigh": 24576}
_ANTHROPIC_BUDGET_MAP = {"low": 2048, "medium": 6144, "high": 12288, "xhigh": 24576}


def _resolve_effort_and_budget(cfg: dict[str, Any], protocol: str) -> tuple[dict[str, Any], str, int]:
    profile = resolve_reasoning_profile(
        str(cfg.get("provider") or ""),
        protocol,
        str(cfg.get("model") or ""),
    )
    effort = normalize_reasoning_effort(
        cfg.get("reasoning_effort"),
        "auto",
        str(cfg.get("provider") or ""),
        protocol,
        str(cfg.get("model") or ""),
    )
    try:
        raw_max = int(cfg.get("max_tokens") or 0)
    except (TypeError, ValueError):
        raw_max = 0
    return profile, effort, max(0, raw_max)


def _build_openai_content(msg: dict[str, Any]) -> Any:
    text = str(msg.get("content") or "")
    imgs = normalize_image_inputs(msg.get("images"))
    if not imgs:
        return text
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for img in imgs:
        parts.append({"type": "image_url", "image_url": {"url": img["data_url"]}})
    return parts


def _build_anthropic_content(msg: dict[str, Any]) -> Any:
    text = str(msg.get("content") or "")
    imgs = normalize_image_inputs(msg.get("images"))
    if not imgs:
        return text
    blocks: list[dict[str, Any]] = [
        {"type": "image", "source": {"type": "base64", "media_type": img["mime_type"], "data": img["b64"]}}
        for img in imgs
    ]
    blocks.append({"type": "text", "text": text})
    return blocks


def _build_gemini_parts(msg: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(msg.get("content") or "")
    parts: list[dict[str, Any]] = [{"text": text}]
    for img in normalize_image_inputs(msg.get("images")):
        parts.append({"inlineData": {"mimeType": img["mime_type"], "data": img["b64"]}})
    return parts


def _prepare_openai(cfg: dict[str, Any], system_prompt: str, messages: list[dict[str, Any]], stream: bool) -> dict[str, Any]:
    profile, effort, raw_max = _resolve_effort_and_budget(cfg, "openai_compat")
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    chat_messages = [
        {"role": "system", "content": system_prompt},
        *[{"role": m["role"], "content": _build_openai_content(m)} for m in messages],
    ]
    body: dict[str, Any] = {
        "model": cfg["model"],
        "messages": chat_messages,
        "stream": stream,
    }
    if not (profile["id"] in _OPENAI_FIXED_TEMP_PROFILES and not (profile["id"] in {"openai_gpt5_1", "openai_gpt5_2plus"} and effort == "none")):
        body["temperature"] = cfg.get("temperature", 0.45)
    if raw_max > 0:
        body["max_tokens"] = raw_max
    if effort != "auto":
        if profile["protocol_mode"] == "deepseek":
            if effort == "none":
                body["thinking"] = {"type": "disabled"}
            else:
                body["thinking"] = {"type": "enabled"}
                body["reasoning_effort"] = "max" if effort == "xhigh" else effort
        elif profile["protocol_mode"] == "openai_reasoning":
            body["reasoning_effort"] = effort
    return {
        "url": _openai_endpoint(cfg["base_url"], "/chat/completions"),
        "headers": headers,
        "json": body,
    }


def _parse_openai_chunk(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if "__full_json__" in chunk:
        full = chunk["__full_json__"]
        choices = full.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            if msg.get("reasoning_content"):
                events.append({"type": "reasoning", "text": str(msg["reasoning_content"])})
            if msg.get("content"):
                events.append({"type": "delta", "text": str(msg["content"])})
        if full.get("usage"):
            events.append({"type": "usage", "usage": full["usage"]})
        return events

    if chunk.get("error"):
        err = chunk["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise LLMClientError(f"模型流中断：{msg}")

    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or {}
        reason = delta.get("reasoning_content") or delta.get("reasoning") or ""
        if reason:
            events.append({"type": "reasoning", "text": str(reason)})
        content = delta.get("content") or ""
        if content:
            events.append({"type": "delta", "text": str(content)})
    if chunk.get("usage"):
        events.append({"type": "usage", "usage": chunk["usage"]})
    return events


def _prepare_anthropic(cfg: dict[str, Any], system_prompt: str, messages: list[dict[str, Any]], stream: bool) -> dict[str, Any]:
    profile, effort, raw_max = _resolve_effort_and_budget(cfg, "anthropic")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": cfg.get("api_key", ""),
        "anthropic-version": "2023-06-01",
    }
    clean_msgs = [
        {"role": "assistant" if m["role"] == "assistant" else "user", "content": _build_anthropic_content(m)}
        for m in messages
    ]
    thinking_cfg: dict[str, Any] | None = None
    if effort != "auto" and profile["protocol_mode"] == "anthropic_thinking":
        if effort == "none":
            thinking_cfg = {"type": "disabled"}
        elif effort in _ANTHROPIC_BUDGET_MAP:
            thinking_cfg = {"type": "enabled", "budget_tokens": _ANTHROPIC_BUDGET_MAP[effort]}

    thinking_enabled = bool(thinking_cfg and thinking_cfg.get("type") == "enabled")
    if thinking_enabled:
        budget = int(thinking_cfg["budget_tokens"])
        effective_max = max(16384, budget + 4096) if raw_max <= 0 else max(raw_max, budget + 1024)
    else:
        fallback_cap = 8192 if profile["id"] == "anthropic_non_thinking" else 16384
        effective_max = fallback_cap if raw_max <= 0 else raw_max

    body: dict[str, Any] = {
        "model": cfg["model"],
        "system": system_prompt,
        "messages": clean_msgs,
        "max_tokens": effective_max,
        "stream": stream,
    }
    if thinking_cfg is not None:
        body["thinking"] = thinking_cfg
    if not thinking_enabled:
        body["temperature"] = cfg.get("temperature", 0.45)
    return {
        "url": _anthropic_messages_url(cfg["base_url"]),
        "headers": headers,
        "json": body,
    }


def _parse_anthropic_chunk(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if "__full_json__" in chunk:
        full = chunk["__full_json__"]
        for block in full.get("content") or []:
            if block.get("type") == "thinking" and block.get("thinking"):
                events.append({"type": "reasoning", "text": str(block["thinking"])})
            elif block.get("text"):
                events.append({"type": "delta", "text": str(block["text"])})
        if full.get("usage"):
            events.append({"type": "usage", "usage": full["usage"]})
        return events

    kind = chunk.get("type") or chunk.get("__event__") or ""
    if kind == "error":
        err = chunk.get("error") or {}
        raise LLMClientError(f"Claude 流错误：{err.get('message', err)}")
    if kind == "content_block_delta":
        delta = chunk.get("delta") or {}
        if delta.get("type") == "thinking_delta" and delta.get("thinking"):
            events.append({"type": "reasoning", "text": str(delta["thinking"])})
        elif delta.get("type") == "text_delta" and delta.get("text"):
            events.append({"type": "delta", "text": str(delta["text"])})
    elif kind == "message_delta" and chunk.get("usage"):
        events.append({"type": "usage", "usage": chunk["usage"]})
    return events


def _prepare_gemini(cfg: dict[str, Any], system_prompt: str, messages: list[dict[str, Any]], stream: bool) -> dict[str, Any]:
    profile, effort, raw_max = _resolve_effort_and_budget(cfg, "gemini")
    action = "streamGenerateContent?alt=sse" if stream else "generateContent"
    url = f"{cfg['base_url'].rstrip('/')}/models/{cfg['model']}:{action}"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": cfg.get("api_key", ""),
    }
    contents = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": _build_gemini_parts(m),
        }
        for m in messages
    ]
    gen_cfg: dict[str, Any] = {"temperature": cfg.get("temperature", 0.45)}
    if raw_max > 0:
        gen_cfg["maxOutputTokens"] = raw_max
    if effort != "auto":
        if profile["protocol_mode"] == "gemini_level" and effort in _GEMINI_LEVEL_MAP:
            gen_cfg["thinkingConfig"] = {
                "includeThoughts": True,
                "thinkingLevel": _GEMINI_LEVEL_MAP[effort],
            }
        elif profile["protocol_mode"] == "gemini_budget" and effort in _GEMINI_BUDGET_MAP:
            budget = _GEMINI_BUDGET_MAP[effort]
            gen_cfg["thinkingConfig"] = {
                "includeThoughts": budget != 0,
                "thinkingBudget": budget,
            }
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": gen_cfg,
    }
    return {"url": url, "headers": headers, "json": body}


def _parse_gemini_chunk(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    payload = chunk.get("__full_json__", chunk)
    if isinstance(payload, dict) and payload.get("error"):
        err = payload["error"]
        raise LLMClientError(f"Gemini 错误：{err.get('message', err)}")
    events: list[dict[str, Any]] = []
    for cand in payload.get("candidates") or []:
        parts = (cand.get("content") or {}).get("parts") or []
        for part in parts:
            txt = part.get("text")
            if not txt:
                continue
            if part.get("thought"):
                events.append({"type": "reasoning", "text": str(txt)})
            else:
                events.append({"type": "delta", "text": str(txt)})
    if payload.get("usageMetadata"):
        events.append({"type": "usage", "usage": payload["usageMetadata"]})
    return events


def _prepare_codex_oauth(
    cfg: dict[str, Any],
    system_prompt: str,
    messages: list[dict[str, Any]],
    stream: bool,
) -> dict[str, Any]:
    _, effort, _ = _resolve_effort_and_budget(cfg, "codex_oauth")
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Authorization": f"Bearer {cfg.get('api_key', '')}",
        "OpenAI-Beta": "responses=experimental",
        "originator": "nihaixia-tcm",
    }
    account_id = str(cfg.get("codex_account_id") or "").strip()
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    input_items: list[dict[str, Any]] = []
    for msg in messages:
        role = "assistant" if msg.get("role") == "assistant" else "user"
        text = str(msg.get("content") or "")
        imgs = normalize_image_inputs(msg.get("images")) if role == "user" else []
        if role == "assistant":
            input_items.append({
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            })
        else:
            parts: list[dict[str, Any]] = [{"type": "input_text", "text": text}]
            for img in imgs:
                parts.append({"type": "input_image", "image_url": img["data_url"]})
            input_items.append({"role": "user", "content": parts})

    body: dict[str, Any] = {
        "model": cfg["model"],
        "store": False,
        "stream": True,
        "instructions": system_prompt or "",
        "input": input_items,
        "tools": [],
        "tool_choice": "none",
    }
    if effort != "auto":
        body["reasoning"] = {"effort": effort}
    return {
        "url": _codex_endpoint(cfg["base_url"]),
        "headers": headers,
        "json": body,
    }


def _extract_codex_output_text(resp_obj: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in resp_obj.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") in {"output_text", "text"} and part.get("text"):
                texts.append(str(part["text"]))
    return "".join(texts)


def _parse_codex_oauth_chunk(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if "__full_json__" in chunk:
        full = chunk["__full_json__"]
        text = _extract_codex_output_text(full)
        if text:
            events.append({"type": "delta", "text": text})
        if full.get("usage"):
            events.append({"type": "usage", "usage": full["usage"]})
        return events

    ev_type = str(chunk.get("type") or chunk.get("__event__") or "").strip()
    if ev_type in {"error", "response.failed"} or (chunk.get("error") and not ev_type):
        err = chunk.get("error") or (chunk.get("response") or {}).get("error") or chunk
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise LLMClientError(f"Codex 流中断：{msg}")
    if ev_type == "response.incomplete":
        details = (chunk.get("response") or {}).get("incomplete_details") or {}
        reason = details.get("reason") or "incomplete"
        raise LLMClientError(f"Codex 输出未完成：{reason}")

    if ev_type in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta", "response.reasoning.delta"}:
        delta = chunk.get("delta") or chunk.get("text") or ""
        if delta:
            events.append({"type": "reasoning", "text": str(delta)})
        return events

    if ev_type == "response.output_text.delta":
        delta = chunk.get("delta") or ""
        if delta:
            events.append({"type": "delta", "text": str(delta)})
        return events

    if ev_type in {"response.completed", "response.done"}:
        resp_obj = chunk.get("response") if isinstance(chunk.get("response"), dict) else chunk
        fallback_text = _extract_codex_output_text(resp_obj)
        if fallback_text:
            events.append({"type": "__fallback_delta__", "text": fallback_text})
        usage = resp_obj.get("usage") or chunk.get("usage")
        if usage:
            events.append({"type": "usage", "usage": usage})
    return events


_PROTOCOL_ADAPTERS = {
    "openai_compat": (_prepare_openai, _parse_openai_chunk),
    "codex_oauth": (_prepare_codex_oauth, _parse_codex_oauth_chunk),
    "anthropic": (_prepare_anthropic, _parse_anthropic_chunk),
    "gemini": (_prepare_gemini, _parse_gemini_chunk),
}


async def stream_chat(
    cfg: dict[str, Any],
    system_prompt: str,
    messages: list[dict[str, str]],
    *,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield normalized reasoning/delta/usage events across supported LLM APIs."""
    protocol = cfg.get("protocol", "openai_compat")
    if protocol not in _PROTOCOL_ADAPTERS:
        raise LLMClientError(f"不支持的协议：{protocol}")
    if not cfg.get("base_url"):
        raise LLMClientError("请先填写模型 Base URL")
    if not cfg.get("model"):
        raise LLMClientError("请先选择或填写模型名称")
    if protocol == "codex_oauth" and not cfg.get("api_key"):
        raise LLMClientError("当前未登录 OpenAI Codex（请先在模型设置中使用设备码或浏览器登录）")
    if cfg.get("requires_key", True) and not cfg.get("api_key"):
        raise LLMClientError("当前模型未配置 API Key")

    prepare_fn, parse_fn = _PROTOCOL_ADAPTERS[protocol]
    req = prepare_fn(cfg, system_prompt, messages, stream=True)
    owns_client = client is None
    http = client or _build_client(int(cfg.get("timeout_sec", 120)))
    try:
        try:
            async with http.stream("POST", req["url"], headers=req["headers"], json=req["json"]) as resp:
                if resp.status_code >= 400:
                    err_body = await _read_error_text(resp)
                    raise LLMClientError(_friendly_http_error(resp.status_code, err_body, protocol=protocol))
                saw_delta = False
                async for chunk in _iter_sse_json(resp):
                    for ev in parse_fn(chunk):
                        if ev.get("type") == "__fallback_delta__":
                            if not saw_delta and ev.get("text"):
                                saw_delta = True
                                yield {"type": "delta", "text": str(ev["text"])}
                            continue
                        if ev.get("type") == "delta" and ev.get("text"):
                            saw_delta = True
                        yield ev
        except httpx.TimeoutException as exc:
            raise LLMClientError(f"请求模型超时（>{cfg.get('timeout_sec', 120)}s），请检查网络或调大超时。") from exc
        except httpx.ConnectError as exc:
            hint = "请确认本地 Ollama 服务已启动" if cfg.get("provider") == "ollama" else "请检查 Base URL 与系统代理网络"
            raise LLMClientError(f"无法连接到模型接口（{hint}）。") from exc
        except httpx.HTTPError as exc:
            raise LLMClientError(f"网络请求异常：{type(exc).__name__}") from exc
    finally:
        if owns_client:
            await http.aclose()


async def complete_chat(
    cfg: dict[str, Any],
    system_prompt: str,
    messages: list[dict[str, str]],
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Collect full streamed reply into a single dict (for non-SSE callers and tests)."""
    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    usage: dict[str, Any] = {}
    async for ev in stream_chat(cfg, system_prompt, messages, client=client):
        if ev["type"] == "delta":
            text_parts.append(ev["text"])
        elif ev["type"] == "reasoning":
            reasoning_parts.append(ev["text"])
        elif ev["type"] == "usage":
            usage = ev["usage"]
    return {
        "text": "".join(text_parts),
        "reasoning": "".join(reasoning_parts),
        "usage": usage,
    }


def _codex_models_url(base_url: str) -> str:
    clean = (base_url or "https://chatgpt.com/backend-api").strip().rstrip("/")
    if clean.endswith("/codex/models"):
        root = clean
    elif clean.endswith("/codex"):
        root = f"{clean}/models"
    elif "/backend-api" in clean:
        root = f"{clean}/codex/models"
    else:
        root = f"{clean}/backend-api/codex/models"
    return f"{root}?client_version=1.0.0"


async def list_models(cfg: dict[str, Any], *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Discover available models from provider API, falling back to curated suggestions."""
    provider_id = cfg.get("provider", "custom")
    preset = PROVIDER_PRESETS.get(provider_id, PROVIDER_PRESETS["custom"])
    suggested = list(preset.get("suggested_models", []))
    protocol = cfg.get("protocol", "openai_compat")
    base_url = (cfg.get("base_url") or "").strip().rstrip("/")
    if not base_url or protocol == "anthropic":
        return {"models": suggested, "source": "preset"}

    owns_client = client is None
    http = client or _build_client(min(20, int(cfg.get("timeout_sec", 20))))
    try:
        if protocol == "codex_oauth":
            if not cfg.get("api_key"):
                return {"models": suggested, "source": "preset"}
            headers = {
                "Authorization": f"Bearer {cfg['api_key']}",
                "OpenAI-Beta": "responses=experimental",
                "originator": "codex_cli_rs",
                "Accept": "application/json",
            }
            if cfg.get("codex_account_id"):
                headers["ChatGPT-Account-Id"] = str(cfg["codex_account_id"])
            try:
                r = await http.get(_codex_models_url(base_url), headers=headers)
                if r.status_code == 200:
                    payload = r.json()
                    raw_models = payload.get("models") if isinstance(payload, dict) else []
                    live_slugs = [
                        str(m.get("slug")).strip()
                        for m in (raw_models or [])
                        if isinstance(m, dict)
                        and m.get("slug")
                        and m.get("visibility", "list") != "hide"
                        and m.get("supported_in_api", True)
                    ]
                    if live_slugs:
                        dedup = list(dict.fromkeys(live_slugs))
                        return {"models": dedup, "source": "live"}
            except (httpx.HTTPError, ValueError):
                pass
            return {"models": suggested, "source": "preset"}
        if provider_id == "ollama":
            try:
                r = await http.get(_ollama_tags_url(base_url))
                if r.status_code == 200:
                    names = [str(m["name"]) for m in (r.json().get("models") or []) if m.get("name")]
                    if names:
                        return {"models": names, "source": "live"}
            except httpx.HTTPError:
                pass
        if protocol == "gemini":
            if not cfg.get("api_key"):
                return {"models": suggested, "source": "preset"}
            r = await http.get(f"{base_url}/models", headers={"x-goog-api-key": cfg["api_key"]})
            if r.status_code >= 400:
                raise LLMClientError(_friendly_http_error(r.status_code, r.text))
            items = [
                str(m.get("name", "")).removeprefix("models/")
                for m in (r.json().get("models") or [])
                if "generateContent" in (m.get("supportedGenerationMethods") or [])
            ]
            return {"models": sorted(set(items)) or suggested, "source": "live"}

        # openai_compat
        headers = {}
        if cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        r = await http.get(_openai_endpoint(base_url, "/models"), headers=headers)
        if r.status_code >= 400:
            raise LLMClientError(_friendly_http_error(r.status_code, r.text))
        ids = [str(m.get("id")) for m in (r.json().get("data") or []) if m.get("id")]
        return {"models": sorted(set(ids)) or suggested, "source": "live"}
    except httpx.HTTPError as exc:
        raise LLMClientError(f"获取模型列表失败：{type(exc).__name__}") from exc
    finally:
        if owns_client:
            await http.aclose()


async def test_connection(cfg: dict[str, Any], *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Run a tiny real completion check and measure latency without logging secrets."""
    started = time.perf_counter()
    probe_cfg = {
        **cfg,
        "max_tokens": 256,
        "temperature": 0.0,
        "reasoning_effort": "auto",
        "timeout_sec": min(45, int(cfg.get("timeout_sec", 45))),
    }
    result = await complete_chat(
        probe_cfg,
        "你是连通性测试助手。请只回复“已连通”三个字。",
        [{"role": "user", "content": "测试连通"}],
        client=client,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "ok": True,
        "provider": cfg.get("provider"),
        "model": cfg.get("model"),
        "latency_ms": latency_ms,
        "reply_preview": result["text"].strip()[:80],
    }


async def vision_extract_intake(
    cfg: dict[str, Any],
    images: list[Any],
    *,
    hint: str = "",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Use a multimodal vision model to transcribe and structure TCM intake data from images."""
    norm_imgs = normalize_image_inputs(images)
    if not norm_imgs:
        raise LLMClientError("请先选择或粘贴至少 1 张有效的 JPG / PNG / WebP 图片（单张 ≤ 4MB）。")
    sys_prompt, user_text = build_vision_intake_prompt(hint=hint)
    vision_cfg = {
        **cfg,
        "temperature": 0.1,
        "reasoning_effort": "auto",
        "max_tokens": max(2048, int(cfg.get("max_tokens") or 0)) if int(cfg.get("max_tokens") or 0) > 0 else 0,
    }
    res = await complete_chat(
        vision_cfg,
        sys_prompt,
        [{"role": "user", "content": user_text, "images": norm_imgs}],
        client=client,
    )
    structured = parse_vision_intake_response(res.get("text", ""), image_count=len(norm_imgs))
    return {
        **structured,
        "provider": cfg.get("provider"),
        "model": cfg.get("model"),
        "usage": res.get("usage") or {},
    }
