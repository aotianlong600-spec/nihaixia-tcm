import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import vm from "node:vm";

const source = await readFile(new URL("../web/ni_ai.js", import.meta.url), "utf8");

function runtime(fetchImpl, active = true) {
  const elements = new Map();
  for (const id of ["ai-chat-thread", "ai-safety-banner", "ai-evidence-body", "ai-patient-list", "ai-session-list", "ai-submit-btn",
    "ai-stop-btn", "ai-consult-phase", "ai-consult-elapsed", "notice"]) {
    const listeners = new Map();
    elements.set(`#${id}`, {
      textContent: "", innerHTML: "",
      classList: { add() {}, remove() {}, toggle() {} },
      addEventListener: (type, handler) => listeners.set(type, handler),
      click: (selector, dataset = {}) => listeners.get("click")({
        target: { closest: (query) => query === selector ? { dataset } : null },
        stopPropagation() {}, preventDefault() {},
      }),
    });
  }
  const sandbox = {
    document: {
      querySelector: (selector) => elements.get(selector) || null,
      querySelectorAll: () => [],
      addEventListener() {},
    },
    window: {
      innerWidth: 1400, requestAnimationFrame: (fn) => fn(),
      setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
      addEventListener() {}, removeEventListener() {}, confirm: () => true,
    },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch: fetchImpl,
    AbortController, TextDecoder,
  };
  vm.runInNewContext(source.replace(/\}\)\(\);\s*$/, `
    globalThis.fixture = { niState, bindEvents };
  })();`), sandbox);
  const { niState, bindEvents } = sandbox.fixture;
  niState.config = { ready: true };
  if (active) {
    niState.activePatientId = "patient-a";
    niState.activeSessionId = "session-a";
  }
  bindEvents();
  return { ...sandbox.window.niAI, element: (selector) => elements.get(selector) };
}

function mockStream() {
  const encoder = new TextEncoder();
  let controller;
  const response = new Response(new ReadableStream({ start(c) { controller = c; } }));
  return {
    response,
    send: (event, data) => controller.enqueue(encoder.encode(
      `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
    )),
    close: () => controller.close(),
    fail: (error) => controller.error(error),
  };
}

function savedSession(id = "session-a") {
  return Response.json({ session: { id }, sessions: [] });
}

test("reopening the workbench still returns a promise to the view switcher", async () => {
  const app = runtime(async () => Response.json({ patients: [] }), false);
  await app.activate();
  await app.activate().catch(() => {});
});

test("switching records during a live reply leaves its packet in the originating session", async () => {
  const stream = mockStream();
  const saved = [];
  const app = runtime(async (url, init) => {
    if (url.endsWith("/chat/stream")) return stream.response;
    if (url.endsWith("/save")) {
      saved.push({ url, ...JSON.parse(init.body) });
      return savedSession();
    }
    if (url.endsWith("/patients/patient-b/sessions")) {
      return Response.json({ sessions: [{ id: "session-b" }] });
    }
    return Response.json({ session: { id: "session-b", turns: [] } });
  });
  const generating = app.submitConsultation("测试主诉");
  await app.element("#ai-patient-list").click("[data-pat-select]", { patSelect: "patient-b" });
  stream.send("context", { mode: "live", packet: { query: "原始证据" } });
  stream.send("done", { mode: "live", text: "已完成" });
  stream.close();
  await generating;
  assert.equal(saved.length, 1);
  assert.equal(saved[0].url, "/api/ai/sessions/session-a/save");
  assert.equal(saved[0].latest_packet.query, "原始证据");
  assert.equal(saved[0].turns.at(-1).text, "已完成");
});

test("a second submit cannot start while the first is creating its session", async () => {
  let allowCreate;
  const creating = new Promise((resolve) => { allowCreate = resolve; });
  let patientCreates = 0;
  const app = runtime(async (url, init) => {
    if (url === "/api/ai/patients" && init.method === "POST") {
      patientCreates++;
      await creating;
      return Response.json({ patient: { id: "patient-a" } });
    }
    if (url.endsWith("/chat/stream")) {
      return new Response('event: done\ndata: {"mode":"live","text":"已完成"}\n\n');
    }
    if (url.endsWith("/sessions")) {
      return Response.json({ session: { id: "session-a", turns: [] }, sessions: [] });
    }
    return savedSession();
  }, false);
  const first = app.submitConsultation("第一次主诉");
  const second = app.submitConsultation("第二次主诉");
  allowCreate();
  await Promise.all([first, second]);
  assert.equal(patientCreates, 1);
});

test("an EOF without done marks the partial reply interrupted", async () => {
  const stream = mockStream();
  let saved;
  const app = runtime(async (url, init) => {
    if (url.endsWith("/chat/stream")) return stream.response;
    saved = JSON.parse(init.body);
    return savedSession();
  });
  const generating = app.submitConsultation("测试主诉");
  stream.send("delta", { text: "未完成回复" });
  stream.close();
  await generating;
  assert.match(app.element("#ai-chat-thread").innerHTML, /中断|未完成/);
  assert.doesNotMatch(app.element("#ai-chat-thread").innerHTML, /已自动切换离线|data-ai-followup/);
  assert.ok(saved.turns.at(-1).error);
});

test("wait status is shown while waiting for the first reply and is not saved to the conversation", async () => {
  const stream = mockStream();
  let saved;
  const app = runtime(async (url, init) => {
    if (url.endsWith("/chat/stream")) return stream.response;
    saved = JSON.parse(init.body);
    return savedSession();
  });
  const generating = app.submitConsultation("测试主诉");
  stream.send("status", { message: "正在载入经典知识库" });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.element("#ai-consult-phase").textContent, "正在载入经典知识库");
  assert.ok(app.element("#ai-consult-elapsed").textContent);
  stream.send("done", { mode: "live", text: "已完成" });
  stream.close();
  await generating;
  assert.equal(app.element("#ai-consult-phase").textContent, "");
  assert.equal(saved.turns.at(-1).text, "已完成");
});

test("opening previous evidence cannot hide the latest safety alert", async () => {
  const firstStream = mockStream();
  const secondStream = mockStream();
  const incoming = [firstStream, secondStream];
  const app = runtime(async (url) => {
    if (url.endsWith("/chat/stream")) return incoming.shift().response;
    return savedSession();
  });
  const first = app.submitConsultation("首轮输入");
  firstStream.send("context", { mode: "live", packet: { citations: [] } });
  firstStream.send("done", { mode: "live", text: "已完成" });
  firstStream.close();
  await first;
  const thread = app.element("#ai-chat-thread");
  const priorTurnId = thread.innerHTML.match(/data-ai-select-packet="([^"]+)"/)[1];
  const second = app.submitConsultation("次轮输入");
  secondStream.send("context", {
    mode: "live", packet: { safety_boundary: { triggered: true, title: "本轮安全提示" } },
  });
  await new Promise((resolve) => setImmediate(resolve));
  const safety = app.element("#ai-safety-banner");
  assert.match(safety.innerHTML, /本轮安全提示/);
  await thread.click("[data-ai-select-packet]", { aiSelectPacket: priorTurnId });
  assert.match(safety.innerHTML, /本轮安全提示/);
  secondStream.send("done", { mode: "live", text: "已完成" });
  secondStream.close();
  await second;
});

test("a failed save remains visible and retries the original snapshot", async () => {
  const snapshots = [];
  const deleted = [];
  const app = runtime(async (url, init) => {
    if (url.endsWith("/chat/stream")) {
      return new Response('event: done\ndata: {"mode":"live","text":"已完成"}\n\n');
    }
    if (url.endsWith("/patients/patient-b/sessions")) {
      return Response.json({ sessions: [{ id: "session-b" }, { id: "session-c" }] });
    }
    if (url.endsWith("/sessions/session-b")) {
      return Response.json({ session: { id: "session-b", turns: [{ role: "user", query: "另一问诊" }] } });
    }
    if (url.endsWith("/delete")) {
      deleted.push(url);
      return Response.json({ sessions: [{ id: "session-b" }] });
    }
    if (url === "/api/ai/patients") return Response.json({ patients: [] });
    snapshots.push([url, init.body]);
    return snapshots.length === 1
      ? Response.json({ detail: "存储空间不足" }, { status: 507 })
      : savedSession();
  });
  await app.submitConsultation("测试主诉");
  const thread = app.element("#ai-chat-thread");
  assert.match(thread.innerHTML, /尚未保存|未保存/);
  await app.element("#ai-patient-list").click("[data-pat-select]", { patSelect: "patient-b" });
  assert.match(thread.innerHTML, /另一问诊/);
  assert.doesNotMatch(thread.innerHTML, /测试主诉/);
  assert.match(thread.innerHTML, /尚未保存/);
  await app.element("#ai-session-list").click("[data-ses-del]", { sesDel: "session-c" });
  assert.deepEqual(deleted, ["/api/ai/sessions/session-c/delete"]);
  await thread.click("[data-ai-retry-save]");
  assert.equal(snapshots.length, 2);
  assert.deepEqual(snapshots[0], snapshots[1]);
  assert.doesNotMatch(thread.innerHTML, /data-ai-retry-save/);
  assert.match(thread.innerHTML, /另一问诊/);
});

test("the origin stays locked through saving even if done arrives before the connection closes", { timeout: 1000 }, async () => {
  const stream = mockStream();
  let startSave;
  let completeSave;
  const saving = new Promise((resolve) => { startSave = resolve; });
  const saveResponse = new Promise((resolve) => { completeSave = resolve; });
  const requests = [];
  const app = runtime(async (url) => {
    requests.push(url);
    if (url.endsWith("/chat/stream")) return stream.response;
    if (url.endsWith("/save")) {
      startSave();
      return saveResponse;
    }
    return Response.json({ sessions: [] });
  });
  const generating = app.submitConsultation("测试主诉");
  stream.send("done", { mode: "live", text: "已完成" });
  await saving;
  await app.element("#ai-session-list").click("[data-ses-del]", { sesDel: "session-a" });
  await app.element("#ai-patient-list").click("[data-pat-select]", { patSelect: "patient-b" });
  completeSave(savedSession());
  await generating;
  assert.deepEqual(requests, ["/api/ai/chat/stream", "/api/ai/sessions/session-a/save"]);
});

test("manual stop records cancellation and clears provisional model content", async () => {
  const stream = mockStream();
  let saved;
  const app = runtime(async (url, init) => {
    if (url.endsWith("/chat/stream")) {
      init.signal.addEventListener("abort", () => stream.fail(init.signal.reason));
      return stream.response;
    }
    saved = JSON.parse(init.body);
    return savedSession();
  });
  const generating = app.submitConsultation("测试主诉");
  stream.send("delta", { text: "局部线上内容" });
  await new Promise((resolve) => setImmediate(resolve));
  app.element("#ai-stop-btn").click();
  await generating;
  assert.equal(saved.turns.at(-1).mode, "cancelled");
  assert.equal(saved.turns.at(-1).text, "");
  assert.match(app.element("#ai-chat-thread").innerHTML, /已取消/);
  assert.doesNotMatch(app.element("#ai-chat-thread").innerHTML, /离线参考|局部线上内容/);
});

test("an offline fallback saves its complete text and citations without partial online output", async () => {
  const stream = mockStream();
  let saved;
  const app = runtime(async (url, init) => {
    if (url.endsWith("/chat/stream")) return stream.response;
    saved = JSON.parse(init.body);
    return savedSession();
  });
  const generating = app.submitConsultation("测试主诉");
  stream.send("reasoning", { text: "局部推演" });
  stream.send("delta", { text: "局部线上内容" });
  stream.send("error", { detail: "模拟超时", fallback_text: "离线参考正文" });
  stream.send("done", {
    mode: "offline_fallback", text: "离线参考正文", error: "模拟超时", reasoning: "局部推演",
    cited: { referenced_ids: [1] },
  });
  stream.close();
  await generating;
  assert.equal(saved.turns.at(-1).mode, "offline_fallback");
  assert.equal(saved.turns.at(-1).text, "离线参考正文");
  assert.equal(saved.turns.at(-1).reasoning, "");
  assert.deepEqual(saved.turns.at(-1).cited, { referenced_ids: [1] });
  assert.match(app.element("#ai-chat-thread").innerHTML, /已提供离线参考/);
  assert.doesNotMatch(app.element("#ai-chat-thread").innerHTML, /局部线上内容|局部推演/);
});
