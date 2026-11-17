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
def test_config_store_preserves_long_generation_timeout(data_dir: Path):
    saved = config_store.save_config(data_dir, {"provider": "codex", "timeout_sec": 600})
    assert saved["timeout_sec"] == 600
    assert config_store.resolve_runtime_config(data_dir)["timeout_sec"] == 600
    limited = config_store.save_config(data_dir, {"timeout_sec": 9999})
    assert limited["timeout_sec"] == 600


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


def test_static_dispatch_pyodide_ai_and_pdf_routes():
    import json
    from app.static_dispatch import dispatch_request

    presets_res = json.loads(dispatch_request("/api/ai/presets-and-styles", "POST", "{}"))
    assert presets_res["status"] == 200
    assert isinstance(presets_res["body"]["presets"], list) and presets_res["body"]["presets"]
    assert isinstance(presets_res["body"]["styles"], list) and len(presets_res["body"]["styles"]) == 3
    assert presets_res["body"]["defaults"]["provider"] == "deepseek"

    pkt_res = json.loads(
        dispatch_request(
            "/api/ai/packet",
            "POST",
            json.dumps({"query": "往来寒热 口苦 咽干", "pulse": "弦"}, ensure_ascii=False),
        )
    )
    assert pkt_res["status"] == 200
    assert pkt_res["body"]["case_packet"]["matched_formulas"][0]["name"] == "小柴胡汤"

    prep_res = json.loads(
        dispatch_request(
            "/api/ai/prepare-prompt",
            "POST",
            json.dumps({"query": "发热 恶风 自汗", "style": "master_balanced"}, ensure_ascii=False),
        )
    )
    assert prep_res["status"] == 200
    assert prep_res["body"]["system_prompt"]
    assert prep_res["body"]["messages"]
    assert prep_res["body"]["offline_reply"]

    chat_res = json.loads(
        dispatch_request(
            "/api/ai/chat",
            "POST",
            json.dumps({"query": "发热 恶风 自汗", "offline": True}, ensure_ascii=False),
        )
    )
    assert chat_res["status"] == 200
    assert chat_res["body"]["mode"] == "offline"
    assert "[ref:" in chat_res["body"]["reply"]

    cite_res = json.loads(
        dispatch_request(
            "/api/ai/extract-refs",
            "POST",
            json.dumps({"text": chat_res["body"]["reply"], "citations": chat_res["body"]["packet"]["citations"]}, ensure_ascii=False),
        )
    )
    assert cite_res["status"] == 200
    assert cite_res["body"]["referenced_ids"]

    pdf_res = json.loads(dispatch_request("/api/__pdf-source?url=/api/acupuncture/source-pages/12/image"))
    assert pdf_res["status"] == 200
    assert pdf_res["body"]["pdf_page"] == 12
    assert pdf_res["body"]["relative_path"].endswith(".pdf")


def test_mobile_responsive_hooks_and_pages_builder_helpers():
    from pathlib import Path
    from scripts import build_pages

    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    assert "viewport-fit=cover" in html
    assert 'id="ai-mobile-pane-tabs"' in html
    assert 'data-mobile-pane="consult"' in html

    png_bytes = build_pages._render_fallback_png(64)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    for rel, (_, digest) in build_pages.RUNTIME_ASSETS.items():
        assert len(digest) == 64, f"{rel} digest must be 64-char sha256"
    assert build_pages._should_bundle_data_file("brain_data/curated_batches/b1.json") is True
    assert build_pages._should_bundle_data_file("brain_data/library/page_images/foo.png") is False
    assert build_pages._should_bundle_data_file("brain_data/formulas_report.json") is False

    opencode_msg = llm_client._friendly_http_error(
        400,
        '{"error":{"message":"Request is missing x-opencode-session and cannot be routed efficiently."}}',
    )
    assert "当前客户端请求" in opencode_msg
    assert "免费模型" in opencode_msg
    assert "x-opencode-session" in opencode_msg


def test_unlimited_max_tokens_and_model_aware_reasoning_profiles(data_dir: Path):
    pub_default = config_store.get_public_config(data_dir)
    assert pub_default["max_tokens"] == 0
    assert pub_default["reasoning_effort"] == "auto"
    assert isinstance(pub_default["reasoning_tiers"], list) and pub_default["reasoning_tiers"]
    assert isinstance(pub_default["reasoning_rules"], list) and pub_default["reasoning_rules"]

    # Negative / 0 -> unlimited (0); positive clamps within [256, 128000]
    s_neg = config_store.save_config(data_dir, {"max_tokens": -100})
    assert s_neg["max_tokens"] == 0
    s_low = config_store.save_config(data_dir, {"max_tokens": 50})
    assert s_low["max_tokens"] == 256
    s_high = config_store.save_config(data_dir, {"max_tokens": 999999})
    assert s_high["max_tokens"] == 128000

    # Non-reasoning model (gpt-4.1) rejects reasoning tiers -> coerces cleanly to auto & omits param
    s_non = config_store.save_config(
        data_dir,
        {"provider": "openai", "protocol": "openai_compat", "model": "gpt-4.1", "reasoning_effort": "high", "max_tokens": 0},
    )
    assert s_non["reasoning_effort"] == "auto"
    assert s_non["reasoning_profile"]["efforts"] == ["auto"]
    req_41 = llm_client._prepare_openai({**s_non, "api_key": "k"}, "sys", [{"role": "user", "content": "hi"}], stream=True)
    assert "max_tokens" not in req_41["json"]
    assert "reasoning_effort" not in req_41["json"]
    assert req_41["json"]["temperature"] == 0.45

    # Codex rejects none and omits temperature
    s_codex = config_store.save_config(
        data_dir,
        {"provider": "openai", "protocol": "openai_compat", "model": "gpt-5.2-codex", "reasoning_effort": "none"},
    )
    assert s_codex["reasoning_effort"] == "auto"
    s_codex_hi = config_store.save_config(data_dir, {"reasoning_effort": "xhigh"})
    assert s_codex_hi["reasoning_effort"] == "xhigh"
    req_codex = llm_client._prepare_openai({**s_codex_hi, "api_key": "k"}, "sys", [{"role": "user", "content": "hi"}], stream=True)
    assert req_codex["json"]["reasoning_effort"] == "xhigh"
    assert "temperature" not in req_codex["json"]

    # DeepSeek none vs xhigh->max
    ds_none = llm_client._prepare_openai(
        {"provider": "deepseek", "protocol": "openai_compat", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "reasoning_effort": "none", "max_tokens": 0},
        "sys",
        [{"role": "user", "content": "hi"}],
        stream=True,
    )
    assert ds_none["json"]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in ds_none["json"]
    assert "max_tokens" not in ds_none["json"]

    ds_max = llm_client._prepare_openai(
        {"provider": "deepseek", "protocol": "openai_compat", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-reasoner", "reasoning_effort": "xhigh", "max_tokens": 0},
        "sys",
        [{"role": "user", "content": "hi"}],
        stream=True,
    )
    assert ds_max["json"]["thinking"] == {"type": "enabled"}
    assert ds_max["json"]["reasoning_effort"] == "max"

    # Gemini 2.5 Pro vs 3 Pro (never mixes thinkingBudget and thinkingLevel)
    assert "none" not in config_store.resolve_reasoning_profile("gemini", "gemini", "gemini-2.5-pro")["efforts"]
    gem_25 = llm_client._prepare_gemini(
        {"provider": "gemini", "protocol": "gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta", "model": "gemini-2.5-flash", "reasoning_effort": "none", "max_tokens": 0},
        "sys",
        [{"role": "user", "content": "hi"}],
        stream=False,
    )
    assert "maxOutputTokens" not in gem_25["json"]["generationConfig"]
    assert gem_25["json"]["generationConfig"]["thinkingConfig"] == {"includeThoughts": False, "thinkingBudget": 0}
    assert "thinkingLevel" not in gem_25["json"]["generationConfig"]["thinkingConfig"]

    gem_3 = llm_client._prepare_gemini(
        {"provider": "gemini", "protocol": "gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta", "model": "gemini-3-pro", "reasoning_effort": "high", "max_tokens": 0},
        "sys",
        [{"role": "user", "content": "hi"}],
        stream=False,
    )
    assert gem_3["json"]["generationConfig"]["thinkingConfig"] == {"includeThoughts": True, "thinkingLevel": "HIGH"}
    assert "thinkingBudget" not in gem_3["json"]["generationConfig"]["thinkingConfig"]

    # Anthropic unlimited + thinking ensures max_tokens > budget_tokens and omits temperature
    anth_req = llm_client._prepare_anthropic(
        {"provider": "anthropic", "protocol": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-sonnet-4-20250514", "reasoning_effort": "high", "max_tokens": 0},
        "sys",
        [{"role": "user", "content": "hi"}],
        stream=True,
    )
    assert anth_req["json"]["thinking"] == {"type": "enabled", "budget_tokens": 12288}
    assert anth_req["json"]["max_tokens"] > 12288
    assert "temperature" not in anth_req["json"]


def test_multimodal_vision_intake_routes_and_ui_hooks(client: TestClient, monkeypatch):
    import base64
    from app.static_dispatch import dispatch_request
    from scripts import build_pages

    png_b64 = base64.b64encode(build_pages._render_fallback_png(4)).decode("ascii")
    img_payload = [{"name": "问诊表.png", "data_url": f"data:image/png;base64,{png_b64}"}]

    # Unconfigured returns actionable 400
    unconf = client.post("/api/ai/vision-intake", json={"images": img_payload})
    assert unconf.status_code == 400
    assert "视觉" in unconf.json()["detail"]

    # CSRF check
    bad_orig = client.post(
        "/api/ai/vision-intake",
        headers={"Origin": "https://evil.example", "Host": "127.0.0.1:8000"},
        json={"images": img_payload},
    )
    assert bad_orig.status_code == 403

    # Configure mock live key and verify protocol builders include multimodal parts
    client.post(
        "/api/ai/config",
        json={"provider": "openai", "protocol": "openai_compat", "base_url": "https://api.openai.com/v1", "model": "gpt-4o", "api_key": "sk-vision-ok"},
    )
    vision_msg = [{"role": "user", "content": "读取图片", "images": ni_persona.normalize_image_inputs(img_payload)}]
    oa_body = llm_client._prepare_openai(
        {"provider": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4o"},
        "sys",
        vision_msg,
        False,
    )["json"]
    assert isinstance(oa_body["messages"][1]["content"], list)
    assert oa_body["messages"][1]["content"][1]["type"] == "image_url"

    gem_body = llm_client._prepare_gemini({"provider": "gemini", "base_url": "https://x", "model": "gemini-2.5-flash"}, "sys", vision_msg, False)["json"]
    assert gem_body["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "image/png"

    anth_body = llm_client._prepare_anthropic({"provider": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-sonnet-4-20250514"}, "sys", vision_msg, False)["json"]
    assert anth_body["messages"][0]["content"][0]["type"] == "image"

    # Mock vision completion JSON extraction
    async def fake_complete(_cfg, _sys, _msgs, client=None):
        return {
            "text": '```json\n{"chief_complaint":"往来寒热 口苦咽干","symptoms":["往来寒热","口苦"],"negations":["不恶寒"],"pulses":["弦"],"tongues":["舌淡红苔薄白"],"medical_notes":{"present":"受凉3天"},"warnings":["光线偏暗注意复核"]}\n```',
            "reasoning": "",
            "usage": {"total_tokens": 55},
        }

    monkeypatch.setattr("ai.llm_client.complete_chat", fake_complete)
    ok_res = client.post("/api/ai/vision-intake", json={"images": img_payload, "hint": "手写病历"})
    assert ok_res.status_code == 200
    body = ok_res.json()
    assert "往来寒热" in body["symptoms"]
    assert "不恶寒" in body["negations"]
    assert "弦" in body["pulses"]
    assert body["medical_notes"]["present"] == "受凉3天"

    # Static Pyodide dispatcher rejects invalid SVG data URI and normalizes valid PNG
    bad_svg = json.loads(
        dispatch_request(
            "/api/ai/vision-prepare",
            "POST",
            json.dumps({"images": [{"data_url": "data:image/svg+xml;base64,PHN2Zy8+"}]}),
        )
    )
    assert bad_svg["status"] == 400
    good_prep = json.loads(dispatch_request("/api/ai/vision-prepare", "POST", json.dumps({"images": img_payload})))
    assert good_prep["status"] == 200 and len(good_prep["body"]["images"]) == 1

    presets_meta = json.loads(dispatch_request("/api/ai/presets-and-styles", "POST", "{}")).get("body", {})
    assert presets_meta["defaults"]["max_tokens"] == 0
    assert presets_meta.get("reasoning_rules")

    # Friendly error on non-vision model rejection
    vis_err = llm_client._friendly_http_error(400, '{"error":{"message":"unknown variant image_url"}}')
    assert "图片识别" in vis_err

    # Frontend HTML hook assertions
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    for hook in (
        "ai-cfg-reasoning",
        "ai-effort-select",
        "ai-upload-image-btn",
        "ai-ocr-extract-btn",
        "ai-profile-select",
        "ai-model-select",
        "ai-cfg-profile-select",
        "ai-cfg-save-as-btn",
        "ai-cfg-codex-box",
        "ai-cfg-codex-device-btn",
        "ai-cfg-codex-browser-btn",
        "codex_oauth",
        'min="0"',
        'value="0"',
    ):
        assert hook in html, f"missing HTML hook: {hook}"


def _make_fake_jwt(claims: dict[str, Any]) -> str:
    import base64

    def _b64(obj: dict[str, Any]) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}.sig"


def test_config_store_multi_profiles_migration_and_key_isolation(data_dir: Path):
    # Legacy v1 flat settings auto-migrates cleanly on read
    legacy_path = data_dir / config_store.CONFIG_FILENAME
    legacy_path.write_text(
        json.dumps(
            {
                "provider": "deepseek",
                "protocol": "openai_compat",
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "api_key": "sk-legacy-11112222",
                "persona_style": "master_balanced",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pub = config_store.get_public_config(data_dir)
    assert pub["active_profile_id"] == "default"
    assert len(pub["profiles"]) == 1
    assert pub["profiles"][0]["has_api_key"] is True
    assert "sk-legacy-11112222" not in json.dumps(pub, ensure_ascii=False)

    # Save a second independent Gemini profile without inheriting DeepSeek's key
    pub2 = config_store.save_config(
        data_dir,
        {
            "save_as_new": True,
            "profile_name": "Gemini 识图",
            "provider": "gemini",
            "protocol": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "model": "gemini-2.5-flash",
            "api_key": "AIza-gemini-99990000",
        },
    )
    assert len(pub2["profiles"]) == 2
    assert pub2["provider"] == "gemini"
    assert pub2["profile_name"] == "Gemini 识图"
    assert "AIza-gemini-99990000" not in json.dumps(pub2, ensure_ascii=False)
    assert "sk-legacy-11112222" not in json.dumps(pub2, ensure_ascii=False)

    # Switching back to legacy profile restores its independent DeepSeek key
    switched = config_store.select_profile(data_dir, "default")
    assert switched["provider"] == "deepseek"
    rt = config_store.resolve_runtime_config(data_dir)
    assert rt["api_key"] == "sk-legacy-11112222"

    # Switching provider within the same profile isolates old provider's key
    iso = config_store.save_config(
        data_dir,
        {
            "save_as_new": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
        },
    )
    assert iso["has_api_key"] is False
    assert config_store.resolve_runtime_config(data_dir)["api_key"] == ""

    # Delete newly created OpenAI profile cleanly, refuse deleting last profile
    after_del = config_store.delete_profile(data_dir, iso["active_profile_id"])
    assert len(after_del["profiles"]) == 2
    after_del2 = config_store.delete_profile(data_dir, pub2["active_profile_id"])
    assert len(after_del2["profiles"]) == 1
    with pytest.raises(ValueError):
        config_store.delete_profile(data_dir, "default")


def test_codex_oauth_flows_refresh_and_api_routes(data_dir: Path, client: TestClient, monkeypatch):
    from urllib.parse import parse_qs, urlparse
    from ai import codex_oauth
    from app.static_dispatch import dispatch_request

    access_jwt_1 = _make_fake_jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acc_1234567890abcdef",
                "chatgpt_plan_type": "plus",
            },
            "email": "nihaixia@example.com",
        }
    )
    access_jwt_2 = _make_fake_jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acc_1234567890abcdef",
                "chatgpt_plan_type": "plus",
            },
            "email": "nihaixia@example.com",
        }
    )
    assert access_jwt_1 == access_jwt_2
    # Distinguish token payload slightly for refresh check
    access_jwt_refreshed = _make_fake_jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acc_1234567890abcdef",
                "chatgpt_plan_type": "pro",
            },
            "email": "nihaixia@example.com",
            "jti": "refresh_2",
        }
    )
    id_jwt = _make_fake_jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acc_1234567890abcdef",
                "chatgpt_plan_type": "plus",
            },
            "email": "nihaixia@example.com",
        }
    )

    seen_grants: list[str] = []

    def oauth_handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/accounts/deviceauth/usercode":
            return httpx.Response(
                200,
                json={"device_auth_id": "dev_001", "user_code": "TCM-9988", "interval": 1},
            )
        if req.url.path == "/api/accounts/deviceauth/token":
            return httpx.Response(404, json={"error": "authorization_pending"})
        if req.url.path == "/oauth/token":
            body_params = parse_qs(req.content.decode("utf-8"))
            grant = (body_params.get("grant_type") or [""])[0]
            seen_grants.append(grant)
            if grant == "authorization_code":
                return httpx.Response(
                    200,
                    json={
                        "access_token": access_jwt_1,
                        "refresh_token": "rt_initial_secret",
                        "id_token": id_jwt,
                        "expires_in": 3600,
                    },
                )
            if grant == "refresh_token":
                return httpx.Response(
                    200,
                    json={
                        "access_token": access_jwt_refreshed,
                        "refresh_token": "rt_rotated_secret",
                        "id_token": id_jwt,
                        "expires_in": 3600,
                    },
                )
        return httpx.Response(404, json={"error": "unexpected"})

    # Prevent real background device poll & localhost:1455 port binding side effects during tests
    monkeypatch.setattr("ai.codex_oauth._build_client", lambda timeout=25.0: _mock_async_client(oauth_handler))
    monkeypatch.setattr("ai.codex_oauth._start_local_callback_listener", lambda mgr, attempt, loop: False)

    async def _run() -> None:
        dev_status = await codex_oauth.start_login(data_dir, method="device", client=_mock_async_client(oauth_handler))
        assert dev_status["login"]["method"] == "device"
        assert dev_status["login"]["user_code"] == "TCM-9988"
        canceled = codex_oauth.cancel_login(data_dir)
        assert canceled["login"] is None or canceled["login"]["status"] == "cancelled"

        # Browser PKCE flow -> extract state from auth_url and complete callback exchange
        br_status = await codex_oauth.start_login(data_dir, method="browser", client=_mock_async_client(oauth_handler))
        auth_url = br_status["login"]["auth_url"]
        state = parse_qs(urlparse(auth_url).query)["state"][0]

        done_status = await codex_oauth.submit_callback_url(
            data_dir,
            f"http://localhost:1455/auth/callback?code=auth_code_xyz&state={state}",
            client=_mock_async_client(oauth_handler),
        )
        assert done_status["logged_in"] is True
        assert done_status["account_masked"] == "ni***@example.com"
        assert "rt_initial_secret" not in json.dumps(done_status, ensure_ascii=False)
        assert "authorization_code" in seen_grants

        # Force near-expiry and confirm ensure_fresh_runtime_config rotates token cleanly
        cred_path = codex_oauth.credential_path(data_dir)
        raw_cred = json.loads(cred_path.read_text(encoding="utf-8"))
        raw_cred["expires"] = 1000  # long past expiry
        cred_path.write_text(json.dumps(raw_cred), encoding="utf-8")

        config_store.save_config(
            data_dir,
            {
                "save_as_new": True,
                "provider": "codex",
                "protocol": "codex_oauth",
                "base_url": "https://chatgpt.com/backend-api",
                "model": "gpt-5.3-codex",
            },
        )
        rt = config_store.resolve_runtime_config(data_dir)
        assert rt["ready"] is True
        refreshed = await codex_oauth.ensure_fresh_runtime_config(
            data_dir,
            rt,
            client=_mock_async_client(oauth_handler),
        )
        assert "refresh_token" in seen_grants
        assert refreshed["api_key"] == access_jwt_refreshed
        assert refreshed["codex_account_id"] == "acc_1234567890abcdef"

    asyncio.run(_run())

    # FastAPI routes for profiles CRUD + codex login/callback/cancel/logout + CSRF check
    save_new_res = client.post(
        "/api/ai/config",
        json={
            "save_as_new": True,
            "profile_name": "测试快速切换配置",
            "provider": "openai",
            "protocol": "openai_compat",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1-mini",
            "api_key": "sk-profile-switch-8888",
        },
    )
    assert save_new_res.status_code == 200
    new_pid = save_new_res.json()["active_profile_id"]
    assert save_new_res.json()["profile_name"] == "测试快速切换配置"
    assert "sk-profile-switch-8888" not in json.dumps(save_new_res.json(), ensure_ascii=False)

    sel_ok = client.post("/api/ai/profiles/select", json={"profile_id": "default"})
    assert sel_ok.status_code == 200
    assert sel_ok.json()["active_profile_id"] == "default"

    del_ok = client.post("/api/ai/profiles/delete", json={"profile_id": new_pid})
    assert del_ok.status_code == 200
    assert all(p["profile_id"] != new_pid for p in del_ok.json()["profiles"])

    status_res = client.get("/api/ai/codex/status")
    assert status_res.status_code == 200
    assert status_res.json()["logged_in"] is True

    login_br = client.post("/api/ai/codex/login", json={"method": "browser"})
    assert login_br.status_code == 200
    br_state = parse_qs(urlparse(login_br.json()["login"]["auth_url"]).query)["state"][0]
    cb_ok = client.post(
        "/api/ai/codex/callback",
        json={"callback_url": f"http://localhost:1455/auth/callback?code=route_code&state={br_state}"},
    )
    assert cb_ok.status_code == 200
    assert cb_ok.json()["logged_in"] is True

    cancel_res = client.post("/api/ai/codex/cancel")
    assert cancel_res.status_code == 200

    sel_bad = client.post("/api/ai/profiles/select", json={"profile_id": "missing_id"})
    assert sel_bad.status_code == 400

    csrf_bad = client.post(
        "/api/ai/profiles/select",
        headers={"Origin": "https://evil.example", "Host": "127.0.0.1:8000"},
        json={"profile_id": "default"},
    )
    assert csrf_bad.status_code == 403

    csrf_codex = client.post(
        "/api/ai/codex/logout",
        headers={"Origin": "https://evil.example", "Host": "127.0.0.1:8000"},
    )
    assert csrf_codex.status_code == 403

    out_res = client.post("/api/ai/codex/logout")
    assert out_res.status_code == 200
    assert out_res.json()["logged_in"] is False

    # Static dispatcher exposes codex preset cleanly
    presets = json.loads(dispatch_request("/api/ai/presets-and-styles", "POST", "{}")).get("body", {}).get("presets", [])
    codex_preset = next((p for p in presets if p["id"] == "codex"), None)
    assert codex_preset is not None
    assert codex_preset["protocol"] == "codex_oauth"
    assert codex_preset["requires_oauth"] is True
    assert codex_preset["requires_key"] is False


def test_llm_client_codex_oauth_responses_streaming_and_errors():
    seen_req: dict[str, Any] = {}
    sse_bytes = (
        'event: response.reasoning_summary_text.delta\n'
        'data: {"type":"response.reasoning_summary_text.delta","delta":"先辨太阳表虚"}\n\n'
        'event: response.output_text.delta\n'
        'data: {"type":"response.output_text.delta","delta":"宜桂枝汤"}\n\n'
        'event: response.completed\n'
        'data: {"type":"response.completed","response":{"usage":{"total_tokens":88},"output":[{"content":[{"type":"output_text","text":"宜桂枝汤"}]}]}}\n\n'
    ).encode("utf-8")

    def handler(req: httpx.Request) -> httpx.Response:
        seen_req["url"] = str(req.url)
        seen_req["headers"] = dict(req.headers)
        seen_req["body"] = json.loads(req.content.decode("utf-8"))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse_bytes)

    cfg = {
        "provider": "codex",
        "protocol": "codex_oauth",
        "base_url": "https://chatgpt.com/backend-api",
        "model": "gpt-5.3-codex",
        "api_key": "oauth-access-token",
        "codex_account_id": "acc_9999",
        "requires_key": False,
        "reasoning_effort": "high",
        "temperature": 0.45,
        "max_tokens": 2048,
    }
    res = asyncio.run(
        llm_client.complete_chat(
            cfg,
            "sys prompt",
            [{"role": "user", "content": "发热有汗恶风"}],
            client=_mock_async_client(handler),
        )
    )
    assert seen_req["url"] == "https://chatgpt.com/backend-api/codex/responses"
    assert seen_req["headers"]["chatgpt-account-id"] == "acc_9999"
    assert seen_req["headers"]["openai-beta"] == "responses=experimental"
    assert "temperature" not in seen_req["body"]
    assert "max_tokens" not in seen_req["body"]
    assert seen_req["body"]["reasoning"] == {"effort": "high"}
    # No duplication between delta event and response.completed full output
    assert res["text"] == "宜桂枝汤"
    assert res["reasoning"] == "先辨太阳表虚"
    assert res["usage"]["total_tokens"] == 88

    # Fallback extraction still recovers output text if no deltas streamed
    no_delta_sse = (
        'event: response.completed\n'
        'data: {"type":"response.completed","response":{"output":[{"content":[{"type":"output_text","text":"单次完结文本"}]}]}}\n\n'
    ).encode("utf-8")
    res_fb = asyncio.run(
        llm_client.complete_chat(
            cfg,
            "sys prompt",
            [{"role": "user", "content": "发热"}],
            client=_mock_async_client(lambda req: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=no_delta_sse)),
        )
    )
    assert res_fb["text"] == "单次完结文本"

    # Live Codex models discovery filters hidden entries and falls back cleanly on error
    def live_models_handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/backend-api/codex/models"
        assert req.url.params.get("client_version") == "1.0.0"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"slug": "gpt-6.1-sol", "visibility": "list", "supported_in_api": True},
                    {"slug": "gpt-5.6-sol", "visibility": "list", "supported_in_api": True},
                    {"slug": "gpt-reserve", "visibility": "hide", "supported_in_api": True},
                    {"slug": "internal-only", "visibility": "list", "supported_in_api": False},
                ]
            },
        )

    live_models = asyncio.run(llm_client.list_models(cfg, client=_mock_async_client(live_models_handler)))
    assert live_models["source"] == "live"
    assert live_models["models"] == ["gpt-6.1-sol", "gpt-5.6-sol"]

    # Preset fallback succeeds cleanly when /codex/models is unreachable or unauthenticated
    models = asyncio.run(llm_client.list_models({**cfg, "api_key": ""}, client=_mock_async_client(handler)))
    assert "gpt-5.6-sol" in models["models"]
    assert models["source"] == "preset"

    # Friendly 401 guidance
    err_401 = llm_client._friendly_http_error(401, '{"error":{"message":"invalid token"}}', protocol="codex_oauth")
    assert "Codex" in err_401


def test_codex_auto_adopt_profile_on_login(data_dir: Path):
    from ai import codex_oauth

    # Existing unconfigured default DeepSeek profile + valid OAuth credential -> auto-adopts Codex profile
    config_store.save_config(data_dir, {"provider": "deepseek", "model": "deepseek-chat"})
    jwt_tok = _make_fake_jwt(
        {"https://api.openai.com/auth": {"chatgpt_account_id": "acc_auto_1", "chatgpt_plan_type": "plus"}}
    )
    codex_oauth.write_credential(
        data_dir,
        {"type": "oauth", "access": jwt_tok, "refresh": "rt_auto", "expires": 9_999_999_999_999, "account_id": "acc_auto_1"},
    )
    adopted = config_store.maybe_auto_adopt_codex_profile(data_dir, models=["gpt-6-sol", "gpt-5.6-sol"])
    assert adopted is True
    pub = config_store.get_public_config(data_dir)
    assert pub["provider"] == "codex"
    assert pub["model"] == "gpt-5.6-sol"
    assert pub["ready"] is True
    assert len(pub["profiles"]) == 2






def test_normalize_config_strips_accidental_bearer_prefix(data_dir: Path) -> None:
    saved = config_store.save_config(
        data_dir,
        {
            "provider": "deepseek",
            "api_key": "  Bearer sk-test-bearer-12345  ",
            "model": "deepseek-chat",
        },
    )
    assert saved["has_api_key"] is True
    assert saved["api_key_masked"] == "sk-t...2345"
    active = config_store.resolve_runtime_config(data_dir)
    assert active["api_key"] == "sk-test-bearer-12345"
    override_cfg = config_store.resolve_runtime_config(
        data_dir, {"provider": "deepseek", "api_key": "bearer sk-override-9999"}
    )
    assert override_cfg["api_key"] == "sk-override-9999"


def test_openai_and_gemini_models_url_strip_endpoint_suffixes() -> None:
    assert (
        llm_client._openai_models_url("https://opencode.ai/zen/v1/chat/completions")
        == "https://opencode.ai/zen/v1/models"
    )
    assert (
        llm_client._openai_models_url("https://api.openai.com/v1/responses/")
        == "https://api.openai.com/v1/models"
    )
    assert (
        llm_client._openai_models_url("https://example.com/v1/messages")
        == "https://example.com/v1/models"
    )
    assert (
        llm_client._openai_models_url("https://example.com/v1/models")
        == "https://example.com/v1/models"
    )
    assert (
        llm_client._gemini_base_url("https://generativelanguage.googleapis.com/v1beta/models/")
        == "https://generativelanguage.googleapis.com/v1beta"
    )


def test_cors_direct_presets_and_prefixed_deepseek_slugs() -> None:
    for pid in ("siliconflow", "dashscope", "openrouter"):
        preset = config_store.PROVIDER_PRESETS[pid]
        assert preset["protocol"] == "openai_compat"
        assert preset["base_url"].startswith("https://")
        assert preset["requires_key"] is True

    sf_profile = config_store.resolve_reasoning_profile(
        "siliconflow", "openai_compat", "deepseek-ai/DeepSeek-V3"
    )
    or_profile = config_store.resolve_reasoning_profile(
        "openrouter", "openai_compat", "deepseek/deepseek-chat"
    )
    official_profile = config_store.resolve_reasoning_profile(
        "deepseek", "openai_compat", "deepseek-chat"
    )
    assert sf_profile["protocol_mode"] == "openai_reasoning"
    assert or_profile["protocol_mode"] == "openai_reasoning"
    assert official_profile["protocol_mode"] == "deepseek"


def test_pages_runtime_has_static_meta_placeholder_and_direct_helpers() -> None:
    root = Path(__file__).resolve().parents[1]
    src = (root / "scripts" / "pages" / "pages_runtime.js").read_text(encoding="utf-8")
    for token in (
        "null /* __STATIC_AI_META__ */",
        "function cleanApiKey",
        "function openaiModelsUrl",
        "function codexModelsUrl",
        "function parseResponsePayloadEvents",
        "function waitForWorkerReady",
        "function buildFallbackStaticPrompt",
        "readyReject(",
    ):
        assert token in src

    ni_js = (root / "web" / "ni_ai.js").read_text(encoding="utf-8")
    assert "#ai-cfg-model-pills [data-ai-pick-model]" in ni_js
    assert "aiPickModel" in ni_js


@pytest.mark.parametrize("terminal", ["[DONE]", '{"type":"response.completed"}', '{"type":"message_stop"}'])
def test_llm_stream_finishes_at_protocol_end_without_http_close(terminal: str):
    class KeepOpenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"connected"}}]}\n\n'
            yield f"data: {terminal}\n\n".encode()
            await asyncio.Event().wait()

    async def run():
        async with _mock_async_client(lambda req: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=KeepOpenStream()
        )) as cli:
            return await asyncio.wait_for(llm_client.complete_chat(
                {"protocol": "openai_compat", "base_url": "https://opencode.ai/zen/v1",
                 "model": "synthetic-model", "api_key": "synthetic-key"},
                "test", [{"role": "user", "content": "test"}], client=cli,
            ), timeout=0.3)

    assert asyncio.run(run())["text"] == "connected"


def test_opencode_credit_error_distinguishes_payg_from_go_subscription():
    message = llm_client._friendly_http_error(
        402,
        json.dumps({"error": {"message": "Insufficient balance. This request is pay-as-you-go, billed to OpenCode Models credits. OpenCode Go covers only requests to the OpenCode Go provider."}}),
    )
    assert "按量余额不足" in message
    assert "Go 订阅" in message
    assert "HTTP 402" in message
