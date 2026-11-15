"""Tests for Ni Shi AI configuration, multi-protocol streaming, grounded Rx assembly, and API routes."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import httpx
import pytest

from ai import config_store, llm_client, ni_consult, ni_persona
from app import acupuncture_catalog, bencao_catalog, catalog, hantang_catalog, neijing_catalog
from app.main import create_app


@pytest.fixture(name="data_dir")
def data_dir_fixture(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture(name="client")
def client_fixture(data_dir: Path) -> TestClient:
    return TestClient(create_app(data_dir))


# ── config_store tests ───────────────────────────────────────────────────
def test_config_store_masking_partial_update_and_clear(data_dir: Path):
    saved = config_store.save_config(
        data_dir,
        {
            "provider": "deepseek",
            "protocol": "openai_compat",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-1234567890abcdef",
            "persona_style": "master_balanced",
        },
    )
    assert saved["has_api_key"] is True
    assert saved["api_key_masked"] == "sk-1...cdef"
    assert "sk-1234567890abcdef" not in json.dumps(saved, ensure_ascii=False)
    assert saved["ready"] is True

    # Updating only model preserves saved API key
    updated = config_store.save_config(data_dir, {"model": "deepseek-reasoner"})
    assert updated["model"] == "deepseek-reasoner"
    assert updated["has_api_key"] is True
    assert config_store.resolve_runtime_config(data_dir)["api_key"] == "sk-1234567890abcdef"

    # Clearing key wipes it atomically
    cleared = config_store.save_config(data_dir, {"clear_api_key": True})
    assert cleared["has_api_key"] is False
    assert cleared["api_key_masked"] == ""


def test_config_store_env_fallback_and_url_validation(data_dir: Path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-987654321")
    cfg = config_store.resolve_runtime_config(data_dir)
    assert cfg["key_source"] == "env"
    assert cfg["ready"] is True

    with pytest.raises(ValueError):
        config_store.validate_base_url("javascript:alert(1)")
    with pytest.raises(ValueError):
        config_store.validate_base_url("file:///etc/passwd")
    assert config_store.validate_base_url("http://127.0.0.1:11434/v1/") == "http://127.0.0.1:11434/v1"


# ── llm_client tests with MockTransport ──────────────────────────────────
def _mock_async_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_llm_client_openai_compat_sse_and_json_fallback():
    sse_payload = (
        'data: {"choices":[{"delta":{"reasoning_content":"先辨六经"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"桂枝汤主之"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"[ref:1]"}}],"usage":{"total_tokens":42}}\n\n'
        "data: [DONE]\n\n"
    ).encode("utf-8")

    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url) == "https://api.deepseek.com/v1/chat/completions"
        assert req.headers["authorization"] == "Bearer sk-test-key"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse_payload)

    cfg = {
        "provider": "deepseek",
        "protocol": "openai_compat",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-reasoner",
        "api_key": "sk-test-key",
        "requires_key": True,
    }

    async def _run():
        async with _mock_async_client(handler) as cli:
            return await llm_client.complete_chat(cfg, "sys", [{"role": "user", "content": "hi"}], client=cli)

    res = asyncio.run(_run())
    assert res["reasoning"] == "先辨六经"
    assert res["text"] == "桂枝汤主之[ref:1]"
    assert res["usage"] == {"total_tokens": 42}

    # JSON non-SSE fallback
    def json_handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"choices": [{"message": {"content": "非流式兜底响应"}}], "usage": {"total_tokens": 11}},
        )

    async def _run_json():
        async with _mock_async_client(json_handler) as cli:
            return await llm_client.complete_chat(cfg, "sys", [{"role": "user", "content": "hi"}], client=cli)

    res_json = asyncio.run(_run_json())
    assert res_json["text"] == "非流式兜底响应"


def test_llm_client_anthropic_and_gemini_sse():
    anth_sse = (
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"审证中"}}\n\n'
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"小柴胡汤和解少阳"}}\n\n'
    ).encode("utf-8")

    def anth_handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url) == "https://api.anthropic.com/v1/messages"
        assert req.headers["x-api-key"] == "anth-secret"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=anth_sse)

    anth_cfg = {
        "provider": "anthropic",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-20250514",
        "api_key": "anth-secret",
        "requires_key": True,
    }

    async def _run_anth():
        async with _mock_async_client(anth_handler) as cli:
            return await llm_client.complete_chat(anth_cfg, "sys", [{"role": "user", "content": "hi"}], client=cli)

    res_anth = asyncio.run(_run_anth())
    assert res_anth["reasoning"] == "审证中"
    assert res_anth["text"] == "小柴胡汤和解少阳"

    gem_sse = (
        'data: {"candidates":[{"content":{"parts":[{"text":"思考脉象","thought":true}]}}]}\n\n'
        'data: {"candidates":[{"content":{"parts":[{"text":"用四逆汤救逆"}]}}],"usageMetadata":{"totalTokenCount":25}}\n\n'
    ).encode("utf-8")

    def gem_handler(req: httpx.Request) -> httpx.Response:
        assert "/models/gemini-2.5-flash:streamGenerateContent" in str(req.url)
        assert req.headers["x-goog-api-key"] == "gem-secret"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=gem_sse)

    gem_cfg = {
        "provider": "gemini",
        "protocol": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-2.5-flash",
        "api_key": "gem-secret",
        "requires_key": True,
    }

    async def _run_gem():
        async with _mock_async_client(gem_handler) as cli:
            return await llm_client.complete_chat(gem_cfg, "sys", [{"role": "user", "content": "hi"}], client=cli)

    res_gem = asyncio.run(_run_gem())
    assert res_gem["reasoning"] == "思考脉象"
    assert res_gem["text"] == "用四逆汤救逆"
    assert res_gem["usage"]["totalTokenCount"] == 25


def test_llm_client_error_sanitization_models_and_test_connection():
    def err_handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    cfg = {
        "provider": "openai",
        "protocol": "openai_compat",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "api_key": "sk-secret-must-not-leak",
        "requires_key": True,
    }

    async def _run_err():
        async with _mock_async_client(err_handler) as cli:
            await llm_client.complete_chat(cfg, "sys", [{"role": "user", "content": "hi"}], client=cli)

    with pytest.raises(llm_client.LLMClientError) as exc_info:
        asyncio.run(_run_err())
    assert "HTTP 401" in str(exc_info.value)
    assert "sk-secret-must-not-leak" not in str(exc_info.value)

    def ok_handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "qwen2.5:14b"}, {"id": "deepseek-r1:14b"}]})
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"choices": [{"message": {"content": "已连通"}}]},
        )

    async def _run_models_and_test():
        async with _mock_async_client(ok_handler) as cli:
            m = await llm_client.list_models(cfg, client=cli)
            t = await llm_client.test_connection(cfg, client=cli)
            return m, t

    models_res, test_res = asyncio.run(_run_models_and_test())
    assert models_res["source"] == "live"
    assert "qwen2.5:14b" in models_res["models"]
    assert test_res["ok"] is True
    assert test_res["reply_preview"] == "已连通"


# ── Grounded clinical Rx, safety & persona tests ─────────────────────────
def test_ni_consult_clinical_rx_enrichment_and_offline_reply():
    packet = ni_consult.build_clinical_context("发热 恶风 自汗", pulse="浮", tongue="淡红苔薄白")
    case = packet["case_packet"]
    assert case["matched_formulas"]
    lead = case["matched_formulas"][0]
    assert "桂枝" in lead["name"]
    assert lead["composition_raw"]
    assert lead["ingredients"]
    assert lead["usage_plain"]
    assert packet["citations"]

    offline_reply = ni_consult.build_offline_ni_reply(packet, style="master_balanced")
    assert lead["name"] in offline_reply
    assert "[ref:1]" in offline_reply

    cited = ni_consult.extract_cited_refs("按[ref:1]及[ref：2]可合参[ref:999]", packet["citations"])
    assert 1 in cited["referenced_ids"]
    assert 999 in cited["unverified_ref_ids"]


def test_ni_consult_safety_emergency_and_toxic_reaction_guardrails():
    em_pkt = ni_consult.build_clinical_context("突发胸痛彻背 呼吸困难 大汗")
    assert em_pkt["safety_boundary"]["triggered"] is True
    assert em_pkt["safety_boundary"]["mode"] == "emergency_triage"
    assert "安全熔断预警" in ni_persona.format_grounded_context(em_pkt)

    tox_pkt = ni_consult.build_clinical_context("服附子剂后口唇发麻 头晕心悸大汗")
    assert tox_pkt["safety_boundary"]["triggered"] is True
    assert tox_pkt["safety_boundary"]["mode"] == "toxic_adverse_reaction"
    assert "瞑眩" in tox_pkt["safety_boundary"]["message"]


def test_ni_consult_pinned_entity_resolution():
    guizhi = catalog.list_formulas(query="桂枝汤")["items"][0]
    pt = acupuncture_catalog.list_points()["items"][0]
    cond = acupuncture_catalog.list_conditions()["items"][0]
    ht = hantang_catalog.list_formulas()["items"][0]
    bc = bencao_catalog.list_entries()["items"][0]
    nj = neijing_catalog.list_concepts()["items"][0]

    pkt_f = ni_consult.build_clinical_context("请讲解", entity_focus={"kind": "formula", "id": guizhi["id"]})
    assert pkt_f["pinned_entity"]["name"] == guizhi["name"]
    assert pkt_f["pinned_entity"]["composition_raw"]

    pkt_a = ni_consult.build_clinical_context("请讲解", entity_focus={"kind": "acupoint", "id": pt["id"]})
    assert pkt_a["pinned_entity"]["name"]
    assert pkt_a["pinned_entity"]["location"]

    pkt_c = ni_consult.build_clinical_context("请讲解", entity_focus={"kind": "condition", "id": cond["id"]})
    assert pkt_c["pinned_entity"]["name"]

    pkt_h = ni_consult.build_clinical_context("请讲解", entity_focus={"kind": "hantang", "id": ht["id"]})
    assert pkt_h["pinned_entity"]["ht_number"]

    pkt_b = ni_consult.build_clinical_context("请讲解", entity_focus={"kind": "herb", "id": bc["id"]})
    assert pkt_b["pinned_entity"]["name"]

    pkt_n = ni_consult.build_clinical_context("请讲解", entity_focus={"kind": "neijing", "id": nj["id"]})
    assert pkt_n["pinned_entity"]["title"]

    pkt_p = ni_consult.build_clinical_context("请讲解", entity_focus={"kind": "library_page", "book_id": "ni-shanghan-pdf", "page_no": 12})
    assert pkt_p["pinned_entity"]["book_id"] == "ni-shanghan-pdf"


# ── FastAPI /api/ai/* integration tests ──────────────────────────────────
def test_ai_config_csrf_and_endpoints(client: TestClient):
    cfg = client.get("/api/ai/config").json()
    assert cfg["has_api_key"] is False
    assert len(cfg["presets"]) >= 5
    assert len(cfg["styles"]) == 3

    # Cross-origin POST blocked by same-origin guard
    csrf = client.post(
        "/api/ai/config",
        headers={"Origin": "https://evil.example", "Host": "127.0.0.1:8000"},
        json={"model": "hack"},
    )
    assert csrf.status_code == 403

    saved = client.post(
        "/api/ai/config",
        headers={"Origin": "http://testserver", "Host": "testserver"},
        json={
            "provider": "deepseek",
            "protocol": "openai_compat",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-test-api-9999",
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["has_api_key"] is True
    assert body["api_key_masked"] == "sk-t...9999"

    pkt_res = client.post("/api/ai/packet", json={"query": "往来寒热 口苦 心烦喜呕", "pulse": "弦"})
    assert pkt_res.status_code == 200
    assert pkt_res.json()["case_packet"]["matched_formulas"]

    chat_res = client.post("/api/ai/chat", json={"query": "发热 恶风 自汗", "offline": True})
    assert chat_res.status_code == 200
    chat_json = chat_res.json()
    assert chat_json["mode"] == "offline"
    assert "桂枝" in chat_json["reply"]


def test_ai_chat_stream_live_and_error_fallback(client: TestClient, monkeypatch):
    client.post(
        "/api/ai/config",
        json={
            "provider": "deepseek",
            "protocol": "openai_compat",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-live-mock-0001",
        },
    )

    async def fake_stream_ok(_cfg: dict[str, Any], _sys: str, _msgs: list[dict[str, str]]):
        yield {"type": "reasoning", "text": "太阳病桂枝汤证。"}
        yield {"type": "delta", "text": "我跟你讲嚎，这是太阳中风，开桂枝汤[ref:1]。"}
        yield {"type": "usage", "usage": {"total_tokens": 88}}

    monkeypatch.setattr("app.main.llm_client.stream_chat", fake_stream_ok)

    with client.stream("POST", "/api/ai/chat/stream", json={"query": "发热 恶风 自汗", "pulse": "浮"}) as resp:
        assert resp.status_code == 200
        raw = "".join(resp.iter_text())
    assert "event: context" in raw
    assert "event: reasoning" in raw
    assert "event: delta" in raw
    assert "event: done" in raw
    assert "桂枝汤" in raw

    async def fake_stream_fail(_cfg: dict[str, Any], _sys: str, _msgs: list[dict[str, str]]):
        if False:
            yield {}
        raise llm_client.LLMClientError("模拟上游超时")

    monkeypatch.setattr("app.main.llm_client.stream_chat", fake_stream_fail)

    with client.stream("POST", "/api/ai/chat/stream", json={"query": "发热 恶风 自汗"}) as resp:
        assert resp.status_code == 200
        err_raw = "".join(resp.iter_text())
    assert "event: error" in err_raw
    assert "offline_fallback" in err_raw
    assert "桂枝" in err_raw


def test_consult_history_patient_isolation_and_crud(client: TestClient):
    # First list auto-seeds default patient & initial session
    seeded = client.get("/api/ai/patients").json()["patients"]
    assert len(seeded) == 1
    default_pat = seeded[0]
    assert default_pat["name"] == "默认问诊人"
    a_sessions = client.get(f"/api/ai/patients/{default_pat['id']}/sessions").json()["sessions"]
    assert len(a_sessions) == 1

    # Add patient B -> gets own initial session isolated from default patient
    b_res = client.post(
        "/api/ai/patients",
        json={"name": "李四", "gender": "女", "age": "36", "notes": "素体少阳偏热"},
    ).json()
    pat_b = b_res["patient"]
    assert pat_b["name"] == "李四"
    b_ses_1 = b_res["initial_session"]["id"]

    # Save structured clinical data into patient B's session
    pkt = client.post("/api/ai/packet", json={"query": "往来寒热 口苦 心烦喜呕", "pulse": "弦"}).json()
    saved = client.post(
        f"/api/ai/sessions/{b_ses_1}/save",
        json={
            "title": "李四少阳初诊",
            "intake": {"symptoms": ["往来寒热", "口苦"], "pulse": "弦"},
            "turns": [{"role": "user", "query": "往来寒热 口苦"}],
            "latest_packet": pkt,
        },
    ).json()
    assert saved["session"]["title"] == "李四少阳初诊"
    assert saved["session"]["primary_formula"] == "小柴胡汤"

    # Update patient B metadata
    upd = client.post(
        f"/api/ai/patients/{pat_b['id']}/update",
        json={"name": "李四复诊", "notes": "忌辛辣油腻"},
    ).json()["patient"]
    assert upd["name"] == "李四复诊"
    assert upd["notes"] == "忌辛辣油腻"

    # Start a new ("新开") session for patient B and verify patient A stays isolated
    b_new = client.post(f"/api/ai/patients/{pat_b['id']}/sessions", json={"title": "复诊新开"}).json()
    assert len(b_new["sessions"]) == 2
    assert len(client.get(f"/api/ai/patients/{default_pat['id']}/sessions").json()["sessions"]) == 1

    # Delete first session of patient B -> second session remains
    del_s = client.post(f"/api/ai/sessions/{b_ses_1}/delete", json={}).json()
    assert del_s["deleted"] == b_ses_1
    assert len(del_s["sessions"]) == 1
    assert client.get(f"/api/ai/sessions/{b_ses_1}").status_code == 404

    # Delete patient B -> cascades remaining session while keeping default patient intact
    rem_b_id = del_s["sessions"][0]["id"]
    del_p = client.post(f"/api/ai/patients/{pat_b['id']}/delete", json={}).json()
    assert del_p["deleted"] == pat_b["id"]
    assert len(del_p["patients"]) == 1
    assert del_p["patients"][0]["id"] == default_pat["id"]
    assert client.get(f"/api/ai/sessions/{rem_b_id}").status_code == 404

    # Cross-origin CSRF protection enforced on patient/session mutations
    bad_pat = client.post(
        "/api/ai/patients",
        headers={"Origin": "https://evil.example", "Host": "127.0.0.1:8000"},
        json={"name": "恶意写入"},
    )
    assert bad_pat.status_code == 403
    bad_ses = client.post(
        f"/api/ai/sessions/{a_sessions[0]['id']}/save",
        headers={"Origin": "https://evil.example", "Host": "127.0.0.1:8000"},
        json={"title": "恶意篡改"},
    )
    assert bad_ses.status_code == 403


def test_shaoyang_formula_priority_primary_citations_and_negations(client: TestClient):
    res = client.post(
        "/api/ai/packet",
        json={
            "query": "往来寒热 胸胁苦满 默默不欲饮食 心烦喜呕 口苦 咽干 目眩 但不恶寒 不大便结实",
            "pulse": "弦",
        },
    )
    assert res.status_code == 200
    body = res.json()
    case_packet = body["case_packet"]
    matched = case_packet["matched_formulas"]
    assert matched
    assert matched[0]["name"] == "小柴胡汤"
    assert matched[0]["match_pct"] >= 80
    assert matched[0]["herb_count"] >= 5

    # Recognized clinical negations are surfaced in both packet and persona prompt
    assert "恶寒" in case_packet["recognized_negations"]
    ctx = ni_persona.format_grounded_context(body)
    assert '"recognized_negations"' in ctx and "恶寒" in ctx

    # Primary Ni/Hantang texts are prioritized ahead of commentary in citations
    citations = body["citations"]
    assert citations
    assert citations[0]["tradition_layer"] in {"ni_lecture", "hantang_clinical"}
