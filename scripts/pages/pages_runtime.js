(function () {
  window.__TCM_STATIC_WEB__ = true;
  window.__TCM_BUILD_VERSION__ = "__BUILD_ID__";

  const CONFIG_STORAGE_KEY = "ni_ai_static_config_v1";
  const CODEX_STORAGE_KEY = "ni_ai_static_codex_oauth_v1";
  const PATIENTS_STORAGE_KEY = "ni_ai_static_patients_v1";
  const SESSIONS_STORAGE_KEY = "ni_ai_static_sessions_v1";
  const SEEDED_STORAGE_KEY = "ni_ai_static_seeded_v1";

  const MAX_PROFILES = 24;
  const CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann";
  const CODEX_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize";
  const CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token";
  const CODEX_DEVICE_CODE_URL = "https://auth.openai.com/api/accounts/deviceauth/usercode";
  const CODEX_DEVICE_POLL_URL = "https://auth.openai.com/api/accounts/deviceauth/token";
  const CODEX_DEVICE_URI = "https://auth.openai.com/codex/device";
  const CODEX_DEVICE_REDIRECT = "https://auth.openai.com/deviceauth/callback";
  const CODEX_BROWSER_REDIRECT = "http://localhost:1455/auth/callback";
  const CODEX_SCOPE = "openid profile email offline_access";
  const CODEX_REFRESH_BUFFER_MS = 60000;

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

  function normalizeMaxTokens(value, fallback) {
    if (value === undefined || value === null || value === "") return fallback;
    const num = Math.trunc(Number(value));
    if (!Number.isFinite(num)) return fallback;
    if (num <= 0) return 0;
    return Math.max(256, Math.min(128000, num));
  }

  function resolveReasoningProfile(provider, protocol, model, rules) {
    const prov = String(provider || "").trim().toLowerCase();
    const proto = String(protocol || "openai_compat").trim().toLowerCase();
    const mod = String(model || "").trim().toLowerCase();
    for (const rule of rules || []) {
      if (Array.isArray(rule.protocols) && rule.protocols.length && !rule.protocols.includes(proto)) continue;
      const exclRx = rule.exclude_regex ? new RegExp(rule.exclude_regex, "i") : null;
      if (exclRx && mod && exclRx.test(mod)) continue;
      const modRx = rule.model_regex ? new RegExp(rule.model_regex, "i") : null;
      const provList = Array.isArray(rule.providers) ? rule.providers : [];
      if (rule.match_either_provider_or_model) {
        if (!(provList.includes(prov) || (modRx && mod && modRx.test(mod)))) continue;
      } else {
        if (provList.length && !provList.includes(prov)) continue;
        if (modRx && !(mod && modRx.test(mod))) continue;
      }
      return {
        id: rule.id,
        efforts: Array.isArray(rule.efforts) ? [...rule.efforts] : ["auto"],
        supports_reasoning: Boolean(rule.supports_reasoning),
        protocol_mode: rule.protocol_mode || "openai_reasoning",
        hint: rule.hint || "",
      };
    }
    return {
      id: "generic",
      efforts: ["auto", "none", "minimal", "low", "medium", "high", "xhigh"],
      supports_reasoning: true,
      protocol_mode: "openai_reasoning",
      hint: "选「自动」按模型默认；选具体档位将透传对应思考参数。",
    };
  }

  function normalizeReasoningEffort(value, fallback, provider, protocol, model, rules) {
    let raw = String(value ?? fallback ?? "auto").trim().toLowerCase();
    if (raw === "max") raw = "xhigh";
    const profile = resolveReasoningProfile(provider, protocol, model, rules);
    return profile.efforts.includes(raw) ? raw : "auto";
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

  // ── Browser-Local Multi-Profile BYOK & Codex OAuth Store ────────────────
  function sanitizeProfileId(rawId, fallback = "") {
    const cleaned = String(rawId || "")
      .trim()
      .replace(/[^a-zA-Z0-9_-]+/g, "")
      .slice(0, 48);
    if (cleaned && cleaned.toLowerCase() !== "new") return cleaned;
    return fallback || makeId("prof");
  }

  function sanitizeProfileName(rawName) {
    return String(rawName || "")
      .trim()
      .replace(/\s+/g, " ")
      .slice(0, 48);
  }

  function autoProfileName(cfg, meta) {
    const provId = String(cfg?.provider || "custom").trim().toLowerCase();
    const preset = (meta?.presets || []).find((p) => p.id === provId) || {};
    const label = String(preset.label || provId).split("（")[0].trim();
    const model = String(cfg?.model || "").trim();
    return model ? `${label} · ${model}` : label;
  }

  function defaultProfileConfig(meta) {
    return {
      provider: "deepseek",
      protocol: "openai_compat",
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-chat",
      api_key: "",
      relay_url: "",
      persona_style: "master_balanced",
      reasoning_effort: "auto",
      temperature: 0.45,
      max_tokens: 0,
      timeout_sec: 120,
      ...(meta?.defaults || {}),
    };
  }

  function coerceStoredProfile(raw, meta, fallbackId = "default") {
    const base = defaultProfileConfig(meta);
    const obj = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
    const pid = sanitizeProfileId(obj.profile_id, fallbackId);
    let norm;
    try {
      norm = normalizeClientConfig(obj, base, meta);
    } catch (_err) {
      norm = { ...base };
    }
    const name = sanitizeProfileName(obj.profile_name) || autoProfileName(norm, meta);
    const updatedAt = Number(obj.updated_at || 0);
    return {
      profile_id: pid,
      profile_name: name,
      ...norm,
      updated_at: Number.isFinite(updatedAt) ? updatedAt : 0,
    };
  }

  function loadStore(meta) {
    const raw = localStorage.getItem(CONFIG_STORAGE_KEY);
    if (!raw) {
      const def = coerceStoredProfile({}, meta, "default");
      return { version: 2, active_profile_id: def.profile_id, profiles: [def] };
    }
    const loaded = safeParseJson(raw, null);
    if (!loaded || typeof loaded !== "object" || Array.isArray(loaded)) {
      const def = coerceStoredProfile({}, meta, "default");
      return { version: 2, active_profile_id: def.profile_id, profiles: [def] };
    }
    if (Array.isArray(loaded.profiles) && loaded.profiles.length) {
      const profiles = [];
      const seen = new Set();
      loaded.profiles.slice(0, MAX_PROFILES).forEach((item, idx) => {
        const prof = coerceStoredProfile(item, meta, `prof_${idx + 1}`);
        if (seen.has(prof.profile_id)) {
          prof.profile_id = `prof_${idx + 1}_${seen.size + 1}`;
        }
        seen.add(prof.profile_id);
        profiles.push(prof);
      });
      if (!profiles.length) {
        profiles.push(coerceStoredProfile({}, meta, "default"));
      }
      let activeId = String(loaded.active_profile_id || "").trim();
      if (!profiles.some((p) => p.profile_id === activeId)) {
        activeId = profiles[0].profile_id;
      }
      return { version: 2, active_profile_id: activeId, profiles };
    }
    // Legacy v1 flat config migration
    const migrated = coerceStoredProfile(loaded, meta, "default");
    return { version: 2, active_profile_id: migrated.profile_id, profiles: [migrated] };
  }

  function writeStore(store) {
    localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(store));
  }

  function activeProfileFromStore(store, profileId = null) {
    const target = String(profileId || store.active_profile_id || "").trim();
    const found = (store.profiles || []).find((p) => p.profile_id === target);
    return found ? { ...found } : { ...store.profiles[0] };
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
    const sameProvider = providerId === String(existing.provider || "").trim().toLowerCase();

    const protocol = String(
      payload?.protocol || (sameProvider && existing.protocol ? existing.protocol : preset.protocol || "openai_compat")
    )
      .trim()
      .toLowerCase();
    if (!["openai_compat", "codex_oauth", "gemini", "anthropic"].includes(protocol)) {
      throw new Error(`不支持的协议类型: ${protocol}`);
    }

    let rawUrl = payload?.base_url;
    if (rawUrl == null) {
      rawUrl = sameProvider && existing.base_url ? existing.base_url : preset.base_url || "";
    }
    const baseUrl = validateBaseUrl(
      rawUrl,
      providerId === "custom" && !String(rawUrl || "").trim()
    );

    let rawRelay = payload?.relay_url;
    if (rawRelay == null) {
      rawRelay = existing.relay_url || "";
    }
    const relayUrl = validateBaseUrl(rawRelay, true);

    const model = String(
      payload?.model != null
        ? payload.model
        : sameProvider && existing.model
        ? existing.model
        : preset.default_model || ""
    ).trim();

    let apiKey = "";
    if (payload?.clear_api_key) {
      apiKey = "";
    } else if (typeof payload?.api_key === "string" && payload.api_key.trim()) {
      apiKey = payload.api_key.trim();
    } else if (sameProvider) {
      apiKey = String(existing.api_key || "").trim();
    }

    let style = String(payload?.persona_style || existing.persona_style || "master_balanced").trim();
    if (stylesSet.size && !stylesSet.has(style)) {
      style = "master_balanced";
    }

    const effort = normalizeReasoningEffort(
      payload?.reasoning_effort,
      existing.reasoning_effort || "auto",
      providerId,
      protocol,
      model,
      meta.reasoning_rules
    );

    return {
      provider: providerId,
      protocol,
      base_url: baseUrl,
      model,
      api_key: apiKey,
      relay_url: relayUrl,
      persona_style: style,
      reasoning_effort: effort,
      temperature: clampNum(payload?.temperature, existing.temperature ?? 0.45, 0.0, 1.5, false),
      max_tokens: normalizeMaxTokens(payload?.max_tokens, existing.max_tokens ?? 0),
      timeout_sec: clampNum(payload?.timeout_sec, existing.timeout_sec ?? 120, 10, 300, true),
    };
  }

  // ── Browser-Local Codex OAuth Manager (with Optional Relay URL) ─────────
  const staticCodexLoginState = {
    status: "idle", // idle | pending | error | cancelled
    method: "",
    verification_uri: "",
    user_code: "",
    auth_url: "",
    verifier: "",
    state: "",
    device_auth_id: "",
    interval_sec: 5,
    next_poll_at: 0,
    expires_at: 0,
    relay_url: "",
    error: "",
  };

  function resetStaticCodexLoginState(status = "idle", error = "") {
    staticCodexLoginState.status = status;
    staticCodexLoginState.method = "";
    staticCodexLoginState.verification_uri = "";
    staticCodexLoginState.user_code = "";
    staticCodexLoginState.auth_url = "";
    staticCodexLoginState.verifier = "";
    staticCodexLoginState.state = "";
    staticCodexLoginState.device_auth_id = "";
    staticCodexLoginState.interval_sec = 5;
    staticCodexLoginState.next_poll_at = 0;
    staticCodexLoginState.expires_at = 0;
    staticCodexLoginState.error = error || "";
  }

  function decodeJwtClaims(token) {
    try {
      const parts = String(token || "").split(".");
      if (parts.length !== 3) return {};
      const b64 = parts[1].replaceAll("-", "+").replaceAll("_", "/");
      const pad = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
      const bytes = Uint8Array.from(atob(pad), (c) => c.charCodeAt(0));
      const text = new TextDecoder("utf-8").decode(bytes);
      const parsed = JSON.parse(text);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_err) {
      return {};
    }
  }

  function extractCodexMeta(tokens) {
    const idClaims = decodeJwtClaims(tokens?.id_token || "");
    const accClaims = decodeJwtClaims(tokens?.access_token || "");
    const authNs = idClaims["https://api.openai.com/auth"] || accClaims["https://api.openai.com/auth"] || {};
    const profNs = idClaims["https://api.openai.com/profile"] || accClaims["https://api.openai.com/profile"] || {};
    let accountId = "";
    if (authNs && typeof authNs === "object") {
      accountId = String(authNs.chatgpt_account_id || "");
    }
    if (!accountId && tokens?.id_token && idClaims.chatgpt_account_id) {
      accountId = String(idClaims.chatgpt_account_id);
    }
    if (!accountId && Array.isArray(idClaims.organizations) && idClaims.organizations[0]?.id) {
      accountId = String(idClaims.organizations[0].id);
    }
    const planType = String(
      (authNs && typeof authNs === "object" ? authNs.chatgpt_plan_type : "") || idClaims.chatgpt_plan_type || ""
    );
    const email = String(
      idClaims.email || profNs.email || accClaims.email || ""
    );
    return { account_id: accountId, plan_type: planType, email };
  }

  function maskCodexLabel(accountId, email = "") {
    const mail = String(email || "").trim();
    if (mail.includes("@")) {
      const [local, domain] = mail.split("@", 2);
      const prefix = local.length > 2 ? local.slice(0, 2) : local.slice(0, 1);
      return `${prefix}***@${domain}`;
    }
    return maskApiKey(accountId);
  }

  function readCodexCred() {
    const raw = localStorage.getItem(CODEX_STORAGE_KEY);
    if (!raw) return null;
    const obj = safeParseJson(raw, null);
    if (!obj || typeof obj !== "object") return null;
    const access = String(obj.access || "").trim();
    const refresh = String(obj.refresh || "").trim();
    const expires = Number(obj.expires || 0);
    if (!access || !refresh || !Number.isFinite(expires) || expires <= 0) return null;
    return {
      type: "oauth",
      access,
      refresh,
      expires: Math.round(expires),
      account_id: String(obj.account_id || "").trim(),
      plan_type: String(obj.plan_type || "").trim(),
      email: String(obj.email || "").trim(),
      updated_at: Number(obj.updated_at || 0),
    };
  }

  function writeCodexCredFromTokens(tokens, fallbackRefresh = "", fallbackMeta = null) {
    const access = String(tokens?.access_token || "").trim();
    const refresh = String(tokens?.refresh_token || fallbackRefresh || "").trim();
    if (!access || !refresh) {
      throw new Error("OpenAI OAuth 未返回完整凭证，请重新登录");
    }
    const expiresIn = Math.max(60, Number(tokens?.expires_in || 3600) || 3600);
    const metaInfo = extractCodexMeta(tokens);
    const cred = {
      type: "oauth",
      access,
      refresh,
      expires: Date.now() + expiresIn * 1000,
      account_id: metaInfo.account_id || fallbackMeta?.account_id || "",
      plan_type: metaInfo.plan_type || fallbackMeta?.plan_type || "",
      email: metaInfo.email || fallbackMeta?.email || "",
      updated_at: Math.floor(Date.now() / 1000),
    };
    localStorage.setItem(CODEX_STORAGE_KEY, JSON.stringify(cred));
    return cred;
  }

  function getStaticCodexStatus() {
    const cred = readCodexCred();
    const now = Date.now();
    let login = null;
    if (staticCodexLoginState.status && staticCodexLoginState.status !== "idle") {
      if (
        staticCodexLoginState.status === "pending" &&
        staticCodexLoginState.expires_at > 0 &&
        now > staticCodexLoginState.expires_at
      ) {
        staticCodexLoginState.status = "error";
        staticCodexLoginState.error = "设备码已超时，请重新点击登录";
      }
      login = {
        status: staticCodexLoginState.status,
        method: staticCodexLoginState.method,
        verification_uri: staticCodexLoginState.verification_uri,
        user_code: staticCodexLoginState.user_code,
        auth_url: staticCodexLoginState.auth_url,
        interval_sec: staticCodexLoginState.interval_sec,
        expires_at: staticCodexLoginState.expires_at,
        error: staticCodexLoginState.error,
      };
    }
    return {
      logged_in: Boolean(cred),
      account_masked: cred ? maskCodexLabel(cred.account_id, cred.email) || "ChatGPT 已登录" : "",
      plan_type: cred?.plan_type || "",
      expires_at: cred?.expires || 0,
      requires_refresh: cred ? cred.expires <= now + CODEX_REFRESH_BUFFER_MS : false,
      login,
    };
  }

  function codexCorsGuidance(stageLabel) {
    return (
      `纯静态网页版受浏览器跨域(CORS)限制，${stageLabel}无法直接访问 OpenAI 官方接口。` +
      `请二选一：(1) 启动本地 Python 服务版（http://127.0.0.1:8767/）点击一键登录与直连；` +
      `或 (2) 在设置弹窗底部「可选：Codex CORS 中继地址」填入自建 Cloudflare Worker（见仓库 scripts/codex_relay_worker.mjs）。`
    );
  }

  async function relayAwareFetch(targetUrl, init = {}, relayUrl = "") {
    const cleanRelay = String(relayUrl || "").trim().replace(/\/+$/, "");
    if (!cleanRelay) {
      return await nativeFetch(targetUrl, init);
    }
    const headersObj = {};
    if (init.headers instanceof Headers) {
      init.headers.forEach((v, k) => {
        headersObj[k] = v;
      });
    } else if (init.headers && typeof init.headers === "object") {
      Object.assign(headersObj, init.headers);
    }
    let bodyPayload = init.body;
    if (typeof bodyPayload === "string" && headersObj["Content-Type"]?.includes("application/json")) {
      const parsed = safeParseJson(bodyPayload, null);
      if (parsed && typeof parsed === "object") bodyPayload = parsed;
    }
    return await nativeFetch(cleanRelay, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: targetUrl,
        method: init.method || "GET",
        headers: headersObj,
        body: bodyPayload,
      }),
      signal: init.signal,
    });
  }

  function b64UrlEncode(bytes) {
    let bin = "";
    for (let i = 0; i < bytes.length; i += 1) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
  }

  async function generatePkcePair() {
    const rawVerifier = new Uint8Array(48);
    crypto.getRandomValues(rawVerifier);
    const verifier = b64UrlEncode(rawVerifier);
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
    const challenge = b64UrlEncode(new Uint8Array(digest));
    const rawState = new Uint8Array(16);
    crypto.getRandomValues(rawState);
    const state = b64UrlEncode(rawState);
    return { verifier, challenge, state };
  }

  async function exchangeCodexCode(code, redirectUri, verifier, relayUrl = "") {
    const body = new URLSearchParams({
      grant_type: "authorization_code",
      code: String(code || ""),
      redirect_uri: redirectUri,
      client_id: CODEX_CLIENT_ID,
      code_verifier: String(verifier || ""),
    }).toString();
    let resp;
    try {
      resp = await relayAwareFetch(
        CODEX_TOKEN_URL,
        {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
          body,
        },
        relayUrl
      );
    } catch (_err) {
      throw new Error(codexCorsGuidance("换取 Codex Token 时"));
    }
    const text = await resp.text().catch(() => "");
    if (!resp.ok) {
      throw new Error(`换取 Codex Token 失败 (HTTP ${resp.status})：${text.slice(0, 180)}`);
    }
    const tokens = safeParseJson(text, null);
    if (!tokens || typeof tokens !== "object") {
      throw new Error("OpenAI Token 接口返回非 JSON 格式");
    }
    return writeCodexCredFromTokens(tokens);
  }

  async function startStaticCodexLogin(method = "device", relayUrl = "") {
    const mode = String(method || "device").trim().toLowerCase();
    staticCodexLoginState.relay_url = String(relayUrl || "").trim();
    if (mode === "device") {
      let resp;
      try {
        resp = await relayAwareFetch(
          CODEX_DEVICE_CODE_URL,
          {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ client_id: CODEX_CLIENT_ID }),
          },
          staticCodexLoginState.relay_url
        );
      } catch (_err) {
        const msg = codexCorsGuidance("申请设备码时");
        resetStaticCodexLoginState("error", msg);
        throw new Error(msg);
      }
      const text = await resp.text().catch(() => "");
      if (!resp.ok) {
        const msg = `申请 Codex 设备码失败 (HTTP ${resp.status})：${text.slice(0, 180)}`;
        resetStaticCodexLoginState("error", msg);
        throw new Error(msg);
      }
      const data = safeParseJson(text, {}) || {};
      const deviceAuthId = String(data.device_auth_id || "").trim();
      const userCode = String(data.user_code || data.usercode || "").trim();
      const interval = Math.max(2, Number(data.interval || 5) || 5);
      if (!deviceAuthId || !userCode) {
        const msg = "OpenAI 设备码接口返回缺少 user_code";
        resetStaticCodexLoginState("error", msg);
        throw new Error(msg);
      }
      Object.assign(staticCodexLoginState, {
        status: "pending",
        method: "device",
        verification_uri: CODEX_DEVICE_URI,
        user_code: userCode,
        auth_url: CODEX_DEVICE_URI,
        verifier: "",
        state: "",
        device_auth_id: deviceAuthId,
        interval_sec: interval,
        next_poll_at: Date.now() + interval * 1000,
        expires_at: Date.now() + 15 * 60 * 1000,
        error: "",
      });
      return getStaticCodexStatus();
    }

    if (mode === "browser") {
      const pkce = await generatePkcePair();
      const params = new URLSearchParams({
        response_type: "code",
        client_id: CODEX_CLIENT_ID,
        redirect_uri: CODEX_BROWSER_REDIRECT,
        scope: CODEX_SCOPE,
        code_challenge: pkce.challenge,
        code_challenge_method: "S256",
        id_token_add_organizations: "true",
        codex_cli_simplified_flow: "true",
        state: pkce.state,
        originator: "nihaixia-tcm",
      });
      Object.assign(staticCodexLoginState, {
        status: "pending",
        method: "browser",
        verification_uri: "",
        user_code: "",
        auth_url: `${CODEX_AUTHORIZE_URL}?${params.toString()}`,
        verifier: pkce.verifier,
        state: pkce.state,
        device_auth_id: "",
        interval_sec: 5,
        next_poll_at: 0,
        expires_at: Date.now() + 10 * 60 * 1000,
        error: "",
      });
      return getStaticCodexStatus();
    }

    throw new Error(`不支持的 Codex 登录方式: ${mode}`);
  }

  async function pollStaticCodexDeviceOnce(relayUrl = "") {
    if (staticCodexLoginState.status !== "pending" || staticCodexLoginState.method !== "device") {
      return;
    }
    const now = Date.now();
    if (now > staticCodexLoginState.expires_at) {
      staticCodexLoginState.status = "error";
      staticCodexLoginState.error = "设备码已超时，请重新点击「设备码登录」";
      return;
    }
    if (now < staticCodexLoginState.next_poll_at) return;
    staticCodexLoginState.next_poll_at = now + staticCodexLoginState.interval_sec * 1000;
    const effectiveRelay = relayUrl || staticCodexLoginState.relay_url || "";
    try {
      const resp = await relayAwareFetch(
        CODEX_DEVICE_POLL_URL,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({
            device_auth_id: staticCodexLoginState.device_auth_id,
            user_code: staticCodexLoginState.user_code,
          }),
        },
        effectiveRelay
      );
      if (resp.status === 403 || resp.status === 404 || resp.status === 400) return;
      if (!resp.ok) {
        const errText = await resp.text().catch(() => "");
        staticCodexLoginState.status = "error";
        staticCodexLoginState.error = `设备码轮询失败 (HTTP ${resp.status})：${errText.slice(0, 120)}`;
        return;
      }
      const data = await resp.json();
      const authCode = String(data.authorization_code || "").trim();
      const verifier = String(data.code_verifier || "").trim();
      if (!authCode || !verifier) return;
      await exchangeCodexCode(authCode, CODEX_DEVICE_REDIRECT, verifier, effectiveRelay);
      resetStaticCodexLoginState("idle", "");
    } catch (err) {
      staticCodexLoginState.status = "error";
      staticCodexLoginState.error = String(err?.message || err);
    }
  }

  async function submitStaticCodexCallback(rawValue, relayUrl = "") {
    if (staticCodexLoginState.status !== "pending" || staticCodexLoginState.method !== "browser" || !staticCodexLoginState.verifier) {
      throw new Error("请先点击「浏览器 OAuth 登录」后再粘贴回调链接");
    }
    let parsed;
    try {
      const trimmed = String(rawValue || "").trim();
      parsed = trimmed.startsWith("http://") || trimmed.startsWith("https://")
        ? new URL(trimmed)
        : new URL(`http://localhost/?${trimmed.replace(/^\?/, "")}`);
    } catch (_err) {
      throw new Error("回调链接格式无效");
    }
    const errParam = parsed.searchParams.get("error");
    if (errParam) {
      const desc = parsed.searchParams.get("error_description") || errParam;
      throw new Error(`OpenAI 授权失败：${desc}`);
    }
    const code = parsed.searchParams.get("code") || "";
    const state = parsed.searchParams.get("state") || "";
    if (!code) throw new Error("回调链接中缺少 code 参数，请确认复制完整地址栏链接");
    if (state !== staticCodexLoginState.state) {
      throw new Error("OAuth state 校验不匹配，请重新发起浏览器登录");
    }
    const effectiveRelay = relayUrl || staticCodexLoginState.relay_url || "";
    await exchangeCodexCode(code, CODEX_BROWSER_REDIRECT, staticCodexLoginState.verifier, effectiveRelay);
    resetStaticCodexLoginState("idle", "");
    return getStaticCodexStatus();
  }

  function cancelStaticCodexLogin() {
    resetStaticCodexLoginState("cancelled", "");
    return getStaticCodexStatus();
  }

  function logoutStaticCodex() {
    localStorage.removeItem(CODEX_STORAGE_KEY);
    resetStaticCodexLoginState("idle", "");
    return getStaticCodexStatus();
  }

  async function ensureFreshStaticCodexConfig(cfg) {
    if (!cfg || cfg.protocol !== "codex_oauth") return cfg;
    const cred = readCodexCred();
    if (!cred) {
      throw new Error("当前未登录 OpenAI Codex（请先在模型设置中登录 ChatGPT 账号）");
    }
    if (cred.expires > Date.now() + CODEX_REFRESH_BUFFER_MS) {
      return {
        ...cfg,
        api_key: cred.access,
        codex_account_id: cred.account_id,
        key_source: "codex_oauth",
        ready: Boolean(cfg.base_url && cfg.model && cred.access),
      };
    }
    let resp;
    try {
      resp = await relayAwareFetch(
        CODEX_TOKEN_URL,
        {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
          body: new URLSearchParams({
            grant_type: "refresh_token",
            refresh_token: cred.refresh,
            client_id: CODEX_CLIENT_ID,
          }).toString(),
        },
        cfg.relay_url || ""
      );
    } catch (_err) {
      throw new Error(codexCorsGuidance("刷新 Codex Token 时"));
    }
    const text = await resp.text().catch(() => "");
    if (!resp.ok) {
      throw new Error(`Codex Token 已过期且刷新失败 (HTTP ${resp.status})，请重新登录 OpenAI Codex`);
    }
    const tokens = safeParseJson(text, null);
    if (!tokens || typeof tokens !== "object") {
      throw new Error("刷新 Codex Token 返回格式异常，请重新登录");
    }
    const refreshed = writeCodexCredFromTokens(tokens, cred.refresh, cred);
    return {
      ...cfg,
      api_key: refreshed.access,
      codex_account_id: refreshed.account_id,
      key_source: "codex_oauth",
      ready: Boolean(cfg.base_url && cfg.model && refreshed.access),
    };
  }

  function resolveProfileRuntime(profile, meta, codexCred = null) {
    const base = { ...defaultProfileConfig(meta), ...(profile || {}) };
    const presetMap = new Map((meta.presets || []).map((p) => [p.id, p]));
    const preset = presetMap.get(base.provider) || {};
    const requiresKey = preset.requires_key !== false;
    const requiresOauth = Boolean(preset.requires_oauth) || base.protocol === "codex_oauth";

    let effectiveKey = "";
    let keySource = "none";
    let codexAccountId = "";
    let codexExpiresAt = 0;
    let ready = false;
    if (base.protocol === "codex_oauth") {
      if (codexCred?.access) {
        effectiveKey = codexCred.access;
        keySource = "codex_oauth";
        codexAccountId = codexCred.account_id || "";
        codexExpiresAt = codexCred.expires || 0;
      }
      ready = Boolean(base.base_url && base.model && codexCred?.refresh);
    } else {
      effectiveKey = String(base.api_key || "").trim();
      keySource = effectiveKey ? "browser" : "none";
      ready = Boolean(base.base_url && base.model && (effectiveKey || !requiresKey));
    }

    return {
      profile_id: String(profile?.profile_id || "default"),
      profile_name: String(profile?.profile_name || autoProfileName(base, meta)),
      ...base,
      api_key: effectiveKey,
      key_source: keySource,
      requires_key: requiresKey,
      requires_oauth: requiresOauth,
      has_oauth: Boolean(codexCred),
      codex_account_id: codexAccountId,
      codex_expires_at: codexExpiresAt,
      ready,
    };
  }

  function toPublicProfile(profile, meta, codexCred, isActive) {
    const runtime = resolveProfileRuntime(profile, meta, codexCred);
    const { api_key: secret, ...rest } = runtime;
    return {
      ...rest,
      has_api_key: Boolean(secret),
      api_key_masked: runtime.protocol === "codex_oauth" ? "" : maskApiKey(secret),
      reasoning_profile: resolveReasoningProfile(runtime.provider, runtime.protocol, runtime.model, meta.reasoning_rules),
      is_active: isActive,
      updated_at: Number(profile.updated_at || 0),
    };
  }

  function toPublicConfig(meta) {
    const store = loadStore(meta);
    const activeId = store.active_profile_id;
    const codexCred = readCodexCred();
    const publicProfiles = store.profiles.map((prof) =>
      toPublicProfile(prof, meta, codexCred, prof.profile_id === activeId)
    );
    const activePublic = publicProfiles.find((p) => p.is_active) || publicProfiles[0];
    return {
      ...activePublic,
      active_profile_id: activeId,
      profiles: publicProfiles,
      codex_auth: getStaticCodexStatus(),
      presets: meta.presets || [],
      styles: meta.styles || [],
      reasoning_tiers: meta.reasoning_tiers || [],
      reasoning_rules: meta.reasoning_rules || [],
    };
  }

  function toRuntimeConfig(meta, override = null) {
    const store = loadStore(meta);
    const reqPid = String(override?.profile_id || "").trim();
    const saved = activeProfileFromStore(store, reqPid || null);
    const codexCred = readCodexCred();
    if (!override) return resolveProfileRuntime(saved, meta, codexCred);
    const normalized = normalizeClientConfig(override, saved, meta);
    const merged = {
      ...saved,
      ...normalized,
      profile_name: sanitizeProfileName(override.profile_name) || saved.profile_name,
    };
    return resolveProfileRuntime(merged, meta, codexCred);
  }

  function saveProfileStore(payload, meta) {
    const store = loadStore(meta);
    const profiles = [...store.profiles];
    const saveAsNew = Boolean(payload?.save_as_new);
    const requestedId = String(payload?.profile_id || "").trim();

    let existingIdx = -1;
    if (!saveAsNew && requestedId) {
      existingIdx = profiles.findIndex((p) => p.profile_id === requestedId);
    } else if (!saveAsNew) {
      existingIdx = profiles.findIndex((p) => p.profile_id === store.active_profile_id);
    }

    const creatingNew = saveAsNew || (Boolean(requestedId) && existingIdx < 0);
    if (creatingNew && profiles.length >= MAX_PROFILES) {
      throw new Error(`最多可保存 ${MAX_PROFILES} 组模型配置，请先删除闲置配置`);
    }

    let baseProfile;
    let targetId;
    if (existingIdx >= 0) {
      baseProfile = { ...profiles[existingIdx] };
      targetId = baseProfile.profile_id;
    } else {
      baseProfile = activeProfileFromStore(store);
      const idSet = new Set(profiles.map((p) => p.profile_id));
      let cand = sanitizeProfileId(saveAsNew ? "" : requestedId);
      while (idSet.has(cand)) cand = makeId("prof");
      targetId = cand;
    }

    const normalized = normalizeClientConfig(payload || {}, baseProfile, meta);
    const explicitName = payload?.profile_name != null ? sanitizeProfileName(payload.profile_name) : "";
    const prevAuto = autoProfileName(baseProfile, meta);
    const existingName = sanitizeProfileName(baseProfile.profile_name);
    let profileName;
    if (explicitName) {
      profileName = explicitName;
    } else if (!creatingNew && existingName && existingName !== prevAuto) {
      profileName = existingName;
    } else {
      profileName = autoProfileName(normalized, meta);
    }

    const entry = {
      profile_id: targetId,
      profile_name: profileName,
      ...normalized,
      updated_at: Math.floor(Date.now() / 1000),
    };
    if (existingIdx >= 0) profiles[existingIdx] = entry;
    else profiles.push(entry);

    writeStore({ version: 2, active_profile_id: targetId, profiles });
    return toPublicConfig(meta);
  }

  function selectProfileStore(profileId, meta) {
    const target = String(profileId || "").trim();
    const store = loadStore(meta);
    if (!store.profiles.some((p) => p.profile_id === target)) {
      throw new Error("未找到指定的模型配置");
    }
    store.active_profile_id = target;
    writeStore(store);
    return toPublicConfig(meta);
  }

  function deleteProfileStore(profileId, meta) {
    const target = String(profileId || "").trim();
    const store = loadStore(meta);
    if (store.profiles.length <= 1) {
      throw new Error("至少保留一组模型配置");
    }
    const remaining = store.profiles.filter((p) => p.profile_id !== target);
    if (remaining.length === store.profiles.length) {
      throw new Error("未找到要删除的模型配置");
    }
    const nextActive = store.active_profile_id === target ? remaining[0].profile_id : store.active_profile_id;
    writeStore({ version: 2, active_profile_id: nextActive, profiles: remaining });
    return toPublicConfig(meta);
  }

  // ── Direct Browser LLM Client (BYOK CORS + Zero-Key Fallback) ───────────
  function openaiEndpoint(baseUrl, suffix) {
    const clean = String(baseUrl || "").replace(/\/+$/, "");
    return clean.endsWith(suffix) ? clean : `${clean}${suffix}`;
  }

  function codexEndpoint(baseUrl) {
    const clean = String(baseUrl || "https://chatgpt.com/backend-api").trim().replace(/\/+$/, "");
    if (clean.endsWith("/codex/responses")) return clean;
    if (clean.endsWith("/codex")) return `${clean}/responses`;
    if (clean.includes("/backend-api")) return `${clean}/codex/responses`;
    return `${clean}/backend-api/codex/responses`;
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

  function friendlyHttpError(status, bodyText, protocol = "") {
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
    const lowerAll = `${detail} ${bodyText || ""}`.toLowerCase();
    if (["image_url", "does not support image", "unknown variant", "multimodal", "vision"].some((k) => lowerAll.includes(k))) {
      return (
        `当前所选模型或网关不支持图片识别 (HTTP ${status})：${detail}。` +
        `（提示：请切换到支持视觉的模型如 gpt-4o / gpt-4.1 / gemini-2.5-flash / claude-sonnet-4 / qwen-vl，或改用手动点选四诊标签）`
      );
    }
    if (status === 401) {
      if (protocol === "codex_oauth") {
        return `Codex 登录凭证已失效或权限不足 (HTTP 401)：请重新登录 OpenAI Codex。${detail}`.trim();
      }
      return `认证失败 (HTTP 401)：请检查 API Key 是否有效或有余额。${detail}`.trim();
    }
    if (status === 403) return `权限或区域受限 (HTTP 403)：${detail}`.trim();
    if (status === 404) return `接口或模型不存在 (HTTP 404)：请检查 Base URL 与模型名称。${detail}`.trim();
    if (status === 429) {
      if (protocol === "codex_oauth") {
        return `Codex 订阅当前模型额度或频率受限 (HTTP 429)：请稍候再试或切换模型。${detail}`.trim();
      }
      return `请求频率或额度受限 (HTTP 429)：${detail}`.trim();
    }
    return `上游模型返回错误 (HTTP ${status})：${detail}`.trim();
  }

  const OPENAI_FIXED_TEMP_PROFILES = new Set([
    "openai_codex_and_o3",
    "openai_o1",
    "openai_gpt5_base",
    "openai_gpt5_1",
    "openai_gpt5_2plus",
  ]);
  const GEMINI_LEVEL_MAP = { minimal: "MINIMAL", low: "LOW", medium: "MEDIUM", high: "HIGH" };
  const GEMINI_BUDGET_MAP = { none: 0, low: 1024, medium: 4096, high: 8192, xhigh: 24576 };
  const ANTHROPIC_BUDGET_MAP = { low: 2048, medium: 6144, high: 12288, xhigh: 24576 };

  function buildOpenAiContent(m) {
    const text = String(m.content || "");
    const imgs = Array.isArray(m.images) ? m.images : [];
    if (!imgs.length) return text;
    return [
      { type: "text", text },
      ...imgs.map((img) => ({ type: "image_url", image_url: { url: img.data_url } })),
    ];
  }

  function buildAnthropicContent(m) {
    const text = String(m.content || "");
    const imgs = Array.isArray(m.images) ? m.images : [];
    if (!imgs.length) return text;
    return [
      ...imgs.map((img) => ({
        type: "image",
        source: { type: "base64", media_type: img.mime_type, data: img.b64 },
      })),
      { type: "text", text },
    ];
  }

  function buildGeminiParts(m) {
    const parts = [{ text: String(m.content || "") }];
    for (const img of Array.isArray(m.images) ? m.images : []) {
      parts.push({ inlineData: { mimeType: img.mime_type, data: img.b64 } });
    }
    return parts;
  }

  function prepareUpstreamRequest(cfg, systemPrompt, messages, stream, meta = null) {
    const protocol = cfg.protocol || "openai_compat";
    const rules = meta?.reasoning_rules || [];
    const profile = resolveReasoningProfile(cfg.provider, protocol, cfg.model, rules);
    const effort = normalizeReasoningEffort(cfg.reasoning_effort, "auto", cfg.provider, protocol, cfg.model, rules);
    const rawMax = Math.max(0, Math.trunc(Number(cfg.max_tokens || 0) || 0));

    if (protocol === "codex_oauth") {
      const headers = {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        Authorization: `Bearer ${cfg.api_key || ""}`,
        "OpenAI-Beta": "responses=experimental",
        originator: "nihaixia-tcm",
      };
      if (cfg.codex_account_id) {
        headers["ChatGPT-Account-Id"] = String(cfg.codex_account_id);
      }
      const inputItems = messages.map((m) => {
        const isAssistant = m.role === "assistant";
        const text = String(m.content || "");
        if (isAssistant) {
          return { role: "assistant", content: [{ type: "output_text", text }] };
        }
        const parts = [{ type: "input_text", text }];
        for (const img of Array.isArray(m.images) ? m.images : []) {
          parts.push({ type: "input_image", image_url: img.data_url });
        }
        return { role: "user", content: parts };
      });
      const body = {
        model: cfg.model,
        store: false,
        stream: true,
        instructions: systemPrompt || "",
        input: inputItems,
        tools: [],
        tool_choice: "none",
      };
      if (effort !== "auto") {
        body.reasoning = { effort };
      }
      return {
        url: codexEndpoint(cfg.base_url),
        headers,
        body,
      };
    }
    if (protocol === "gemini") {
      const action = stream ? "streamGenerateContent?alt=sse" : "generateContent";
      const genCfg = { temperature: cfg.temperature ?? 0.45 };
      if (rawMax > 0) genCfg.maxOutputTokens = rawMax;
      if (effort !== "auto") {
        if (profile.protocol_mode === "gemini_level" && GEMINI_LEVEL_MAP[effort]) {
          genCfg.thinkingConfig = { includeThoughts: true, thinkingLevel: GEMINI_LEVEL_MAP[effort] };
        } else if (profile.protocol_mode === "gemini_budget" && GEMINI_BUDGET_MAP[effort] !== undefined) {
          const budget = GEMINI_BUDGET_MAP[effort];
          genCfg.thinkingConfig = { includeThoughts: budget !== 0, thinkingBudget: budget };
        }
      }
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
            parts: buildGeminiParts(m),
          })),
          generationConfig: genCfg,
        },
      };
    }
    if (protocol === "anthropic") {
      let thinkingCfg = null;
      if (effort !== "auto" && profile.protocol_mode === "anthropic_thinking") {
        if (effort === "none") thinkingCfg = { type: "disabled" };
        else if (ANTHROPIC_BUDGET_MAP[effort]) {
          thinkingCfg = { type: "enabled", budget_tokens: ANTHROPIC_BUDGET_MAP[effort] };
        }
      }
      const thinkingOn = Boolean(thinkingCfg && thinkingCfg.type === "enabled");
      let effectiveMax;
      if (thinkingOn) {
        effectiveMax = rawMax <= 0 ? Math.max(16384, thinkingCfg.budget_tokens + 4096) : Math.max(rawMax, thinkingCfg.budget_tokens + 1024);
      } else {
        const cap = profile.id === "anthropic_non_thinking" ? 8192 : 16384;
        effectiveMax = rawMax <= 0 ? cap : rawMax;
      }
      const body = {
        model: cfg.model,
        system: systemPrompt,
        messages: messages.map((m) => ({
          role: m.role === "assistant" ? "assistant" : "user",
          content: buildAnthropicContent(m),
        })),
        max_tokens: effectiveMax,
        stream: Boolean(stream),
      };
      if (thinkingCfg) body.thinking = thinkingCfg;
      if (!thinkingOn) body.temperature = cfg.temperature ?? 0.45;
      return {
        url: anthropicMessagesUrl(cfg.base_url),
        headers: {
          "Content-Type": "application/json",
          "x-api-key": cfg.api_key || "",
          "anthropic-version": "2023-06-01",
          "anthropic-dangerous-direct-browser-access": "true",
        },
        body,
      };
    }
    const headers = { "Content-Type": "application/json" };
    if (cfg.api_key) {
      headers.Authorization = `Bearer ${cfg.api_key}`;
    }
    const body = {
      model: cfg.model,
      messages: [
        { role: "system", content: systemPrompt },
        ...messages.map((m) => ({ role: m.role, content: buildOpenAiContent(m) })),
      ],
      stream: Boolean(stream),
    };
    const skipTemp =
      OPENAI_FIXED_TEMP_PROFILES.has(profile.id) &&
      !((profile.id === "openai_gpt5_1" || profile.id === "openai_gpt5_2plus") && effort === "none");
    if (!skipTemp) body.temperature = cfg.temperature ?? 0.45;
    if (rawMax > 0) body.max_tokens = rawMax;
    if (effort !== "auto") {
      if (profile.protocol_mode === "deepseek") {
        if (effort === "none") {
          body.thinking = { type: "disabled" };
        } else {
          body.thinking = { type: "enabled" };
          body.reasoning_effort = effort === "xhigh" ? "max" : effort;
        }
      } else if (profile.protocol_mode === "openai_reasoning") {
        body.reasoning_effort = effort;
      }
    }
    return {
      url: openaiEndpoint(cfg.base_url, "/chat/completions"),
      headers,
      body,
    };
  }

  function parseUpstreamEvents(protocol, chunk, eventName = "") {
    const events = [];
    if (!chunk || typeof chunk !== "object") return events;
    if (protocol === "codex_oauth") {
      const extractText = (respObj) => {
        const texts = [];
        for (const item of respObj?.output || []) {
          for (const part of item?.content || []) {
            if ((part?.type === "output_text" || part?.type === "text") && part?.text) {
              texts.push(String(part.text));
            }
          }
        }
        return texts.join("");
      };
      if (chunk.__full) {
        const text = extractText(chunk);
        if (text) events.push({ type: "delta", text });
        if (chunk.usage) events.push({ type: "usage", usage: chunk.usage });
        return events;
      }
      const evType = String(chunk.type || eventName || "").trim();
      if (evType === "error" || evType === "response.failed" || (chunk.error && !evType)) {
        const err = chunk.error || chunk?.response?.error || chunk;
        const msg = err?.message || JSON.stringify(err);
        throw new Error(`Codex 流中断：${msg}`);
      }
      if (evType === "response.incomplete") {
        const reason = chunk?.response?.incomplete_details?.reason || "incomplete";
        throw new Error(`Codex 输出未完成：${reason}`);
      }
      if (
        evType === "response.reasoning_summary_text.delta" ||
        evType === "response.reasoning_text.delta" ||
        evType === "response.reasoning.delta"
      ) {
        const delta = chunk.delta || chunk.text || "";
        if (delta) events.push({ type: "reasoning", text: String(delta) });
        return events;
      }
      if (evType === "response.output_text.delta") {
        if (chunk.delta) events.push({ type: "delta", text: String(chunk.delta) });
        return events;
      }
      if (evType === "response.completed" || evType === "response.done") {
        const respObj = chunk.response && typeof chunk.response === "object" ? chunk.response : chunk;
        const fb = extractText(respObj);
        if (fb) events.push({ type: "__fallback_delta__", text: fb });
        const usage = respObj?.usage || chunk.usage;
        if (usage) events.push({ type: "usage", usage });
      }
      return events;
    }
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

  async function* iterUpstreamEvents(cfg, systemPrompt, messages, signal, meta = null) {
    const liveCfg = await ensureFreshStaticCodexConfig(cfg);
    const req = prepareUpstreamRequest(liveCfg, systemPrompt, messages, true, meta);
    let resp;
    try {
      resp = await relayAwareFetch(
        req.url,
        {
          method: "POST",
          headers: req.headers,
          body: JSON.stringify(req.body),
          signal,
        },
        liveCfg.relay_url || ""
      );
    } catch (err) {
      if (err?.name === "AbortError") throw err;
      if (liveCfg.protocol === "codex_oauth") {
        throw new Error(codexCorsGuidance("请求 Codex 订阅接口时"));
      }
      throw new Error(`无法从浏览器直连模型接口：${err?.message || "CORS 或网络受限"}`);
    }
    if (!resp.ok) {
      const errText = await resp.text().catch(() => "");
      throw new Error(friendlyHttpError(resp.status, errText, liveCfg.protocol));
    }
    const ctype = (resp.headers.get("content-type") || "").toLowerCase();
    let sawDelta = false;
    const filterEmit = function* (evs) {
      for (const ev of evs) {
        if (ev.type === "__fallback_delta__") {
          if (!sawDelta && ev.text) {
            sawDelta = true;
            yield { type: "delta", text: ev.text };
          }
          continue;
        }
        if (ev.type === "delta" && ev.text) sawDelta = true;
        yield ev;
      }
    };
    if (ctype.includes("application/json") && !ctype.includes("text/event-stream")) {
      const full = await resp.json();
      if (full && typeof full === "object") full.__full = true;
      for (const ev of filterEmit(parseUpstreamEvents(liveCfg.protocol, full))) yield ev;
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
      return parseUpstreamEvents(liveCfg.protocol, parsed, evName);
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
          for (const ev of filterEmit(flushEvent())) yield ev;
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
    for (const ev of filterEmit(flushEvent())) yield ev;
  }

  async function runDirectModels(cfg, meta) {
    const preset = (meta.presets || []).find((p) => p.id === cfg.provider) || {};
    const suggested = Array.isArray(preset.suggested_models) ? [...preset.suggested_models] : [];
    const baseUrl = String(cfg.base_url || "").trim().replace(/\/+$/, "");
    if (!baseUrl || cfg.protocol === "anthropic" || cfg.protocol === "codex_oauth") {
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

  async function runDirectTest(cfg, meta = null) {
    if (!cfg.base_url) throw new Error("请先填写模型 Base URL");
    if (!cfg.model) throw new Error("请先选择或填写模型名称");
    if (cfg.protocol !== "codex_oauth" && cfg.requires_key && !cfg.api_key) {
      throw new Error("当前模型未配置 API Key");
    }

    const liveCfg = await ensureFreshStaticCodexConfig(cfg);
    const started = performance.now();
    const probeCfg = { ...liveCfg, max_tokens: 256, temperature: 0.0, reasoning_effort: "auto" };

    if (probeCfg.protocol === "codex_oauth") {
      const deltas = [];
      for await (const ev of iterUpstreamEvents(
        probeCfg,
        "你是连通性测试助手。请只回复“已连通”三个字。",
        [{ role: "user", content: "测试连通" }],
        undefined,
        meta
      )) {
        if (ev.type === "delta" && ev.text) deltas.push(ev.text);
      }
      return {
        ok: true,
        provider: probeCfg.provider,
        model: probeCfg.model,
        latency_ms: Math.round(performance.now() - started),
        reply_preview: deltas.join("").trim().slice(0, 80),
      };
    }

    const req = prepareUpstreamRequest(
      probeCfg,
      "你是连通性测试助手。请只回复“已连通”三个字。",
      [{ role: "user", content: "测试连通" }],
      false,
      meta
    );
    let resp;
    try {
      resp = await relayAwareFetch(
        req.url,
        {
          method: "POST",
          headers: req.headers,
          body: JSON.stringify(req.body),
        },
        probeCfg.relay_url || ""
      );
    } catch (_err) {
      const hint =
        probeCfg.provider === "ollama"
          ? "Ollama 默认需设置 OLLAMA_ORIGINS=* 允许网页端直连，或使用本地 Python 服务版"
          : "浏览器端直连受网络或目标网关 CORS 策略限制，您仍可直接切回零 Key 离线推演";
      throw new Error(`无法从浏览器直连模型接口：${hint}。`);
    }
    if (!resp.ok) {
      throw new Error(friendlyHttpError(resp.status, await resp.text().catch(() => ""), probeCfg.protocol));
    }
    const full = await resp.json();
    full.__full = true;
    const events = parseUpstreamEvents(probeCfg.protocol, full);
    const preview = events
      .filter((e) => e.type === "delta")
      .map((e) => e.text)
      .join("")
      .trim()
      .slice(0, 80);
    return {
      ok: true,
      provider: probeCfg.provider,
      model: probeCfg.model,
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
      return jsonResponse(toPublicConfig(meta));
    }

    if (apiPath === "/api/ai/config" && method === "POST") {
      try {
        return jsonResponse(saveProfileStore(body || {}, meta));
      } catch (err) {
        return jsonResponse({ detail: String(err?.message || err) }, 400);
      }
    }

    if (apiPath === "/api/ai/profiles/select" && method === "POST") {
      try {
        return jsonResponse(selectProfileStore(body?.profile_id, meta));
      } catch (err) {
        return jsonResponse({ detail: String(err?.message || err) }, 400);
      }
    }

    if (apiPath === "/api/ai/profiles/delete" && method === "POST") {
      try {
        return jsonResponse(deleteProfileStore(body?.profile_id, meta));
      } catch (err) {
        return jsonResponse({ detail: String(err?.message || err) }, 400);
      }
    }

    if (apiPath === "/api/ai/codex/status" && method === "GET") {
      const active = activeProfileFromStore(loadStore(meta));
      await pollStaticCodexDeviceOnce(active?.relay_url || "");
      return jsonResponse({
        ...getStaticCodexStatus(),
        config: toPublicConfig(meta),
      });
    }

    if (apiPath === "/api/ai/codex/login" && method === "POST") {
      try {
        const active = activeProfileFromStore(loadStore(meta));
        const relayUrl = String(body?.relay_url || active?.relay_url || "").trim();
        const status = await startStaticCodexLogin(body?.method || "device", relayUrl);
        return jsonResponse({ ...status, config: toPublicConfig(meta) });
      } catch (err) {
        return jsonResponse({ detail: String(err?.message || err) }, 400);
      }
    }

    if (apiPath === "/api/ai/codex/callback" && method === "POST") {
      try {
        const active = activeProfileFromStore(loadStore(meta));
        const relayUrl = String(body?.relay_url || active?.relay_url || "").trim();
        const status = await submitStaticCodexCallback(body?.callback_url || "", relayUrl);
        return jsonResponse({ ...status, config: toPublicConfig(meta) });
      } catch (err) {
        return jsonResponse({ detail: String(err?.message || err) }, 400);
      }
    }

    if (apiPath === "/api/ai/codex/cancel" && method === "POST") {
      const status = cancelStaticCodexLogin();
      return jsonResponse({ ...status, config: toPublicConfig(meta) });
    }

    if (apiPath === "/api/ai/codex/logout" && method === "POST") {
      const status = logoutStaticCodex();
      return jsonResponse({ ...status, config: toPublicConfig(meta) });
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
        return jsonResponse(await runDirectTest(cfg, meta));
      } catch (err) {
        return jsonResponse({ detail: String(err?.message || err) }, 400);
      }
    }

    if (apiPath === "/api/ai/vision-intake" && method === "POST") {
      let cfg = toRuntimeConfig(meta, body?.config_override || null);
      if (!cfg.ready) {
        return jsonResponse(
          {
            detail:
              "识图功能需要先在「模型设置」中配置支持视觉的大模型与 API Key（或登录 OpenAI Codex 订阅账号）；免 Key 离线模式请直接点选上方四诊标签。",
          },
          400
        );
      }
      try {
        cfg = await ensureFreshStaticCodexConfig(cfg);
      } catch (err) {
        return jsonResponse({ detail: String(err?.message || err) }, 400);
      }
      const prep = await callWorker("/api/ai/vision-prepare", "POST", body || {});
      if ((prep.status || 200) >= 400) return jsonResponse(prep.body, prep.status);
      const { system_prompt, user_text, images } = prep.body;
      const visionCfg = {
        ...cfg,
        temperature: 0.1,
        reasoning_effort: "auto",
        max_tokens: cfg.max_tokens > 0 ? Math.max(2048, cfg.max_tokens) : 0,
      };
      if (visionCfg.protocol === "codex_oauth") {
        try {
          const textParts = [];
          for await (const ev of iterUpstreamEvents(
            visionCfg,
            system_prompt,
            [{ role: "user", content: user_text, images }],
            signal,
            meta
          )) {
            if (ev.type === "delta" && ev.text) textParts.push(ev.text);
          }
          const parsed = await callWorker("/api/ai/vision-parse", "POST", {
            text: textParts.join(""),
            image_count: images.length,
          });
          return jsonResponse({ ...parsed.body, provider: cfg.provider, model: cfg.model }, parsed.status || 200);
        } catch (err) {
          return jsonResponse({ detail: String(err?.message || err) }, 400);
        }
      }
      const req = prepareUpstreamRequest(
        visionCfg,
        system_prompt,
        [{ role: "user", content: user_text, images }],
        false,
        meta
      );
      let resp;
      try {
        resp = await relayAwareFetch(
          req.url,
          {
            method: "POST",
            headers: req.headers,
            body: JSON.stringify(req.body),
            signal,
          },
          visionCfg.relay_url || ""
        );
      } catch (_err) {
        return jsonResponse(
          { detail: "浏览器端直连识图接口受跨域(CORS)或网络限制，请改用本地 Python 服务版或手动点选四诊标签。" },
          400
        );
      }
      if (!resp.ok) {
        return jsonResponse({ detail: friendlyHttpError(resp.status, await resp.text().catch(() => ""), visionCfg.protocol) }, 400);
      }
      const full = await resp.json();
      full.__full = true;
      const text = parseUpstreamEvents(cfg.protocol, full)
        .filter((e) => e.type === "delta")
        .map((e) => e.text)
        .join("");
      const parsed = await callWorker("/api/ai/vision-parse", "POST", { text, image_count: images.length });
      return jsonResponse({ ...parsed.body, provider: cfg.provider, model: cfg.model }, parsed.status || 200);
    }

    if (apiPath === "/api/ai/chat/stream" && method === "POST") {
      const cfgOverride = body?.config_override ? { ...body.config_override } : {};
      if (body?.reasoning_effort) cfgOverride.reasoning_effort = body.reasoning_effort;
      const cfg = toRuntimeConfig(meta, Object.keys(cfgOverride).length ? cfgOverride : null);
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
              for await (const ev of iterUpstreamEvents(cfg, system_prompt, messages, signal, meta)) {
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
