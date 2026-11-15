(function () {
  window.__TCM_STATIC_WEB__ = true;
  window.__TCM_BUILD_VERSION__ = "__BUILD_ID__";

  const CONFIG_STORAGE_KEY = "ni_ai_static_config_v1";
  const PATIENTS_STORAGE_KEY = "ni_ai_static_patients_v1";
  const SESSIONS_STORAGE_KEY = "ni_ai_static_sessions_v1";
  const SEEDED_STORAGE_KEY = "ni_ai_static_seeded_v1";

  const PLACEHOLDER_SVG =
    "data:image/svg+xml;utf8," +
    encodeURIComponent(
      `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="120">` +
        `<rect width="100%" height="100%" rx="8" fill="#fbf7ee" stroke="#dfd3bd"/>` +
        `<text x="50%" y="54%" text-anchor="middle" font-family="sans-serif" font-size="14" fill="#5d4e3c">网页构建版：正在按需渲染原书 PDF 扫描页…</text>` +
        `</svg>`
    );

  const FAILED_SVG =
    "data:image/svg+xml;utf8," +
    encodeURIComponent(
      `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="120">` +
        `<rect width="100%" height="100%" rx="8" fill="#fff8f6" stroke="#e4c7be"/>` +
        `<text x="50%" y="54%" text-anchor="middle" font-family="sans-serif" font-size="14" fill="#7a3e34">原书 PDF 扫描页暂未能在线渲染，下方已提供完整逐字校对原文</text>` +
        `</svg>`
    );

  function escapeAttr(val) {
    return String(val ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  window.tcmImgAttrs = function (apiUrl) {
    return `data-tcm-api-img="${escapeAttr(apiUrl)}" src="${PLACEHOLDER_SVG}"`;
  };

  function jsonResponse(body, status = 200) {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  }

  function safeParseJson(raw, fallback) {
    try {
      const parsed = JSON.parse(raw);
      return parsed == null ? fallback : parsed;
    } catch (_err) {
      return fallback;
    }
  }

  function nowIso() {
    return new Date().toISOString();
  }

  function makeId(prefix) {
    const rand = Math.random().toString(16).slice(2, 12).padEnd(10, "0");
    return `${prefix}_${rand}`;
  }

  function maskApiKey(secret) {
    const val = String(secret || "").trim();
    if (!val) return "";
    if (val.length <= 8) return "*".repeat(val.length);
    return `${val.slice(0, 4)}...${val.slice(-4)}`;
  }

  function validateBaseUrl(url, allowEmpty = false) {
    const cleaned = String(url || "").trim().replace(/\/+$/, "");
    if (!cleaned) {
      if (allowEmpty) return "";
      throw new Error("Base URL 不能为空");
    }
    let parsed;
    try {
      parsed = new URL(cleaned);
    } catch (_err) {
      throw new Error("Base URL 必须是以 http:// 或 https:// 开头的有效地址");
    }
    if ((parsed.protocol !== "http:" && parsed.protocol !== "https:") || !parsed.host) {
      throw new Error("Base URL 必须是以 http:// 或 https:// 开头的有效地址");
    }
    return cleaned;
  }

  function clampNum(value, fallback, lo, hi, asInt = false) {
    const num = Number(value);
    if (!Number.isFinite(num)) return fallback;
    const clamped = Math.max(lo, Math.min(hi, num));
    return asInt ? Math.round(clamped) : Math.round(clamped * 100) / 100;
  }

  // ── Pyodide Worker Bridge ────────────────────────────────────────────────
  const nativeFetch = window.fetch.bind(window);
  let reqSeq = 0;
  const pending = new Map();
  let workerReady = false;
  let workerFailed = null;
  let readyResolve;
  const readyPromise = new Promise((r) => {
    readyResolve = r;
  });

  const worker = new Worker("./pages_worker.js?v=__BUILD_ID__", { type: "module" });
  worker.addEventListener("message", (event) => {
    const msg = event.data || {};
    if (msg.type === "status") {
      const note = document.getElementById("dataset-note");
      if (note && !workerReady) note.textContent = `构建版 · ${msg.text}`;
      return;
    }
    if (msg.type === "ready") {
      workerReady = true;
      readyResolve();
      return;
    }
    if (msg.type === "init_error") {
      workerFailed = msg.error || "引擎初始化失败";
      const note = document.getElementById("dataset-note");
      if (note) note.textContent = `离线引擎初始化失败：${workerFailed}`;
      for (const [, p] of pending) {
        p.reject(new Error(workerFailed));
      }
      pending.clear();
      return;
    }
    if (msg.type === "response") {
      const item = pending.get(msg.id);
      if (!item) return;
      pending.delete(msg.id);
      try {
        item.resolve(JSON.parse(msg.raw));
      } catch (err) {
        item.reject(err);
      }
    }
  });

  worker.addEventListener("error", (err) => {
    workerFailed = err?.message || "Web Worker 加载失败";
    for (const [, p] of pending) p.reject(new Error(workerFailed));
    pending.clear();
  });

  async function callWorker(apiUrl, method = "GET", bodyPayload = null) {
    if (workerFailed) throw new Error(workerFailed);
    if (!workerReady) await readyPromise;
    const id = ++reqSeq;
    const bodyStr =
      bodyPayload == null
        ? ""
        : typeof bodyPayload === "string"
        ? bodyPayload
        : JSON.stringify(bodyPayload);
    return await new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      worker.postMessage({ type: "api", id, url: apiUrl, method, body: bodyStr });
    });
  }

  let presetsPromise = null;
  async function getPresetsAndStyles() {
    if (!presetsPromise) {
      presetsPromise = callWorker("/api/ai/presets-and-styles", "POST", {})
        .then((res) => res.body)
        .catch((err) => {
          presetsPromise = null;
          throw err;
        });
    }
    return presetsPromise;
  }

  // ── Browser-Local BYOK AI Configuration (localStorage) ──────────────────
  function loadStoredRawConfig(meta) {
    const base = { ...(meta.defaults || {}) };
    const raw = localStorage.getItem(CONFIG_STORAGE_KEY);
    if (!raw) return base;
    const loaded = safeParseJson(raw, {});
    if (typeof loaded !== "object" || Array.isArray(loaded)) return base;
    return { ...base, ...loaded };
  }

  function normalizeClientConfig(payload, existing, meta) {
    const presetsList = Array.isArray(meta.presets) ? meta.presets : [];
    const presetMap = new Map(presetsList.map((p) => [p.id, p]));
    const stylesSet = new Set((meta.styles || []).map((s) => s.id));

    const providerId = String(payload?.provider || existing.provider || "deepseek")
      .trim()
      .toLowerCase();
    const preset = presetMap.get(providerId);
    if (!preset) {
      throw new Error(`不支持的提供商: ${providerId}`);
    }

    const protocol = String(payload?.protocol || preset.protocol || "openai_compat")
      .trim()
      .toLowerCase();
    if (!["openai_compat", "gemini", "anthropic"].includes(protocol)) {
      throw new Error(`不支持的协议类型: ${protocol}`);
    }

    let rawUrl = payload?.base_url;
    if (rawUrl == null) {
      rawUrl =
        providerId === existing.provider && existing.base_url
          ? existing.base_url
          : preset.base_url || "";
    }
    const baseUrl = validateBaseUrl(
      rawUrl,
      providerId === "custom" && !String(rawUrl || "").trim()
    );

    const model = String(
      payload?.model != null
        ? payload.model
        : providerId === existing.provider && existing.model
        ? existing.model
        : preset.default_model || ""
    ).trim();

    let apiKey = String(existing.api_key || "").trim();
    if (payload?.clear_api_key) {
      apiKey = "";
    } else if (typeof payload?.api_key === "string" && payload.api_key.trim()) {
      apiKey = payload.api_key.trim();
    }

    let style = String(payload?.persona_style || existing.persona_style || "master_balanced").trim();
    if (stylesSet.size && !stylesSet.has(style)) {
      style = "master_balanced";
    }

    return {
      provider: providerId,
      protocol,
      base_url: baseUrl,
      model,
      api_key: apiKey,
      persona_style: style,
      temperature: clampNum(payload?.temperature, existing.temperature ?? 0.45, 0.0, 1.5, false),
      max_tokens: clampNum(payload?.max_tokens, existing.max_tokens ?? 4096, 256, 16384, true),
      timeout_sec: clampNum(payload?.timeout_sec, existing.timeout_sec ?? 120, 10, 300, true),
    };
  }

  function toPublicConfig(resolved, meta) {
    const presetMap = new Map((meta.presets || []).map((p) => [p.id, p]));
    const preset = presetMap.get(resolved.provider) || {};
    const requiresKey = preset.requires_key !== false;
    const secret = String(resolved.api_key || "").trim();
    const ready = Boolean(resolved.base_url && resolved.model && (secret || !requiresKey));
    const { api_key: _secret, ...rest } = resolved;
    return {
      ...rest,
      key_source: secret ? "browser" : "none",
      requires_key: requiresKey,
      ready,
      has_api_key: Boolean(secret),
      api_key_masked: maskApiKey(secret),
      presets: meta.presets || [],
      styles: meta.styles || [],
    };
  }

  function toRuntimeConfig(meta, override = null) {
    const saved = loadStoredRawConfig(meta);
    const merged = override ? normalizeClientConfig(override, saved, meta) : saved;
    const presetMap = new Map((meta.presets || []).map((p) => [p.id, p]));
    const preset = presetMap.get(merged.provider) || {};
    const requiresKey = preset.requires_key !== false;
    const secret = String(merged.api_key || "").trim();
    const ready = Boolean(merged.base_url && merged.model && (secret || !requiresKey));
    return {
      ...merged,
      api_key: secret,
      key_source: secret ? "browser" : "none",
      requires_key: requiresKey,
      ready,
    };
  }

  // ── Direct Browser LLM Client (BYOK CORS + Zero-Key Fallback) ───────────
  function openaiEndpoint(baseUrl, suffix) {
    const clean = String(baseUrl || "").replace(/\/+$/, "");
    return clean.endsWith(suffix) ? clean : `${clean}${suffix}`;
  }

  function anthropicMessagesUrl(baseUrl) {
    const clean = String(baseUrl || "").replace(/\/+$/, "");
    if (clean.endsWith("/messages")) return clean;
    if (clean.endsWith("/v1")) return `${clean}/messages`;
    return `${clean}/v1/messages`;
  }

  function ollamaTagsUrl(baseUrl) {
    const u = new URL(baseUrl);
    return `${u.protocol}//${u.host}/api/tags`;
  }

  function friendlyHttpError(status, bodyText) {
    let detail = "";
    try {
      const parsed = JSON.parse(bodyText);
      const err = parsed?.error && typeof parsed.error === "object" ? parsed.error : null;
      detail = String(err?.message || err?.detail || parsed?.message || parsed?.detail || "");
    } catch (_err) {
      detail = "";
    }
    detail = (detail || bodyText || "").trim().split(/\r?\n/)[0].slice(0, 240);
    if (detail.toLowerCase().includes("x-opencode-session") || String(bodyText || "").toLowerCase().includes("x-opencode-session")) {
      return (
        `OpenCode Go 订阅网关拒绝了非编程代理请求 (HTTP ${status})：${detail}。` +
        `（提示：OpenCode Go 仅限编程代理工具使用；请改用 DeepSeek、OpenAI 兼容网关、Gemini、Claude、OpenCode Zen 通用按量接口，或关闭 Key 使用本地免 Key 推演）`
      );
    }
    if (status === 401) return `认证失败 (HTTP 401)：请检查 API Key 是否有效或有余额。${detail}`.trim();
    if (status === 403) return `权限或区域受限 (HTTP 403)：${detail}`.trim();
    if (status === 404) return `接口或模型不存在 (HTTP 404)：请检查 Base URL 与模型名称。${detail}`.trim();
    if (status === 429) return `请求频率或额度受限 (HTTP 429)：${detail}`.trim();
    return `上游模型返回错误 (HTTP ${status})：${detail}`.trim();
  }

  function prepareUpstreamRequest(cfg, systemPrompt, messages, stream) {
    const protocol = cfg.protocol || "openai_compat";
    if (protocol === "gemini") {
      const action = stream ? "streamGenerateContent?alt=sse" : "generateContent";
      return {
        url: `${String(cfg.base_url).replace(/\/+$/, "")}/models/${encodeURIComponent(cfg.model)}:${action}`,
        headers: {
          "Content-Type": "application/json",
          "x-goog-api-key": cfg.api_key || "",
        },
        body: {
          systemInstruction: { parts: [{ text: systemPrompt }] },
          contents: messages.map((m) => ({
            role: m.role === "assistant" ? "model" : "user",
            parts: [{ text: m.content }],
          })),
          generationConfig: {
            temperature: cfg.temperature ?? 0.45,
            maxOutputTokens: cfg.max_tokens ?? 4096,
          },
        },
      };
    }
    if (protocol === "anthropic") {
      return {
        url: anthropicMessagesUrl(cfg.base_url),
        headers: {
          "Content-Type": "application/json",
          "x-api-key": cfg.api_key || "",
          "anthropic-version": "2023-06-01",
          "anthropic-dangerous-direct-browser-access": "true",
        },
        body: {
          model: cfg.model,
          system: systemPrompt,
          messages: messages.map((m) => ({
            role: m.role === "assistant" ? "assistant" : "user",
            content: m.content,
          })),
          max_tokens: cfg.max_tokens ?? 4096,
          temperature: cfg.temperature ?? 0.45,
          stream: Boolean(stream),
        },
      };
    }
    const headers = { "Content-Type": "application/json" };
    if (cfg.api_key) {
      headers.Authorization = `Bearer ${cfg.api_key}`;
    }
    return {
      url: openaiEndpoint(cfg.base_url, "/chat/completions"),
      headers,
      body: {
        model: cfg.model,
        messages: [{ role: "system", content: systemPrompt }, ...messages],
        stream: Boolean(stream),
        temperature: cfg.temperature ?? 0.45,
        max_tokens: cfg.max_tokens ?? 4096,
      },
    };
  }

  function parseUpstreamEvents(protocol, chunk, eventName = "") {
    const events = [];
    if (!chunk || typeof chunk !== "object") return events;
    if (protocol === "gemini") {
      if (chunk.error) {
        throw new Error(`Gemini 错误：${chunk.error.message || JSON.stringify(chunk.error)}`);
      }
      for (const cand of chunk.candidates || []) {
        for (const part of cand?.content?.parts || []) {
          if (!part?.text) continue;
          events.push({ type: part.thought ? "reasoning" : "delta", text: String(part.text) });
        }
      }
      if (chunk.usageMetadata) events.push({ type: "usage", usage: chunk.usageMetadata });
      return events;
    }
    if (protocol === "anthropic") {
      if (chunk.__full) {
        for (const block of chunk.content || []) {
          if (block?.type === "thinking" && block.thinking) {
            events.push({ type: "reasoning", text: String(block.thinking) });
          } else if (block?.text) {
            events.push({ type: "delta", text: String(block.text) });
          }
        }
        if (chunk.usage) events.push({ type: "usage", usage: chunk.usage });
        return events;
      }
      const kind = chunk.type || eventName || "";
      if (kind === "error") {
        throw new Error(`Claude 流错误：${chunk?.error?.message || JSON.stringify(chunk.error || chunk)}`);
      }
      if (kind === "content_block_delta") {
        const d = chunk.delta || {};
        if (d.type === "thinking_delta" && d.thinking) {
          events.push({ type: "reasoning", text: String(d.thinking) });
        } else if (d.type === "text_delta" && d.text) {
          events.push({ type: "delta", text: String(d.text) });
        }
      } else if (kind === "message_delta" && chunk.usage) {
        events.push({ type: "usage", usage: chunk.usage });
      }
      return events;
    }
    // openai_compat
    if (chunk.__full) {
      const msg = chunk?.choices?.[0]?.message || {};
      if (msg.reasoning_content) events.push({ type: "reasoning", text: String(msg.reasoning_content) });
      if (msg.content) events.push({ type: "delta", text: String(msg.content) });
      if (chunk.usage) events.push({ type: "usage", usage: chunk.usage });
      return events;
    }
    if (chunk.error) {
      throw new Error(`模型流中断：${chunk.error?.message || JSON.stringify(chunk.error)}`);
    }
    for (const choice of chunk.choices || []) {
      const d = choice?.delta || {};
      const reason = d.reasoning_content || d.reasoning || "";
      if (reason) events.push({ type: "reasoning", text: String(reason) });
      if (d.content) events.push({ type: "delta", text: String(d.content) });
    }
    if (chunk.usage) events.push({ type: "usage", usage: chunk.usage });
    return events;
  }

  async function* iterUpstreamEvents(cfg, systemPrompt, messages, signal) {
    const req = prepareUpstreamRequest(cfg, systemPrompt, messages, true);
    const resp = await nativeFetch(req.url, {
      method: "POST",
      headers: req.headers,
      body: JSON.stringify(req.body),
      signal,
    });
    if (!resp.ok) {
      const errText = await resp.text().catch(() => "");
      throw new Error(friendlyHttpError(resp.status, errText));
    }
    const ctype = (resp.headers.get("content-type") || "").toLowerCase();
    if (ctype.includes("application/json") && !ctype.includes("text/event-stream")) {
      const full = await resp.json();
      if (full && typeof full === "object") full.__full = true;
      for (const ev of parseUpstreamEvents(cfg.protocol, full)) yield ev;
      return;
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buf = "";
    let eventName = "";
    let dataLines = [];

    const flushEvent = () => {
      if (!dataLines.length) {
        eventName = "";
        return [];
      }
      const payloadStr = dataLines.join("\n").trim();
      const evName = eventName;
      dataLines = [];
      eventName = "";
      if (!payloadStr || payloadStr === "[DONE]") return [];
      const parsed = safeParseJson(payloadStr, null);
      if (!parsed || typeof parsed !== "object") return [];
      return parseUpstreamEvents(cfg.protocol, parsed, evName);
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nlIdx;
      while ((nlIdx = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nlIdx).replace(/\r$/, "");
        buf = buf.slice(nlIdx + 1);
        if (!line) {
          for (const ev of flushEvent()) yield ev;
          continue;
        }
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).replace(/^ /, ""));
        }
      }
    }
    if (buf.trim()) {
      const line = buf.replace(/\r$/, "");
      if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
    }
    for (const ev of flushEvent()) yield ev;
  }

  async function runDirectModels(cfg, meta) {
    const preset = (meta.presets || []).find((p) => p.id === cfg.provider) || {};
    const suggested = Array.isArray(preset.suggested_models) ? [...preset.suggested_models] : [];
    const baseUrl = String(cfg.base_url || "").trim().replace(/\/+$/, "");
    if (!baseUrl || cfg.protocol === "anthropic") {
      return { models: suggested, source: "preset" };
    }
    try {
      if (cfg.provider === "ollama") {
        const r = await nativeFetch(ollamaTagsUrl(baseUrl));
        if (r.ok) {
          const data = await r.json();
          const names = (data.models || []).map((m) => String(m?.name || "")).filter(Boolean);
          if (names.length) return { models: names, source: "live" };
        }
      }
      if (cfg.protocol === "gemini") {
        if (!cfg.api_key) return { models: suggested, source: "preset" };
        const r = await nativeFetch(`${baseUrl}/models`, {
          headers: { "x-goog-api-key": cfg.api_key },
        });
        if (!r.ok) throw new Error(friendlyHttpError(r.status, await r.text().catch(() => "")));
        const data = await r.json();
        const items = (data.models || [])
          .filter((m) => (m.supportedGenerationMethods || []).includes("generateContent"))
          .map((m) => String(m.name || "").replace(/^models\//, ""))
          .filter(Boolean);
        return { models: items.length ? Array.from(new Set(items)).sort() : suggested, source: items.length ? "live" : "preset" };
      }
      const headers = cfg.api_key ? { Authorization: `Bearer ${cfg.api_key}` } : {};
      const r = await nativeFetch(openaiEndpoint(baseUrl, "/models"), { headers });
      if (!r.ok) throw new Error(friendlyHttpError(r.status, await r.text().catch(() => "")));
      const data = await r.json();
      const ids = (data.data || []).map((m) => String(m?.id || "")).filter(Boolean);
      return { models: ids.length ? Array.from(new Set(ids)).sort() : suggested, source: ids.length ? "live" : "preset" };
    } catch (err) {
      if (suggested.length) {
        return { models: suggested, source: "preset", note: String(err?.message || err) };
      }
      throw new Error(`获取模型列表失败：${err?.message || "浏览器跨域受限或接口不可达"}`);
    }
  }

  async function runDirectTest(cfg) {
    if (!cfg.base_url) throw new Error("请先填写模型 Base URL");
    if (!cfg.model) throw new Error("请先选择或填写模型名称");
    if (cfg.requires_key && !cfg.api_key) throw new Error("当前模型未配置 API Key");

    const started = performance.now();
    const probeCfg = { ...cfg, max_tokens: 32, temperature: 0.0 };
    const req = prepareUpstreamRequest(
      probeCfg,
      "你是连通性测试助手。请只回复“已连通”三个字。",
      [{ role: "user", content: "测试连通" }],
      false
    );
    let resp;
    try {
      resp = await nativeFetch(req.url, {
        method: "POST",
        headers: req.headers,
        body: JSON.stringify(req.body),
      });
    } catch (_err) {
      const hint =
        cfg.provider === "ollama"
          ? "Ollama 默认需设置 OLLAMA_ORIGINS=* 允许网页端直连，或使用本地 Python 服务版"
          : "浏览器端直连受网络或目标网关 CORS 策略限制，您仍可直接切回零 Key 离线推演";
      throw new Error(`无法从浏览器直连模型接口：${hint}。`);
    }
    if (!resp.ok) {
      throw new Error(friendlyHttpError(resp.status, await resp.text().catch(() => "")));
    }
    const full = await resp.json();
    full.__full = true;
    const events = parseUpstreamEvents(cfg.protocol, full);
    const preview = events
      .filter((e) => e.type === "delta")
      .map((e) => e.text)
      .join("")
      .trim()
      .slice(0, 80);
    return {
      ok: true,
      provider: cfg.provider,
      model: cfg.model,
      latency_ms: Math.round(performance.now() - started),
      reply_preview: preview,
    };
  }

  // ── Browser-Local Patient Profiles & Isolated Consult History ───────────
  function ensureHistorySeeded() {
    let patients = safeParseJson(localStorage.getItem(PATIENTS_STORAGE_KEY) || "null", null);
    let sessions = safeParseJson(localStorage.getItem(SESSIONS_STORAGE_KEY) || "null", null);
    const seeded = localStorage.getItem(SEEDED_STORAGE_KEY) === "1";
    if (!Array.isArray(patients)) patients = [];
    if (!Array.isArray(sessions)) sessions = [];

    if (!seeded && patients.length === 0) {
      const now = nowIso();
      const patId = makeId("pat");
      const sesId = makeId("ses");
      patients.push({
        id: patId,
        name: "默认问诊人",
        gender: "",
        age: "",
        notes: "网页版数据保存在当前浏览器本地，每位问诊人独立保存历史",
        created_at: now,
        updated_at: now,
      });
      sessions.push({
        id: sesId,
        patient_id: patId,
        title: "新开问诊",
        intake: {},
        pinned_entity: null,
        turns: [],
        latest_packet: null,
        primary_formula: "",
        summary_text: "待录入症状",
        created_at: now,
        updated_at: now,
      });
      localStorage.setItem(SEEDED_STORAGE_KEY, "1");
      saveHistoryStore(patients, sessions);
    }
    return { patients, sessions };
  }

  function saveHistoryStore(patients, sessions) {
    try {
      localStorage.setItem(PATIENTS_STORAGE_KEY, JSON.stringify(patients));
      localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify(sessions));
    } catch (_err) {
      // Compact older session packets if browser localStorage quota is tight
      const trimmed = sessions.map((s, idx) =>
        idx < sessions.length - 6 ? { ...s, latest_packet: null } : s
      );
      localStorage.setItem(PATIENTS_STORAGE_KEY, JSON.stringify(patients));
      localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify(trimmed));
    }
  }

  function sortByUpdatedDesc(items) {
    return [...items].sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
  }

  function buildPatientList(patients, sessions) {
    return sortByUpdatedDesc(patients).map((p) => {
      const ps = sortByUpdatedDesc(sessions.filter((s) => s.patient_id === p.id));
      const latestWithFormula = ps.find((s) => s.primary_formula);
      return {
        ...p,
        session_count: ps.length,
        latest_formula: latestWithFormula ? latestWithFormula.primary_formula : "",
      };
    });
  }

  function buildSessionSummaries(sessions, patientId) {
    return sortByUpdatedDesc(sessions.filter((s) => s.patient_id === patientId)).map((s) => ({
      id: s.id,
      patient_id: s.patient_id,
      title: s.title,
      primary_formula: s.primary_formula || "",
      summary_text: s.summary_text || "",
      turn_count: Array.isArray(s.turns) ? s.turns.filter((t) => t && t.role === "user").length : 0,
      created_at: s.created_at,
      updated_at: s.updated_at,
    }));
  }

  function deriveSessionMeta(explicitTitle, existingTitle, intake, turns, latestPacket, pinnedEntity) {
    let primaryFormula = "";
    if (latestPacket && typeof latestPacket === "object") {
      const matched = (latestPacket.case_packet || latestPacket).matched_formulas || [];
      if (matched.length && matched[0]?.name) {
        primaryFormula = String(matched[0].name);
      }
    }
    const firstUserTurn = (turns || []).find((t) => t && t.role === "user" && t.query);
    const firstQ = String(firstUserTurn?.query || "").trim();
    const intakeQ = String(intake?.query || "").trim();
    const pinnedName = String(pinnedEntity?.name || "").trim();
    const summaryText = (firstQ || intakeQ || pinnedName || "待录入症状").replace(/\n/g, " ").slice(0, 90);

    let title;
    if (typeof explicitTitle === "string" && explicitTitle.trim()) {
      title = explicitTitle.trim().slice(0, 60);
    } else if (existingTitle && existingTitle !== "新开问诊") {
      title = existingTitle;
    } else {
      const head = (firstQ || intakeQ || pinnedName).replace(/\n/g, " ").trim();
      if (head && primaryFormula) title = `${head.slice(0, 14)} · ${primaryFormula}`;
      else if (head) title = head.slice(0, 24);
      else if (primaryFormula) title = primaryFormula;
      else title = "新开问诊";
    }
    return {
      title: title.slice(0, 60),
      primary_formula: primaryFormula.slice(0, 40),
      summary_text: summaryText,
    };
  }

  async function handleHistoryApi(apiPath, method, body) {
    const store = ensureHistorySeeded();

    if (apiPath === "/api/ai/patients" && method === "GET") {
      return jsonResponse({ patients: buildPatientList(store.patients, store.sessions) });
    }
    if (apiPath === "/api/ai/patients" && method === "POST") {
      const cleanName = String(body?.name || "").trim();
      if (!cleanName) return jsonResponse({ detail: "问诊人姓名/称呼不能为空" }, 400);
      const now = nowIso();
      const patId = makeId("pat");
      const sesId = makeId("ses");
      const patient = {
        id: patId,
        name: cleanName.slice(0, 40),
        gender: String(body?.gender || "").trim().slice(0, 16),
        age: String(body?.age || "").trim().slice(0, 24),
        notes: String(body?.notes || "").trim().slice(0, 400),
        session_count: 1,
        latest_formula: "",
        created_at: now,
        updated_at: now,
      };
      const session = {
        id: sesId,
        patient_id: patId,
        title: "新开问诊",
        intake: {},
        pinned_entity: null,
        turns: [],
        latest_packet: null,
        primary_formula: "",
        summary_text: "待录入症状",
        created_at: now,
        updated_at: now,
      };
      store.patients.push(patient);
      store.sessions.push(session);
      saveHistoryStore(store.patients, store.sessions);
      return jsonResponse({
        patient,
        initial_session: session,
        patients: buildPatientList(store.patients, store.sessions),
      });
    }

    let m = apiPath.match(/^\/api\/ai\/patients\/([^/]+)\/update$/);
    if (m && method === "POST") {
      const pid = decodeURIComponent(m[1]);
      const idx = store.patients.findIndex((p) => p.id === pid);
      if (idx < 0) return jsonResponse({ detail: "未找到该问诊人" }, 404);
      const cur = store.patients[idx];
      const nextName = String(body?.name != null ? body.name : cur.name).trim();
      if (!nextName) return jsonResponse({ detail: "问诊人姓名/称呼不能为空" }, 400);
      store.patients[idx] = {
        ...cur,
        name: nextName.slice(0, 40),
        gender: String(body?.gender != null ? body.gender : cur.gender).trim().slice(0, 16),
        age: String(body?.age != null ? body.age : cur.age).trim().slice(0, 24),
        notes: String(body?.notes != null ? body.notes : cur.notes).trim().slice(0, 400),
        updated_at: nowIso(),
      };
      saveHistoryStore(store.patients, store.sessions);
      const list = buildPatientList(store.patients, store.sessions);
      return jsonResponse({ patient: list.find((p) => p.id === pid) || store.patients[idx], patients: list });
    }

    m = apiPath.match(/^\/api\/ai\/patients\/([^/]+)\/delete$/);
    if (m && method === "POST") {
      const pid = decodeURIComponent(m[1]);
      const before = store.patients.length;
      store.patients = store.patients.filter((p) => p.id !== pid);
      if (store.patients.length === before) return jsonResponse({ detail: "未找到该问诊人" }, 404);
      store.sessions = store.sessions.filter((s) => s.patient_id !== pid);
      saveHistoryStore(store.patients, store.sessions);
      return jsonResponse({ deleted: pid, patients: buildPatientList(store.patients, store.sessions) });
    }

    m = apiPath.match(/^\/api\/ai\/patients\/([^/]+)\/sessions$/);
    if (m && method === "GET") {
      const pid = decodeURIComponent(m[1]);
      const pat = buildPatientList(store.patients, store.sessions).find((p) => p.id === pid);
      if (!pat) return jsonResponse({ detail: "未找到该问诊人" }, 404);
      return jsonResponse({ patient: pat, sessions: buildSessionSummaries(store.sessions, pid) });
    }
    if (m && method === "POST") {
      const pid = decodeURIComponent(m[1]);
      const pat = store.patients.find((p) => p.id === pid);
      if (!pat) return jsonResponse({ detail: "未找到该问诊人" }, 404);
      const now = nowIso();
      const intake = body?.intake && typeof body.intake === "object" ? body.intake : {};
      const title = String(body?.title || "").trim().slice(0, 60) || "新开问诊";
      const summary = String(intake.query || "").trim().slice(0, 80) || "待录入症状";
      const session = {
        id: makeId("ses"),
        patient_id: pid,
        title,
        intake,
        pinned_entity: body?.pinned_entity || null,
        turns: [],
        latest_packet: null,
        primary_formula: "",
        summary_text: summary,
        created_at: now,
        updated_at: now,
      };
      pat.updated_at = now;
      store.sessions.push(session);
      saveHistoryStore(store.patients, store.sessions);
      return jsonResponse({ session, sessions: buildSessionSummaries(store.sessions, pid) });
    }

    m = apiPath.match(/^\/api\/ai\/sessions\/([^/]+)$/);
    if (m && method === "GET") {
      const sid = decodeURIComponent(m[1]);
      const ses = store.sessions.find((s) => s.id === sid);
      if (!ses) return jsonResponse({ detail: "未找到该问诊历史记录" }, 404);
      return jsonResponse({ session: ses });
    }

    m = apiPath.match(/^\/api\/ai\/sessions\/([^/]+)\/save$/);
    if (m && method === "POST") {
      const sid = decodeURIComponent(m[1]);
      const idx = store.sessions.findIndex((s) => s.id === sid);
      if (idx < 0) return jsonResponse({ detail: "未找到该问诊历史记录" }, 404);
      const cur = store.sessions[idx];
      const nextIntake = body?.intake && typeof body.intake === "object" ? body.intake : cur.intake || {};
      const updatePinned = Boolean(body?.update_pinned || Object.prototype.hasOwnProperty.call(body || {}, "pinned_entity"));
      const updatePacket = Boolean(body?.update_packet || Object.prototype.hasOwnProperty.call(body || {}, "latest_packet"));
      const nextPinned = updatePinned ? body.pinned_entity ?? null : cur.pinned_entity;
      const rawTurns = Array.isArray(body?.turns) ? body.turns : cur.turns || [];
      const slimTurns = rawTurns
        .slice(-40)
        .filter((t) => t && typeof t === "object")
        .map(({ packet: _p, streaming: _st, ...rest }) => rest);
      const nextPacket = updatePacket ? body.latest_packet ?? null : cur.latest_packet;
      const metaDerived = deriveSessionMeta(
        body?.title,
        cur.title,
        nextIntake,
        slimTurns,
        nextPacket,
        nextPinned
      );
      const now = nowIso();
      const updated = {
        ...cur,
        title: metaDerived.title,
        intake: nextIntake,
        pinned_entity: nextPinned,
        turns: slimTurns,
        latest_packet: nextPacket,
        primary_formula: metaDerived.primary_formula,
        summary_text: metaDerived.summary_text,
        updated_at: now,
      };
      store.sessions[idx] = updated;
      const pat = store.patients.find((p) => p.id === updated.patient_id);
      if (pat) pat.updated_at = now;
      saveHistoryStore(store.patients, store.sessions);
      return jsonResponse({
        session: updated,
        sessions: buildSessionSummaries(store.sessions, updated.patient_id),
      });
    }

    m = apiPath.match(/^\/api\/ai\/sessions\/([^/]+)\/delete$/);
    if (m && method === "POST") {
      const sid = decodeURIComponent(m[1]);
      const target = store.sessions.find((s) => s.id === sid);
      if (!target) return jsonResponse({ detail: "未找到该问诊历史记录" }, 404);
      store.sessions = store.sessions.filter((s) => s.id !== sid);
      saveHistoryStore(store.patients, store.sessions);
      return jsonResponse({
        deleted: sid,
        patient_id: target.patient_id,
        sessions: buildSessionSummaries(store.sessions, target.patient_id),
      });
    }

    return null;
  }

  // ── Unified /api/ai/* Static Router ─────────────────────────────────────
  async function handleStaticAiApi(apiUrl, method, body, signal) {
    const u = new URL(apiUrl, location.origin);
    const apiPath = u.pathname;

    if (apiPath.startsWith("/api/ai/patients") || apiPath.startsWith("/api/ai/sessions")) {
      const res = await handleHistoryApi(apiPath, method, body);
      if (res) return res;
    }

    const meta = await getPresetsAndStyles();

    if (apiPath === "/api/ai/config" && method === "GET") {
      return jsonResponse(toPublicConfig(toRuntimeConfig(meta), meta));
    }

    if (apiPath === "/api/ai/config" && method === "POST") {
      try {
        const existing = loadStoredRawConfig(meta);
        const next = normalizeClientConfig(body || {}, existing, meta);
        localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(next));
        return jsonResponse(toPublicConfig(toRuntimeConfig(meta), meta));
      } catch (err) {
        return jsonResponse({ detail: String(err?.message || err) }, 400);
      }
    }

    if (apiPath === "/api/ai/models" && method === "POST") {
      try {
        const cfg = toRuntimeConfig(meta, body && Object.keys(body).length ? body : null);
        return jsonResponse(await runDirectModels(cfg, meta));
      } catch (err) {
        return jsonResponse({ detail: String(err?.message || err) }, 400);
      }
    }

    if (apiPath === "/api/ai/test" && method === "POST") {
      try {
        const cfg = toRuntimeConfig(meta, body && Object.keys(body).length ? body : null);
        return jsonResponse(await runDirectTest(cfg));
      } catch (err) {
        return jsonResponse({ detail: String(err?.message || err) }, 400);
      }
    }

    if (apiPath === "/api/ai/chat/stream" && method === "POST") {
      const cfg = toRuntimeConfig(meta, body?.config_override || null);
      const style = String(body?.style || cfg.persona_style || "master_balanced");
      const prepRes = await callWorker("/api/ai/prepare-prompt", "POST", { ...body, style });
      if ((prepRes.status || 200) >= 400) {
        return jsonResponse(prepRes.body, prepRes.status);
      }
      const { packet, system_prompt, messages, offline_reply } = prepRes.body;
      const useOffline = Boolean(body?.offline || !cfg.ready);
      const mode = useOffline ? "offline" : "live";

      const encoder = new TextEncoder();
      const sendFrame = (controller, evName, payloadObj) => {
        controller.enqueue(
          encoder.encode(`event: ${evName}\ndata: ${JSON.stringify(payloadObj)}\n\n`)
        );
      };

      const stream = new ReadableStream({
        async start(controller) {
          try {
            sendFrame(controller, "context", {
              mode,
              provider: cfg.provider,
              model: cfg.model,
              style,
              packet,
            });

            if (useOffline) {
              for (let idx = 0; idx < offline_reply.length; idx += 80) {
                sendFrame(controller, "delta", { text: offline_reply.slice(idx, idx + 80) });
              }
              const citeRes = await callWorker("/api/ai/extract-refs", "POST", {
                text: offline_reply,
                citations: packet.citations || [],
              });
              sendFrame(controller, "done", {
                mode: "offline",
                provider: cfg.provider,
                model: cfg.model,
                style,
                text: offline_reply,
                reasoning: "",
                usage: {},
                cited: citeRes.body || [],
              });
              controller.close();
              return;
            }

            let textParts = [];
            let reasoningParts = [];
            let usage = {};
            try {
              for await (const ev of iterUpstreamEvents(cfg, system_prompt, messages, signal)) {
                if (ev.type === "reasoning") {
                  reasoningParts.push(ev.text);
                  sendFrame(controller, "reasoning", { text: ev.text });
                } else if (ev.type === "delta") {
                  textParts.push(ev.text);
                  sendFrame(controller, "delta", { text: ev.text });
                } else if (ev.type === "usage") {
                  usage = ev.usage || {};
                }
              }
            } catch (err) {
              if (err?.name === "AbortError") {
                controller.close();
                return;
              }
              const detail = String(err?.message || "浏览器直连模型受限或网络异常");
              sendFrame(controller, "error", { detail, fallback_text: offline_reply });
              const citeRes = await callWorker("/api/ai/extract-refs", "POST", {
                text: offline_reply,
                citations: packet.citations || [],
              });
              sendFrame(controller, "done", {
                mode: "offline_fallback",
                error: detail,
                text: offline_reply,
                reasoning: reasoningParts.join(""),
                usage,
                cited: citeRes.body || [],
              });
              controller.close();
              return;
            }

            const fullText = textParts.join("");
            const citeRes = await callWorker("/api/ai/extract-refs", "POST", {
              text: fullText,
              citations: packet.citations || [],
            });
            sendFrame(controller, "done", {
              mode: "live",
              provider: cfg.provider,
              model: cfg.model,
              style,
              text: fullText,
              reasoning: reasoningParts.join(""),
              usage,
              cited: citeRes.body || [],
            });
            controller.close();
          } catch (fatalErr) {
            controller.error(fatalErr);
          }
        },
      });

      return new Response(stream, {
        status: 200,
        headers: {
          "Content-Type": "text/event-stream; charset=utf-8",
          "Cache-Control": "no-store",
        },
      });
    }

    // Remaining AI routes (/api/ai/packet, /api/ai/chat) go straight to Pyodide
    const rpc = await callWorker(apiUrl, method, body);
    return jsonResponse(rpc.body, rpc.status || 200);
  }

  // ── Intercept All Same-Origin /api/* Requests ───────────────────────────
  window.fetch = async function (input, init) {
    const rawUrl = typeof input === "string" ? input : input?.url || "";
    let u;
    try {
      u = new URL(rawUrl, location.href);
    } catch (_err) {
      return nativeFetch(input, init);
    }
    const apiIdx = u.pathname.indexOf("/api/");
    if (u.origin === location.origin && apiIdx >= 0) {
      const apiUrl = u.pathname.slice(apiIdx) + u.search;
      const method = String(init?.method || (typeof input !== "string" && input?.method) || "GET").toUpperCase();
      let body = null;
      if (init?.body && typeof init.body === "string") {
        body = safeParseJson(init.body, {});
      }
      if (apiUrl.startsWith("/api/ai/")) {
        return await handleStaticAiApi(apiUrl, method, body, init?.signal);
      }
      const parsed = await callWorker(apiUrl, method, body);
      return jsonResponse(parsed.body, parsed.status || 200);
    }
    return nativeFetch(input, init);
  };

  // ── On-demand PDF.js Page Image Renderer (<img data-tcm-api-img="...">) ─
  let pdfjsPromise = null;
  const pdfDocCache = new Map();
  const pageDataUrlCache = new Map();

  async function getPdfJs() {
    if (!pdfjsPromise) {
      pdfjsPromise = import("./runtime/pdfjs/pdf.min.mjs").then((lib) => {
        lib.GlobalWorkerOptions.workerSrc = new URL("./runtime/pdfjs/pdf.worker.min.mjs", location.href).href;
        return lib;
      });
    }
    return pdfjsPromise;
  }

  async function renderApiImageToImg(img) {
    const apiUrl = img.dataset.tcmApiImg;
    if (!apiUrl || img.dataset.tcmRendering === "1" || img.dataset.tcmRendered === apiUrl) return;
    img.dataset.tcmRendering = "1";
    try {
      if (pageDataUrlCache.has(apiUrl)) {
        img.src = pageDataUrlCache.get(apiUrl);
        img.dataset.tcmRendered = apiUrl;
        return;
      }
      const metaRes = await window.fetch(`/api/__pdf-source?url=${encodeURIComponent(apiUrl)}`);
      if (!metaRes.ok) throw new Error("未找到原书 PDF");
      const meta = await metaRes.json();
      const relUrl = "./" + meta.relative_path.split("/").map(encodeURIComponent).join("/");
      const pdfjs = await getPdfJs();
      let docPromise = pdfDocCache.get(relUrl);
      if (!docPromise) {
        docPromise = pdfjs.getDocument({ url: relUrl }).promise;
        pdfDocCache.set(relUrl, docPromise);
      }
      const doc = await docPromise;
      const page = await doc.getPage(Number(meta.pdf_page) || 1);
      const viewport = page.getViewport({ scale: 1.55 });
      const canvas = document.createElement("canvas");
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      const ctx = canvas.getContext("2d", { alpha: false });
      await page.render({ canvasContext: ctx, viewport }).promise;
      const dataUrl = canvas.toDataURL("image/png");
      if (pageDataUrlCache.size >= 24) {
        const firstKey = pageDataUrlCache.keys().next().value;
        pageDataUrlCache.delete(firstKey);
      }
      pageDataUrlCache.set(apiUrl, dataUrl);
      img.src = dataUrl;
      img.dataset.tcmRendered = apiUrl;
    } catch (_err) {
      img.src = FAILED_SVG;
      img.dataset.tcmRendered = apiUrl;
    } finally {
      delete img.dataset.tcmRendering;
    }
  }

  function scanPendingImages(root = document.body) {
    if (!root) return;
    root.querySelectorAll?.("img[data-tcm-api-img]")?.forEach((img) => {
      renderApiImageToImg(img);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    scanPendingImages();
    const obs = new MutationObserver((mutations) => {
      for (const m of mutations) {
        if (m.type === "attributes" && m.target?.matches?.("img[data-tcm-api-img]")) {
          renderApiImageToImg(m.target);
          continue;
        }
        for (const node of m.addedNodes) {
          if (node.nodeType !== 1) continue;
          if (node.matches?.("img[data-tcm-api-img]")) renderApiImageToImg(node);
          else scanPendingImages(node);
        }
      }
    });
    if (document.body) {
      obs.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["data-tcm-api-img"],
      });
    }

    function showSwUpdateToast() {
      if (document.getElementById("tcm-sw-update-toast")) return;
      const bar = document.createElement("div");
      bar.id = "tcm-sw-update-toast";
      bar.className = "tcm-sw-toast";
      bar.innerHTML =
        `<span>发现新版倪氏经方知识库与辨证引擎</span>` +
        `<button type="button" class="primary-btn small-btn" id="tcm-sw-reload-btn">点击刷新生效</button>`;
      document.body?.appendChild(bar);
      document.getElementById("tcm-sw-reload-btn")?.addEventListener("click", () => window.location.reload());
    }

    if (
      "serviceWorker" in navigator &&
      (location.protocol === "https:" || location.hostname === "127.0.0.1" || location.hostname === "localhost")
    ) {
      navigator.serviceWorker
        .register("./sw.js", { updateViaCache: "none" })
        .then((reg) => {
          if (reg.waiting && navigator.serviceWorker.controller) {
            showSwUpdateToast();
          }
          reg.addEventListener("updatefound", () => {
            const nextWorker = reg.installing;
            if (!nextWorker) return;
            nextWorker.addEventListener("statechange", () => {
              if (nextWorker.state === "installed" && navigator.serviceWorker.controller) {
                showSwUpdateToast();
              }
            });
          });
        })
        .catch(() => {});
    }
  });
})();
