import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { test } from "node:test";
import vm from "node:vm";

const source = await readFile(new URL("../scripts/pages/pages_runtime.js", import.meta.url), "utf8");

function runtime(fetchImpl = fetch, { meta = null, workerReply = null, guardWrite = null } = {}) {
  const workerListeners = new Map();
  let emitWorkerMessage;
  const session = new Map();
  const storage = new Map([
    ["ni_ai_static_codex_oauth_v1", JSON.stringify({
      access: "synthetic-access", refresh: "synthetic-refresh", expires: Date.now() + 3600000,
    })],
  ]);
  const sandbox = {
    window: { fetch: fetchImpl },
    location: new URL("https://aotianlong600-spec.github.io/nihaixia-tcm/"),
    document: { addEventListener() {}, getElementById() { return null; } },
    navigator: {},
    Worker: class {
      constructor() { emitWorkerMessage = data => workerListeners.get("message")({ data }); }
      addEventListener(type, handler) { workerListeners.set(type, handler); }
      postMessage(request) {
        queueMicrotask(() => emitWorkerMessage({
          type: "response", id: request.id, raw: JSON.stringify(workerReply(request)),
        }));
      }
    },
    localStorage: {
      getItem: k => storage.get(k) ?? null,
      setItem(k, v) { guardWrite?.(k, v); storage.set(k, v); },
      removeItem: k => storage.delete(k),
    },
    sessionStorage: { getItem: k => session.get(k) ?? null, setItem: (k, v) => session.set(k, v), removeItem: k => session.delete(k) },
    URL, URLSearchParams, Headers, Request, Response, ReadableStream,
    TextEncoder, TextDecoder, AbortController, DOMException, performance,
    setTimeout: (fn, ms) => setTimeout(fn, Math.min(ms, 200)), clearTimeout,
  };
  vm.runInNewContext(source.replace("null /* __STATIC_AI_META__ */", JSON.stringify(meta)).replace(/\}\)\(\);\s*$/, `
    globalThis.helpers = { relayAwareFetch, startStaticCodexLogin, runDirectTest, iterUpstreamEvents, friendlyHttpError, saveHistoryStore };
  })();`), sandbox);
  return { ...sandbox.helpers, bridge: sandbox.window.tcmLocalCodexBridge, browserFetch: sandbox.window.fetch, emitWorkerMessage, storage };
}

async function upstream(t, handler) {
  const server = createServer(handler);
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  t.after(async () => {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  });
  return `http://127.0.0.1:${server.address().port}`;
}

async function bounded(promise) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => { timer = setTimeout(() => reject(Error("Request remained pending")), 1000); }),
    ]);
  } finally { clearTimeout(timer); }
}

const cfg = {
  provider: "custom", protocol: "openai_compat", model: "synthetic-model",
  api_key: "synthetic-key", requires_key: true, timeout_sec: 20,
};

for (const relay of [false, true]) {
  test(`response-body timeout survives receipt of HTTP headers (${relay ? "relay" : "direct"})`, async t => {
    const url = await upstream(t, (_req, res) => { res.writeHead(200); res.flushHeaders(); });
    const { relayAwareFetch } = runtime();
    const response = await relayAwareFetch(url, {}, relay ? url : "", 150);
    await assert.rejects(bounded(response.text()), error => error.name === "TimeoutError");
  });
}

test("a stalled Codex device-code request has a default deadline", async t => {
  const url = await upstream(t, () => {});
  const { startStaticCodexLogin } = runtime((_url, init) => fetch(url, init));
  await assert.rejects(bounded(startStaticCodexLogin("device")), /超时/);
});

for (const protocol of ["openai_compat", "codex_oauth"]) {
  test(`connection test ends when the response body stalls (${protocol})`, async t => {
    const url = await upstream(t, (_req, res) => {
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      res.flushHeaders();
    });
    const { runDirectTest } = runtime((_url, init) => fetch(url, init));
    await assert.rejects(bounded(runDirectTest({ ...cfg, protocol, base_url: url })), /超时/);
  });
}

for (const protocol of ["openai_compat", "codex_oauth"]) {
  test(`connection test accepts completed SSE without waiting for HTTP close (${protocol})`, async t => {
    const url = await upstream(t, (_req, res) => {
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      if (protocol === "codex_oauth") {
        res.write('data: {"type":"response.output_text.delta","delta":"已连通"}\n\n');
        res.write('data: {"type":"response.completed","response":{"status":"completed"}}\n\n');
      } else {
        res.write('data: {"choices":[{"delta":{"content":"已连通"}}]}\n\n');
        res.write('data: [DONE]\n\n');
      }
    });
    const { runDirectTest } = runtime((_url, init) => fetch(url, init));
    const result = await bounded(runDirectTest({ ...cfg, protocol, base_url: url }));
    assert.equal(result.ok, true);
    assert.equal(result.reply_preview, "已连通");
  });
}

test("an empty model response cannot be reported as a successful connection", async t => {
  const url = await upstream(t, (_req, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end('{"choices":[]}');
  });
  const { runDirectTest } = runtime((_url, init) => fetch(url, init));
  await assert.rejects(runDirectTest({ ...cfg, base_url: url }), /未返回|无有效/);
});

test("normal JSON completions still pass the connection test", async t => {
  const url = await upstream(t, (_req, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end('{"choices":[{"message":{"content":"已连通"}}]}');
  });
  const { runDirectTest } = runtime((_url, init) => fetch(url, init));
  const result = await runDirectTest({ ...cfg, base_url: url });
  assert.equal(result.reply_preview, "已连通");
});

test("a buffered Codex stream works when a relay labels it as JSON", async t => {
  const url = await upstream(t, (_req, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end('data: {"type":"response.completed","response":{"status":"completed","output":[{"content":[{"type":"output_text","text":"已连通"}]}]}}\n\n');
  });
  const { runDirectTest } = runtime((_url, init) => fetch(url, init));
  const result = await runDirectTest({ ...cfg, protocol: "codex_oauth", base_url: url });
  assert.equal(result.reply_preview, "已连通");
});

for (const contentType of ["text/event-stream", "application/json"]) {
  test(`Codex rejects partial text when the upstream closes without completion (${contentType})`, async () => {
    const { runDirectTest } = runtime(async () => new Response(
      'data: {"type":"response.output_text.delta","delta":"partial"}\n\n',
      { headers: { "Content-Type": contentType } },
    ));
    await assert.rejects(runDirectTest({ ...cfg, protocol: "codex_oauth", base_url: "https://chatgpt.com/backend-api" }), /未收到.*完成/);
  });
}

test("relay busy and relay timeout receive distinct, actionable messages", () => {
  const { friendlyHttpError } = runtime();
  assert.match(friendlyHttpError(429, '{"error":"relay_busy"}', "codex_oauth"), /转发服务.*繁忙/);
  assert.match(friendlyHttpError(502, '{"error":"provider_connection_failed","reason":"deadline_exceeded"}', "codex_oauth"), /回复超时/);
});

test("a relay error after the first Codex delta is not a successful reply", async () => {
  const { runDirectTest } = runtime(async () => new Response(
    'data: {"type":"response.output_text.delta","delta":"partial"}\n\n' +
    'event: error\ndata: {"type":"error","error":{"code":"provider_connection_failed","reason":"deadline_exceeded"}}\n\n',
    { headers: { "Content-Type": "text/event-stream" } },
  ));
  await assert.rejects(runDirectTest({ ...cfg, protocol: "codex_oauth", base_url: "https://chatgpt.com/backend-api" }), /回复超时/);
});

test("a cold consultation waits for checked context and stops if the knowledge worker fails", async () => {
  let networkCalls = 0;
  const { browserFetch, emitWorkerMessage } = runtime(async () => {
    networkCalls++;
    throw new Error("consultation reached model before checks");
  }, { meta: { presets: [{ id: "codex", protocol: "codex_oauth", base_url: "https://chatgpt.com/backend-api", default_model: "synthetic" }] } });
  const response = await browserFetch("/api/ai/chat/stream", {
    method: "POST",
    body: JSON.stringify({ query: "synthetic", config_override: { provider: "codex" } }),
  });
  const read = response.body.getReader();
  const start = await bounded(read.read());
  assert.match(new TextDecoder().decode(start.value), /event: status/);
  assert.equal(networkCalls, 0);
  emitWorkerMessage({ type: "init_error", error: "synthetic initialization failure" });
  let rest = "";
  for (;;) {
    const { value, done } = await bounded(read.read());
    if (done) break;
    rest += new TextDecoder().decode(value);
  }
  assert.match(rest, /"mode":"error"/);
  assert.equal(networkCalls, 0);
});

test("a cold consultation checks local context before generating and preserves the check in its stream", async () => {
  let prepared = false;
  let modelCalls = 0;
  const { browserFetch, emitWorkerMessage } = runtime(async () => {
    assert.equal(prepared, true);
    modelCalls++;
    return new Response('data: {"type":"response.output_text.delta","delta":"synthetic"}\n\n' +
      'data: {"type":"response.completed","response":{"status":"completed"}}\n\n',
      { headers: { "Content-Type": "text/event-stream" } });
  }, {
    meta: { presets: [{ id: "codex", protocol: "codex_oauth", base_url: "https://chatgpt.com/backend-api", default_model: "synthetic" }] },
    workerReply({ url }) {
      if (url === "/api/ai/prepare-prompt") {
        prepared = true;
        return { status: 200, body: {
          packet: { safety_boundary: { triggered: false }, citations: [] },
          system_prompt: "synthetic system prompt", messages: [{ role: "user", content: "synthetic" }], offline_reply: "synthetic fallback",
        } };
      }
      return { status: 200, body: {} };
    },
  });
  const response = await browserFetch("/api/ai/chat/stream", {
    method: "POST",
    body: JSON.stringify({ query: "synthetic", config_override: { provider: "codex" } }),
  });
  assert.equal(modelCalls, 0);
  emitWorkerMessage({ type: "ready" });
  const stream = await bounded(response.text());
  assert.ok(stream.indexOf("event: context") < stream.indexOf("event: delta"));
  assert.match(stream, /"safety_boundary":\{"triggered":false\}/);
  assert.match(stream, /event: done/);
  assert.equal(modelCalls, 1);
});

test("quota failure keeps old evidence packets and rolls back an incomplete history write", () => {
  let full = false;
  const patientKey = "ni_ai_static_patients_v1";
  const sessionKey = "ni_ai_static_sessions_v1";
  const { saveHistoryStore, storage } = runtime(fetch, { guardWrite(key, value) {
    if (full && key === sessionKey && value.includes("NEW")) {
      throw new DOMException("Browser storage full", "QuotaExceededError");
    }
  } });
  const sessions = Array.from({ length: 7 }, (_, i) => ({ id: i, latest_packet: { summary: "preserve" } }));
  saveHistoryStore([{ id: "P" }], sessions);
  full = true;
  assert.throws(() => saveHistoryStore([{ id: "P", name: "renamed" }], [...sessions, { id: "NEW" }]), /Browser storage full/);
  assert.deepEqual(JSON.parse(storage.get(patientKey)), [{ id: "P" }]);
  assert.deepEqual(JSON.parse(storage.get(sessionKey)), sessions);
});

test("manual cancellation still aborts a body read", async t => {
  const url = await upstream(t, (_req, res) => { res.writeHead(200); res.flushHeaders(); });
  const controller = new AbortController();
  const { relayAwareFetch } = runtime();
  const response = await relayAwareFetch(url, { signal: controller.signal }, "", 1000);
  const text = response.text();
  controller.abort();
  await assert.rejects(bounded(text), error => error.name === "AbortError");
});

test("an already-cancelled request leaves no unhandled fetch rejection", async t => {
  const url = await upstream(t, (_req, res) => res.end("unused"));
  const controller = new AbortController();
  controller.abort();
  const { relayAwareFetch } = runtime();
  await assert.rejects(relayAwareFetch(url, { signal: controller.signal }), error => error.name === "AbortError");
  await new Promise(resolve => setImmediate(resolve));
});

test("OpenCode 402 reports PAYG credit separately from a Go subscription", () => {
  const { friendlyHttpError } = runtime();
  const message = friendlyHttpError(402, JSON.stringify({ error: {
    message: "Insufficient balance. This request is pay-as-you-go, billed to OpenCode Models credits. OpenCode Go covers only requests to the OpenCode Go provider.",
  } }));
  assert.match(message, /按量余额不足/);
  assert.match(message, /Go 订阅/);
});

test("Codex uses the project's existing relay and preserves the wire body", async () => {
  let sent;
  const { relayAwareFetch } = runtime(async (url, init) => {
    sent = { url, init };
    return new Response('{"ok":true}', { headers: { "Content-Type": "application/json" } });
  });
  const payload = '{"model":"synthetic-model","stream":true}';
  const result = await relayAwareFetch("https://chatgpt.com/backend-api/codex/responses", {
    method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer synthetic-token" }, body: payload,
  });
  assert.equal((await result.json()).ok, true);
  assert.equal(sent.url, "https://vpn.liul.top/relay");
  assert.deepEqual(JSON.parse(sent.init.body), {
    url: "https://chatgpt.com/backend-api/codex/responses", method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer synthetic-token" }, body: payload, timeout_ms: 20000,
  });
});

test("the project relay receives the configured model deadline while custom envelopes stay compatible", async () => {
  const bodies = [];
  const { relayAwareFetch } = runtime(async (_url, init) => {
    bodies.push(JSON.parse(init.body));
    return new Response("ok");
  });
  const target = "https://chatgpt.com/backend-api/codex/responses";
  await (await relayAwareFetch(target, { method: "POST", body: "{}" }, "", 600000)).text();
  await (await relayAwareFetch(target, { method: "POST", body: "{}" }, "https://relay.example", 600000)).text();
  assert.equal(bodies[0].timeout_ms, 600000);
  assert.equal(Object.hasOwn(bodies[1], "timeout_ms"), false);
});

test("custom relays are preserved and other providers stay direct", async () => {
  const calls = [];
  const { relayAwareFetch } = runtime(async (url, init) => {
    calls.push(String(url));
    return new Response("ok");
  });
  await (await relayAwareFetch("https://auth.openai.com/oauth/token", {}, "https://relay.example/")).text();
  await (await relayAwareFetch("https://api.deepseek.com/v1/chat/completions")).text();
  assert.deepEqual(calls, ["https://relay.example", "https://api.deepseek.com/v1/chat/completions"]);
});

test("Codex HTML blocks identify the relay instead of blaming the user's region", () => {
  const { friendlyHttpError } = runtime();
  for (const error of ["provider_access_blocked", "provider_challenge"]) {
    const message = friendlyHttpError(403, JSON.stringify({ error, upstream_format: "html" }), "codex_oauth");
    assert.match(message, /转发服务器.*拦截/);
    assert.equal(message.includes("权限或区域受限"), false);
  }
});

test("an unknown Codex 403 does not invent a cause", () => {
  const { friendlyHttpError } = runtime();
  const message = friendlyHttpError(403, '{"error":"provider_request_failed"}', "codex_oauth");
  assert.match(message, /尚无法判断具体原因/);
});

test("explicit local pairing routes Codex through loopback without leaking the pairing key", async () => {
  const calls = [];
  const { bridge, relayAwareFetch } = runtime(async (url, init) => {
    calls.push({ url: String(url), init });
    if (String(url).endsWith('/pair')) return new Response(JSON.stringify({ service: 'nihaixia-codex-browser-relay', key: 'p'.repeat(43), expires_in: 3600 }));
    return new Response('ok');
  });
  assert.equal(bridge.status().connected, false);
  await bridge.connect();
  assert.equal(bridge.status().connected, true);
  await (await relayAwareFetch('https://chatgpt.com/backend-api/codex/responses', { method: 'POST', body: '{}' })).text();
  await (await relayAwareFetch('https://api.deepseek.com/v1/chat/completions')).text();
  bridge.disconnect();
  await (await relayAwareFetch('https://chatgpt.com/backend-api/codex/responses', { method: 'POST', body: '{}' })).text();
  assert.equal(calls[1].url, 'http://127.0.0.1:8769/relay');
  assert.equal(calls[1].init.headers['X-Tcm-Bridge-Key'], 'p'.repeat(43));
  assert.equal(calls[2].init.headers?.['X-Tcm-Bridge-Key'], undefined);
  assert.equal(calls[3].url, 'https://vpn.liul.top/relay');
  assert.equal(calls[3].init.headers['X-Tcm-Bridge-Key'], undefined);
});

test("pairing refuses an unknown loopback service", async () => {
  const { bridge } = runtime(async () => new Response(JSON.stringify({ service: 'untrusted', key: 'p'.repeat(43), expires_in: 3600 })));
  await assert.rejects(bridge.connect(), /本机中转/);
  assert.equal(bridge.status().connected, false);
});

test("an expired local pairing asks to reconnect the bridge", () => {
  const { friendlyHttpError } = runtime();
  assert.match(friendlyHttpError(401, '{"error":"bridge_pairing_required"}', 'codex_oauth'), /重新连接本机中转/);
});
