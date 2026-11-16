"""Opt-in loopback bridge for the project's static web app; stores no provider credentials."""
import json
import re
import secrets
import time
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

ORIGIN = "https://aotianlong600-spec.github.io"
SERVICE = "nihaixia-codex-browser-relay"
PAIR_TTL = 8 * 60 * 60
MAX_REQUEST = 2 * 1024 * 1024
MAX_RESPONSE = 4 * 1024 * 1024
HEADER_NAMES = {"authorization", "content-type", "accept", "chatgpt-account-id", "openai-beta", "originator", "user-agent"}
AUTH_PATHS = {"/oauth/token", "/api/accounts/deviceauth/usercode", "/api/accounts/deviceauth/token"}


async def read_limited(chunks, maximum):
    result = bytearray()
    async for chunk in chunks:
        if len(result) + len(chunk) > maximum:
            raise HTTPException(413, "中转请求或回复超过大小限制")
        result.extend(chunk)
    return bytes(result)


def validate_envelope(value):
    if not isinstance(value, dict) or set(value) - {"url", "method", "headers", "body"}:
        raise ValueError("invalid envelope")
    url = value.get("url")
    if not isinstance(url, str) or any(ord(c) < 32 for c in url):
        raise ValueError("invalid URL")
    target = urlsplit(url)
    if target.scheme != "https" or target.username or target.password or target.port or target.fragment:
        raise ValueError("invalid target")
    method = str(value.get("method", "POST")).upper()
    if target.hostname == "auth.openai.com" and target.path in AUTH_PATHS:
        allowed_method = "POST"
    elif target.hostname == "chatgpt.com" and target.path == "/backend-api/codex/responses":
        allowed_method = "POST"
    elif target.hostname == "chatgpt.com" and target.path == "/backend-api/codex/models":
        allowed_method = "GET"
    else:
        raise ValueError("target not allowed")
    if method != allowed_method:
        raise ValueError("method not allowed")
    if target.query and not (allowed_method == "GET" and set(parse_qs(target.query)) == {"client_version"} and re.fullmatch(r"client_version=[a-zA-Z0-9.\-]{1,40}", target.query)):
        raise ValueError("query not allowed")
    raw_headers = value.get("headers")
    if not isinstance(raw_headers, dict):
        raise ValueError("invalid headers")
    headers = {}
    for name, item in raw_headers.items():
        if not isinstance(name, str) or name.lower() not in HEADER_NAMES or not isinstance(item, str) or not item.isascii() or len(item) > 8000 or "\r" in item or "\n" in item:
            raise ValueError("header not allowed")
        headers[name.lower()] = item
    body = value.get("body")
    if method == "POST" and (not isinstance(body, str) or headers.get("content-type") not in {"application/json", "application/x-www-form-urlencoded"}):
        raise ValueError("invalid body")
    if target.hostname == "chatgpt.com" and not re.fullmatch(r"Bearer \S+", headers.get("authorization", "")):
        raise ValueError("missing credential")
    return target, method, headers, body if method == "POST" else None


def create_app():
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.pairing_key = secrets.token_urlsafe(32)
    app.state.expires = time.monotonic() + PAIR_TTL

    @app.middleware("http")
    async def guard(request, call_next):
        if request.headers.get("host", "").lower() not in {"127.0.0.1:8769", "localhost:8769"}:
            return JSONResponse({"error": "host_not_allowed"}, 403)
        trusted = request.headers.get("origin") == ORIGIN
        if request.url.path != "/health" and not trusted:
            return JSONResponse({"error": "origin_not_allowed"}, 403)
        if request.method == "OPTIONS":
            response = Response(status_code=204)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if trusted:
            response.headers.update({
                "Access-Control-Allow-Origin": ORIGIN,
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, X-Tcm-Bridge-Key",
                "Access-Control-Allow-Private-Network": "true",
                "Vary": "Origin",
            })
        return response

    @app.get("/health")
    async def health():
        return {"service": SERVICE, "status": "ok"}

    @app.post("/pair")
    async def pair():
        if time.monotonic() >= app.state.expires:
            app.state.pairing_key = secrets.token_urlsafe(32)
            app.state.expires = time.monotonic() + PAIR_TTL
        return {"service": SERVICE, "key": app.state.pairing_key, "expires_in": int(app.state.expires - time.monotonic())}

    @app.post("/relay")
    async def relay(request: Request):
        supplied = request.headers.get("x-tcm-bridge-key", "")
        if time.monotonic() >= app.state.expires or not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", supplied) or not secrets.compare_digest(supplied, app.state.pairing_key):
            return JSONResponse({"error": "bridge_pairing_required"}, 401)
        try:
            payload = json.loads(await read_limited(request.stream(), MAX_REQUEST))
            target, method, headers, body = validate_envelope(payload)
        except (ValueError, UnicodeError):
            return JSONResponse({"error": "invalid_request"}, 400)
        client = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10), follow_redirects=False, trust_env=True)
        try:
            upstream = await client.send(client.build_request(method, target.geturl(), headers=headers, content=body), stream=True)
        except httpx.HTTPError:
            await client.aclose()
            return JSONResponse({"error": "provider_connection_failed"}, 502)
        except BaseException:
            await client.aclose()
            raise
        if not upstream.is_success:
            try:
                raw = await read_limited(upstream.aiter_bytes(), 65536)
                code = "provider_request_failed"
                if target.hostname == "auth.openai.com":
                    try:
                        value = json.loads(raw)
                        if isinstance(value.get("error"), str) and re.fullmatch(r"[a-z0-9_]{1,80}", value["error"]):
                            code = value["error"]
                    except (ValueError, AttributeError):
                        pass
                return JSONResponse({"error": code}, upstream.status_code if upstream.status_code >= 400 else 502)
            finally:
                await upstream.aclose()
                await client.aclose()
        content_type = upstream.headers.get("content-type") or ("text/event-stream" if target.path.endswith("/responses") else "application/json")

        async def forward():
            size = 0
            try:
                async for chunk in upstream.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE:
                        yield b'\n\ndata: {"type":"error","error":{"message":"Local bridge response exceeds size limit"}}\n\n'
                        break
                    yield chunk
            except httpx.HTTPError:
                yield b'\n\ndata: {"type":"error","error":{"message":"Local bridge upstream connection interrupted"}}\n\n'
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(forward(), status_code=upstream.status_code, headers={"Content-Type": content_type})

    return app
