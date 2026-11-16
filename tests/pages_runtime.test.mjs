import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { test } from "node:test";
import vm from "node:vm";

const source = await readFile(new URL("../scripts/pages/pages_runtime.js", import.meta.url), "utf8");

function runtime(fetchImpl = fetch) {
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
    Worker: class { addEventListener() {} },
    localStorage: { getItem: k => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v) },
    sessionStorage: { getItem: k => session.get(k) ?? null, setItem: (k, v) => session.set(k, v), removeItem: k => session.delete(k) },
    URL, URLSearchParams, Headers, Request, Response, ReadableStream,
    TextEncoder, TextDecoder, AbortController, DOMException, performance,
    setTimeout: (fn, ms) => setTimeout(fn, Math.min(ms, 200)), clearTimeout,
  };
  vm.runInNewContext(source.replace(/\}\)\(\);\s*$/, `
    globalThis.helpers = { relayAwareFetch, startStaticCodexLogin, runDirectTest, iterUpstreamEvents, friendlyHttpError };
  })();`), sandbox);
  return { ...sandbox.helpers, bridge: sandbox.window.tcmLocalCodexBridge };
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
  assert.equal(sent.url, "https://nihaixia-model-relay-long600.fairykiwi35.chatgpt.site/relay");
  assert.deepEqual(JSON.parse(sent.init.body), {
    url: "https://chatgpt.com/backend-api/codex/responses", method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer synthetic-token" }, body: payload,
  });
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
  assert.equal(calls[3].url, 'https://nihaixia-model-relay-long600.fairykiwi35.chatgpt.site/relay');
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
