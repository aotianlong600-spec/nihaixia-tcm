import json
import asyncio

from fastapi.testclient import TestClient
from starlette.requests import Request
import httpx
import pytest

from app import codex_browser_relay as relay


ORIGIN = "https://aotianlong600-spec.github.io"


@pytest.fixture
def bridge():
    return TestClient(relay.create_app(), base_url="http://127.0.0.1:8769")


def pair(bridge):
    response = bridge.post("/pair", headers={"Origin": ORIGIN}, json={})
    assert response.status_code == 200
    return {"Origin": ORIGIN, "X-Tcm-Bridge-Key": response.json()["key"]}


def envelope(url="https://chatgpt.com/backend-api/codex/responses"):
    return {"url": url, "method": "POST", "headers": {
        "Content-Type": "application/json", "Authorization": "Bearer synthetic-token",
    }, "body": '{"model":"synthetic-model","stream":true}'}


def test_pairing_requires_the_project_origin_and_loopback_host(bridge):
    assert bridge.post("/pair", json={}).status_code == 403
    assert bridge.post("/pair", headers={"Origin": "https://untrusted.example"}, json={}).status_code == 403
    assert bridge.post("/pair", headers={"Origin": ORIGIN, "Host": "untrusted.example:8769"}, json={}).status_code == 403
    response = bridge.post("/pair", headers={"Origin": ORIGIN}, json={})
    assert response.json()["service"] == "nihaixia-codex-browser-relay"
    assert len(response.json()["key"]) >= 40
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert response.headers["Cache-Control"] == "no-store"


def test_preflight_allows_only_the_project_origin(bridge):
    headers = {"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
               "Access-Control-Request-Headers": "content-type,x-tcm-bridge-key",
               "Access-Control-Request-Private-Network": "true"}
    response = bridge.options("/relay", headers=headers)
    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert response.headers["Access-Control-Allow-Private-Network"] == "true"
    headers["Origin"] = "https://untrusted.example"
    denied = bridge.options("/relay", headers=headers)
    assert denied.status_code == 403
    assert "Access-Control-Allow-Origin" not in denied.headers


def test_relay_requires_pairing_and_rejects_external_destinations(bridge):
    assert bridge.post("/relay", headers={"Origin": ORIGIN}, json=envelope()).status_code == 401
    headers = pair(bridge)
    for target in ["http://chatgpt.com/backend-api/codex/responses", "https://untrusted.example/", "https://chatgpt.com:444/backend-api/codex/responses", "https://chatgpt.com/backend-api/codex/responses?redirect=1"]:
        assert bridge.post("/relay", headers=headers, json=envelope(target)).status_code == 400


def test_malformed_pairing_header_is_rejected_without_a_server_error(bridge):
    response = bridge.post("/relay", headers=[(b"Origin", ORIGIN.encode()), (b"X-Tcm-Bridge-Key", b"\xff")], json=envelope())
    assert response.status_code == 401


def test_forwards_only_explicit_credentials_and_returns_completion(bridge, monkeypatch):
    real_client = httpx.AsyncClient

    def upstream(request):
        assert str(request.url) == "https://chatgpt.com/backend-api/codex/responses"
        assert request.headers["authorization"] == "Bearer synthetic-token"
        assert request.content == b'{"model":"synthetic-model","stream":true}'
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n')

    monkeypatch.setattr(relay.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(upstream), **kw))
    response = bridge.post("/relay", headers=pair(bridge), json=envelope())
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/event-stream")
    assert "response.completed" in response.text


def test_provider_errors_do_not_echo_the_credential(bridge, monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(relay.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": {"message": "synthetic-token"}})), **kw))
    response = bridge.post("/relay", headers=pair(bridge), json=envelope())
    assert response.status_code == 401
    assert "synthetic-token" not in response.text


def test_pairing_expires_and_can_be_renewed(bridge, monkeypatch):
    headers = pair(bridge)
    expired = bridge.app.state.expires + 1
    monkeypatch.setattr(relay.time, "monotonic", lambda: expired)
    denied = bridge.post("/relay", headers=headers, json=envelope())
    assert denied.status_code == 401
    assert denied.json()["error"] == "bridge_pairing_required"
    renewed = pair(bridge)
    assert renewed["X-Tcm-Bridge-Key"] != headers["X-Tcm-Bridge-Key"]


def test_a_limited_stream_emits_an_error_instead_of_silent_success(bridge, monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(relay, "MAX_RESPONSE", 20)
    monkeypatch.setattr(relay.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=b'data: {"type":"response.completed"}\n\n')), **kw))
    response = bridge.post("/relay", headers=pair(bridge), json=envelope())
    assert '"type":"error"' in response.text
    assert "response.completed" not in response.text


def test_cancel_before_headers_closes_the_owned_client(monkeypatch):
    class CancelledClient:
        closed = False

        def build_request(self, *args, **kwargs):
            return httpx.Request(*args, **kwargs)

        async def send(self, *args, **kwargs):
            raise asyncio.CancelledError()

        async def aclose(self):
            self.closed = True

    client = CancelledClient()
    monkeypatch.setattr(relay.httpx, "AsyncClient", lambda **kwargs: client)
    app = relay.create_app()
    endpoint = next(route.endpoint for route in app.routes if route.path == "/relay")

    async def receive():
        return {"type": "http.request", "body": json.dumps(envelope()).encode(), "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/relay", "headers": [(b"x-tcm-bridge-key", app.state.pairing_key.encode())]}, receive)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(endpoint(request))
    assert client.closed
