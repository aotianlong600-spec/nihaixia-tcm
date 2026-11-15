"""Pure-Python async streaming client for OpenAI-compatible, DeepSeek, Gemini, Claude, and Ollama APIs."""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

from ai.config_store import PROVIDER_PRESETS


class LLMClientError(RuntimeError):
    """Sanitized upstream LLM transport or protocol failure."""


def _openai_endpoint(base_url: str, suffix: str) -> str:
    clean = base_url.rstrip("/")
    if clean.endswith(suffix):
        return clean
    return f"{clean}{suffix}"


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


def _friendly_http_error(status: int, body_text: str) -> str:
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
    if status == 401:
        return f"认证失败 (HTTP 401)：请检查 API Key 是否有效或有余额。{detail}".strip()
    if status == 403:
        return f"权限或区域受限 (HTTP 403)：{detail}".strip()
    if status == 404:
        return f"接口或模型不存在 (HTTP 404)：请检查 Base URL 与模型名称。{detail}".strip()
    if status == 429:
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
                    yield parsed
            except json.JSONDecodeError:
                pass


def _prepare_openai(cfg: dict[str, Any], system_prompt: str, messages: list[dict[str, str]], stream: bool) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    chat_messages = [{"role": "system", "content": system_prompt}, *messages]
    body: dict[str, Any] = {
        "model": cfg["model"],
        "messages": chat_messages,
        "stream": stream,
        "temperature": cfg.get("temperature", 0.45),
        "max_tokens": cfg.get("max_tokens", 4096),
    }
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


def _prepare_anthropic(cfg: dict[str, Any], system_prompt: str, messages: list[dict[str, str]], stream: bool) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": cfg.get("api_key", ""),
        "anthropic-version": "2023-06-01",
    }
    clean_msgs = [
        {"role": "assistant" if m["role"] == "assistant" else "user", "content": m["content"]}
        for m in messages
    ]
    body: dict[str, Any] = {
        "model": cfg["model"],
        "system": system_prompt,
        "messages": clean_msgs,
        "max_tokens": cfg.get("max_tokens", 4096),
        "temperature": cfg.get("temperature", 0.45),
        "stream": stream,
    }
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


def _prepare_gemini(cfg: dict[str, Any], system_prompt: str, messages: list[dict[str, str]], stream: bool) -> dict[str, Any]:
    action = "streamGenerateContent?alt=sse" if stream else "generateContent"
    url = f"{cfg['base_url'].rstrip('/')}/models/{cfg['model']}:{action}"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": cfg.get("api_key", ""),
    }
    contents = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in messages
    ]
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {
            "temperature": cfg.get("temperature", 0.45),
            "maxOutputTokens": cfg.get("max_tokens", 4096),
        },
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


_PROTOCOL_ADAPTERS = {
    "openai_compat": (_prepare_openai, _parse_openai_chunk),
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
                    raise LLMClientError(_friendly_http_error(resp.status_code, err_body))
                async for chunk in _iter_sse_json(resp):
                    for ev in parse_fn(chunk):
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


async def list_models(cfg: dict[str, Any], *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Discover available models from provider API, falling back to curated suggestions."""
    provider_id = cfg.get("provider", "custom")
    preset = PROVIDER_PRESETS.get(provider_id, PROVIDER_PRESETS["custom"])
    suggested = list(preset.get("suggested_models", []))
    protocol = cfg.get("protocol", "openai_compat")
    base_url = (cfg.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        return {"models": suggested, "source": "preset"}
    if protocol == "anthropic":
        return {"models": suggested, "source": "preset"}

    owns_client = client is None
    http = client or _build_client(min(20, int(cfg.get("timeout_sec", 20))))
    try:
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
    probe_cfg = {**cfg, "max_tokens": 32, "temperature": 0.0, "timeout_sec": min(45, int(cfg.get("timeout_sec", 45)))}
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
