import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { request as httpRequest } from 'node:http';
import { connect } from 'node:net';
import { test } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { createRelayServer } from '../scripts/run_public_codex_relay.mjs';

const ORIGIN = 'https://aotianlong600-spec.github.io';

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

async function bounded(promise) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('HTTP test did not complete')), 2000);
    })]);
  } finally { clearTimeout(timer); }
}

async function running(t, options = {}) {
  const server = createRelayServer(options);
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  });
  return server.address().port;
}

function responseOf(request) {
  return new Promise((resolve, reject) => {
    request.once('error', reject);
    request.once('response', response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.once('error', reject);
      response.once('end', () => resolve({
        status: response.statusCode, headers: response.headers,
        body: Buffer.concat(chunks).toString('utf8'),
      }));
    });
  });
}

function send(port, { path = '/relay', method = 'POST', body = '{}', headers = {}, origin = ORIGIN } = {}) {
  const request = httpRequest({
    hostname: '127.0.0.1', port, path, method,
    headers: { ...(origin === null ? {} : { Origin: origin }), 'Content-Type': 'application/json', ...headers },
  });
  const response = responseOf(request);
  request.end(body);
  return bounded(response);
}

function envelope(url, method = 'POST') {
  return JSON.stringify({ url, method, headers: {
    Authorization: 'Bearer synthetic-token', 'Content-Type': 'application/json',
  }, body: method === 'GET' ? null : '{}' });
}

async function statusOf(port) {
  const response = await send(port, { path: '/status', method: 'GET', body: '', origin: null });
  assert.equal(response.status, 200);
  assert.equal(response.headers['access-control-allow-origin'], undefined);
  assert.equal(response.headers['cache-control'], 'no-store');
  return JSON.parse(response.body);
}

test('the executable adapter serves the worker health route', async t => {
  const port = await running(t);
  const response = await send(port, { path: '/health', method: 'GET', body: '' });
  assert.equal(response.status, 200);
  assert.match(response.headers['content-type'], /application\/json/);
  assert.equal(typeof JSON.parse(response.body), 'object');
});

test('HTTP translation ignores hostile Host and preserves the request body and response', async t => {
  const port = await running(t, { handler: async request => {
    await delay(15);
    return Response.json({
      origin: new URL(request.url).origin, path: new URL(request.url).pathname,
      query: new URL(request.url).search, method: request.method,
      body: await request.text(), originHeader: request.headers.get('Origin'),
      contentType: request.headers.get('Content-Type'), aborted: request.signal.aborted,
    }, { status: 201, headers: { 'X-Relay-Test': 'preserved' } });
  } });
  const response = await send(port, {
    path: '/relay?case=1', body: '{"text":"中文"}', headers: { Host: 'attacker.invalid' },
  });
  assert.equal(response.status, 201);
  assert.equal(response.headers['x-relay-test'], 'preserved');
  assert.deepEqual(JSON.parse(response.body), {
    origin: 'http://127.0.0.1', path: '/relay', query: '?case=1', method: 'POST',
    body: '{"text":"中文"}', originHeader: ORIGIN, contentType: 'application/json', aborted: false,
  });
});

test('an oversized declared body is rejected before the client uploads it', async t => {
  const port = await running(t, { bodyLimit: 8, handler: () => new Response('must not run') });
  const request = httpRequest({ hostname: '127.0.0.1', port, path: '/relay', method: 'POST',
    headers: { Origin: ORIGIN, 'Content-Length': '9' } });
  try {
    const response = responseOf(request);
    request.flushHeaders();
    const result = await bounded(response);
    assert.equal(result.status, 413);
    assert.deepEqual(JSON.parse(result.body), { error: 'request_too_large' });
    assert.equal(result.headers['access-control-allow-origin'], ORIGIN);
  } finally { request.destroy(); }
});

for (const [origin, allowed] of [[ORIGIN, true], ['http://localhost:8767', true], ['https://attacker.invalid', false]]) {
  test(`chunked uploads are bounded and error CORS respects ${origin}`, async t => {
    const port = await running(t, { bodyLimit: 8, handler: () => new Response('must not run') });
    const result = await send(port, { body: '123456789', headers: { Origin: origin, 'Transfer-Encoding': 'chunked' } });
    assert.equal(result.status, 413);
    assert.equal(result.headers['access-control-allow-origin'], allowed ? origin : undefined);
    assert.equal(result.headers.connection, 'close');
  });
}

test('busy inference slots reject excess work, preserve health, and recover after completion', async t => {
  const entered = deferred();
  const release = deferred();
  let first = true;
  const port = await running(t, { maxConcurrent: 1, handler: async request => {
    if (new URL(request.url).pathname === '/health') return Response.json({ status: 'ok' });
    if (first) { first = false; entered.resolve(); await release.promise; }
    return new Response('finished');
  } });
  const pending = send(port);
  pending.catch(() => {});
  try {
    await bounded(entered.promise);
    const busy = await send(port);
    assert.equal(busy.status, 503);
    assert.ok(Number(busy.headers['retry-after']) > 0);
    assert.equal(busy.headers['access-control-allow-origin'], ORIGIN);
    const health = await send(port, { path: '/health', method: 'GET', body: '' });
    assert.equal(health.status, 200);
  } finally { release.resolve(); }
  assert.equal((await pending).status, 200);
  assert.equal((await send(port)).status, 200);
});

test('client disconnect aborts upstream work and returns its concurrency slot', async t => {
  const entered = deferred();
  const cancelled = deferred();
  let first = true;
  const port = await running(t, { maxConcurrent: 1, handler: async request => {
    if (first) {
      first = false;
      entered.resolve();
      await new Promise(resolve => request.signal.addEventListener('abort', () => {
        cancelled.resolve(); resolve();
      }, { once: true }));
    }
    return new Response('done');
  } });
  const request = httpRequest({ hostname: '127.0.0.1', port, path: '/relay', method: 'POST' });
  request.on('error', () => {});
  request.end('{}');
  await bounded(entered.promise);
  request.destroy();
  await bounded(cancelled.promise);
  assert.equal((await send(port)).status, 200);
});

test('a body-bearing health request cannot bypass the concurrency bound', async t => {
  const entered = deferred();
  const release = deferred();
  const port = await running(t, { maxConcurrent: 1, handler: async request => {
    if (new URL(request.url).pathname !== '/health') { entered.resolve(); await release.promise; }
    return new Response('ready');
  } });
  const pending = send(port);
  pending.catch(() => {});
  try {
    await bounded(entered.promise);
    const result = await send(port, { path: '/health', method: 'GET', headers: { 'Content-Length': '2' } });
    assert.equal(result.status, 503);
  } finally { release.resolve(); }
  await pending;
});

test('unexpected handler errors return fixed JSON without credentials or stack traces', async t => {
  const port = await running(t, { handler: () => { throw new Error('synthetic-secret-token'); } });
  const response = await send(port, { body: '{"secret":"synthetic-secret-token"}' });
  assert.equal(response.status, 500);
  assert.deepEqual(JSON.parse(response.body), { error: 'relay_internal_error' });
  assert.equal(response.headers['access-control-allow-origin'], ORIGIN);
  assert.doesNotMatch(response.body, /synthetic-secret|Error|\bat\s/);
});

test('slow incomplete uploads time out and release their concurrency slot', async t => {
  const port = await running(t, { requestTimeoutMs: 60, maxConcurrent: 1, handler: () => new Response('ready') });
  const request = httpRequest({ hostname: '127.0.0.1', port, path: '/relay', method: 'POST',
    headers: { Origin: ORIGIN, 'Content-Length': '20' } });
  try {
    const response = responseOf(request);
    request.write('{}');
    const result = await bounded(response);
    assert.equal(result.status, 408);
    assert.deepEqual(JSON.parse(result.body), { error: 'request_timeout' });
    assert.equal(result.headers['access-control-allow-origin'], ORIGIN);
    assert.equal((await send(port)).status, 200);
  } finally { request.destroy(); }
});

test('the response deadline ends a stalled handler even when it ignores cancellation', async t => {
  const release = deferred();
  let first = true;
  const port = await running(t, { responseTimeoutMs: 60, maxConcurrent: 1, handler: async () => {
    if (first) { first = false; await release.promise; }
    return new Response('ready');
  } });
  try {
    const result = await send(port);
    assert.equal(result.status, 504);
    assert.deepEqual(JSON.parse(result.body), { error: 'relay_timeout' });
    assert.equal((await send(port)).status, 200);
  } finally { release.resolve(); }
});

test('absolute-form request targets cannot escape the synthetic local origin', async t => {
  const port = await running(t, { handler: () => new Response('must not run') });
  const result = await send(port, { path: 'https://attacker.invalid/relay' });
  assert.equal(result.status, 400);
  assert.deepEqual(JSON.parse(result.body), { error: 'invalid_request' });
});

test('oversized HTTP headers are rejected before the handler runs', async t => {
  const port = await running(t, { handler: () => new Response('must not run') });
  const result = await send(port, { headers: { 'X-Oversized': 'x'.repeat(17 * 1024) } });
  assert.equal(result.status, 431);
});

test('incomplete headers are disconnected by the header deadline', async t => {
  const port = await running(t, { headersTimeoutMs: 60 });
  const socket = connect(port, '127.0.0.1');
  t.after(() => socket.destroy());
  const response = new Promise((resolve, reject) => {
    let text = '';
    socket.on('data', chunk => { text += chunk.toString(); });
    socket.once('error', reject);
    socket.once('end', () => resolve(text));
  });
  socket.write('POST /relay HTTP/1.1\r\nHost: localhost\r\n');
  assert.match(await bounded(response), /^HTTP\/1\.1 408 /);
});

test('the response deadline cancels a body that stalls after headers arrive', async t => {
  const cancelled = deferred();
  const port = await running(t, { responseTimeoutMs: 60, handler: () => new Response(new ReadableStream({
    start(controller) { controller.enqueue(new TextEncoder().encode('data: partial\n\n')); },
    cancel() { cancelled.resolve(); },
  }), { headers: { 'Content-Type': 'text/event-stream' } }) });
  const request = httpRequest({ hostname: '127.0.0.1', port, path: '/relay', method: 'POST' });
  const interrupted = new Promise((resolve, reject) => {
    request.once('error', reject);
    request.once('response', response => {
      let text = '';
      response.on('data', chunk => { text += chunk.toString(); });
      response.once('aborted', () => resolve(text));
      response.once('end', () => reject(new Error('Stalled body ended successfully')));
      response.on('error', () => {});
    });
  });
  request.end('{}');
  assert.equal(await bounded(interrupted), 'data: partial\n\n');
  await bounded(cancelled.promise);
});

test('an occupied generation slot preserves OAuth, models, preflight, and health capacity until the stream ends', async t => {
  let streamController;
  const entered = deferred();
  const port = await running(t, { maxConcurrent: 1, handler: async request => {
    if (new URL(request.url).pathname === '/health') return Response.json({ status: 'ok' });
    const payload = JSON.parse(await request.text());
    if (payload.url !== 'https://chatgpt.com/backend-api/codex/responses') return new Response('control');
    return new Response(new ReadableStream({ start(controller) {
      streamController = controller;
      controller.enqueue(new TextEncoder().encode('data: partial\n\n'));
      entered.resolve();
    } }), { headers: { 'Content-Type': 'text/event-stream' } });
  } });
  const pending = send(port, { body: envelope('https://chatgpt.com/backend-api/codex/responses') });
  pending.catch(() => {});
  try {
    await bounded(entered.promise);
    for (const url of [
      'https://auth.openai.com/api/accounts/deviceauth/usercode',
      'https://auth.openai.com/api/accounts/deviceauth/token',
      'https://auth.openai.com/oauth/token',
    ]) assert.equal((await send(port, { body: JSON.stringify({ url, method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: '{}',
    }) })).status, 200);
    assert.equal((await send(port, { body: envelope('https://chatgpt.com/backend-api/codex/models?client_version=1.0.0', 'GET') })).status, 200);
    assert.equal((await send(port, { method: 'OPTIONS', body: '' })).status, 204);
    assert.equal((await send(port, { path: '/health', method: 'GET', body: '' })).status, 200);
    assert.equal((await send(port, { body: envelope('https://chatgpt.com/backend-api/codex/responses') })).status, 503);
    const status = await statusOf(port);
    assert.equal(status.active.generation, 1);
    assert.equal(status.active.control, 0);
  } finally { streamController?.close(); }
  assert.equal((await pending).status, 200);
  assert.deepEqual((await statusOf(port)).active, { admitted: 0, generation: 0, control: 0 });
});

test('control capacity is independently bounded and recovers after client cancellation', async t => {
  const entered = deferred();
  const cancelled = deferred();
  let first = true;
  const port = await running(t, { maxConcurrent: 1, maxControlConcurrent: 1, handler: async request => {
    const payload = JSON.parse(await request.text());
    if (payload.url === 'https://auth.openai.com/oauth/token' && first) {
      first = false;
      entered.resolve();
      await new Promise(resolve => request.signal.addEventListener('abort', () => {
        cancelled.resolve(); resolve();
      }, { once: true }));
    }
    return new Response('ready');
  } });
  const request = httpRequest({ hostname: '127.0.0.1', port, path: '/relay', method: 'POST' });
  request.on('error', () => {});
  request.end(envelope('https://auth.openai.com/oauth/token'));
  try {
    await bounded(entered.promise);
    const busy = await send(port, { body: envelope('https://auth.openai.com/oauth/token') });
    assert.equal(busy.status, 503);
    assert.equal((await send(port, { body: envelope('https://chatgpt.com/backend-api/codex/responses') })).status, 200);
    const during = await statusOf(port);
    assert.deepEqual(during.active, { admitted: 1, generation: 0, control: 1 });
    assert.equal(during.failures.control_busy, 1);
  } finally { request.destroy(); }
  await bounded(cancelled.promise);
  assert.equal((await send(port, { body: envelope('https://auth.openai.com/oauth/token') })).status, 200);
  const after = await statusOf(port);
  assert.deepEqual(after.active, { admitted: 0, generation: 0, control: 0 });
  assert.equal(after.failures.client_aborted, 1);
});

test('only exact control envelopes can use reserved control slots', async t => {
  const entered = deferred();
  const release = deferred();
  let first = true;
  const port = await running(t, { maxConcurrent: 1, handler: async () => {
    if (first) { first = false; entered.resolve(); await release.promise; }
    return new Response('ready');
  } });
  const pending = send(port);
  pending.catch(() => {});
  try {
    await bounded(entered.promise);
    for (const [url, method] of [
      ['https://auth.openai.com/oauth/token?extra=1', 'POST'],
      ['https://auth.openai.com/api/accounts/deviceauth/other', 'POST'],
      ['https://auth.openai.com/oauth/token', 'GET'],
      ['https://chatgpt.com/backend-api/codex/models?client_version=2.0.0', 'GET'],
      ['https://chatgpt.com/backend-api/codex/models?client_version=1.0.0', 'POST'],
      ['https://attacker.invalid/oauth/token', 'POST'],
    ]) assert.equal((await send(port, { body: envelope(url, method) })).status, 503);
  } finally { release.resolve(); }
  await pending;
});

test('invalid control envelopes cannot consume reserved capacity when generation is saturated', async t => {
  const entered = deferred();
  const release = deferred();
  let first = true;
  const port = await running(t, { maxConcurrent: 1, handler: async () => {
    if (first) { first = false; entered.resolve(); await release.promise; }
    return new Response('ready');
  } });
  const models = JSON.parse(envelope('https://chatgpt.com/backend-api/codex/models?client_version=1.0.0', 'GET'));
  const token = JSON.parse(envelope('https://auth.openai.com/oauth/token'));
  const pending = send(port);
  pending.catch(() => {});
  try {
    await bounded(entered.promise);
    for (const payload of [
      { ...models, headers: {} },
      { ...models, headers: { Authorization: 'invalid-synthetic-token' } },
      { ...models, headers: null },
      { ...models, headers: { ...models.headers, Cookie: 'synthetic-private-cookie' } },
      { ...models, body: '{}' },
      { ...models, timeout_ms: null },
      { ...token, body: {} },
      { ...token, headers: { 'Content-Type': 'text/plain' } },
    ]) assert.equal((await send(port, { body: JSON.stringify(payload) })).status, 503);
  } finally { release.resolve(); }
  await pending;
});

test('slow uploads have a bounded total admission budget while preflight and health remain available', async t => {
  const port = await running(t, { maxAdmitted: 2, handler: request => {
    return new URL(request.url).pathname === '/health' ? Response.json({ status: 'ok' }) : new Response('ready');
  } });
  const requests = [];
  try {
    for (let i = 0; i < 2; i++) {
      const request = httpRequest({ hostname: '127.0.0.1', port, path: '/relay', method: 'POST',
        headers: { 'Content-Length': '100' } });
      request.on('error', () => {});
      request.write('{');
      requests.push(request);
    }
    for (let i = 0; i < 20 && (await statusOf(port)).active.admitted !== 2; i++) await delay(5);
    assert.deepEqual((await statusOf(port)).active, { admitted: 2, generation: 0, control: 0 });
    assert.equal((await send(port)).status, 503);
    assert.equal((await send(port, { method: 'OPTIONS', body: '' })).status, 204);
    assert.equal((await send(port, { path: '/health', method: 'GET', body: '' })).status, 200);
    assert.equal((await statusOf(port)).failures.admission_busy, 1);
  } finally { requests.forEach(request => request.destroy()); }
  for (let i = 0; i < 20 && (await statusOf(port)).active.admitted; i++) await delay(5);
  const after = await statusOf(port);
  assert.equal(after.active.admitted, 0);
  assert.equal(after.failures.client_aborted, 2);
});

test('preflight rejects unapproved origins and bodies without using generation slots', async t => {
  const port = await running(t, { handler: () => { throw new Error('must not run'); } });
  const unapproved = await send(port, { method: 'OPTIONS', body: '', origin: 'https://attacker.invalid' });
  assert.equal(unapproved.status, 403);
  assert.equal(unapproved.headers['access-control-allow-origin'], undefined);
  assert.equal((await send(port, { method: 'OPTIONS', body: 'synthetic-private-body', headers: { 'Content-Length': '22' } })).status, 400);
  assert.equal((await send(port, { method: 'OPTIONS', body: '' })).status, 204);
});

test('private status contains only numeric aggregates and refuses browser origins', async t => {
  const port = await running(t, { handler: request => {
    return new URL(request.url).pathname === '/health' ? Response.json({ status: 'ok' }) : new Response('synthetic-private-reply');
  } });
  const publicRequest = await send(port, { path: '/status', method: 'GET', body: '' });
  assert.equal(publicRequest.status, 403);
  assert.equal(publicRequest.headers['access-control-allow-origin'], undefined);
  await send(port, { body: '{"private":"synthetic-private-token"}' });
  const status = await statusOf(port);
  assert.deepEqual(status.capacity, { generation: 16, control: 4, admission: 24 });
  assert.equal(status.completed, 1);
  assert.equal(typeof status.worker, 'object');
  const numericLeaves = value => Object.values(value).every(item => {
    return typeof item === 'object' && item !== null ? numericLeaves(item) : typeof item === 'number';
  });
  assert.equal(numericLeaves(status), true);
  assert.doesNotMatch(JSON.stringify(status), /synthetic|Bearer|token|prompt|timestamp|address/);
});

test('stream failures release generation capacity and increment aggregate failure counters', async t => {
  let first = true;
  const port = await running(t, { maxConcurrent: 1, handler: () => {
    if (!first) return new Response('ready');
    first = false;
    let sent = false;
    return new Response(new ReadableStream({ pull(controller) {
      if (!sent) { sent = true; controller.enqueue(new TextEncoder().encode('data: partial\n\n')); }
      else controller.error(new Error('synthetic-private-failure'));
    } }));
  } });
  await assert.rejects(send(port));
  assert.equal((await send(port)).status, 200);
  const status = await statusOf(port);
  assert.equal(status.active.generation, 0);
  assert.equal(status.failures.stream_failed, 1);
  assert.equal(status.failures.client_aborted, 0);
  assert.doesNotMatch(JSON.stringify(status), /synthetic-private/);
});

test('the real Worker delivers an HTTP SSE frame before the terminal event arrives', async t => {
  const initial = 'data: {"type":"response.output_text.delta","delta":"progress"}\n\n';
  const terminal = 'data: {"type":"response.completed"}\n\n';
  let source, cancelled = false;
  t.mock.method(globalThis, 'fetch', async () => new Response(new ReadableStream({
    start(controller) { source = controller; controller.enqueue(new TextEncoder().encode(initial)); },
    cancel() { cancelled = true; },
  }), { headers: { 'Content-Type': 'text/event-stream' } }));
  const port = await running(t, { maxConcurrent: 1 });
  const firstFrame = deferred();
  const request = httpRequest({ hostname: '127.0.0.1', port, path: '/relay', method: 'POST',
    headers: { Origin: ORIGIN, 'Content-Type': 'application/json' } });
  const pending = responseOf(request);
  pending.catch(() => {});
  request.once('response', response => response.once('data', chunk => firstFrame.resolve(chunk.toString())));
  request.end(envelope('https://chatgpt.com/backend-api/codex/responses'));
  try {
    assert.equal(await bounded(firstFrame.promise), initial);
    assert.equal((await statusOf(port)).active.generation, 1);
    assert.equal((await send(port, { method: 'OPTIONS', body: '' })).status, 204);
    source.enqueue(new TextEncoder().encode(terminal));
    const result = await bounded(pending);
    assert.equal(result.status, 200);
    assert.equal(result.body, initial + terminal);
    assert.equal(cancelled, true);
    assert.equal((await statusOf(port)).active.generation, 0);
  } finally {
    if (!cancelled) source?.close();
    request.destroy();
  }
});

test('a real Worker stream failure reaches HTTP as a sanitized error event and a safe counter', async t => {
  const initial = 'data: {"type":"response.output_text.delta","delta":"progress"}\n\n';
  let source;
  t.mock.method(globalThis, 'fetch', async () => new Response(new ReadableStream({
    start(controller) { source = controller; controller.enqueue(new TextEncoder().encode(initial)); },
  }), { headers: { 'Content-Type': 'text/event-stream' } }));
  const port = await running(t);
  const before = (await statusOf(port)).worker.upstream_read_failed;
  const firstFrame = deferred();
  const request = httpRequest({ hostname: '127.0.0.1', port, path: '/relay', method: 'POST',
    headers: { Origin: ORIGIN, 'Content-Type': 'application/json' } });
  const pending = responseOf(request);
  pending.catch(() => {});
  request.once('response', response => response.once('data', () => firstFrame.resolve()));
  request.end(envelope('https://chatgpt.com/backend-api/codex/responses'));
  try {
    await bounded(firstFrame.promise);
    source.error(new Error('synthetic-private-upstream-failure'));
    const result = await bounded(pending);
    assert.equal(result.status, 200);
    assert.ok(result.body.startsWith(initial));
    assert.match(result.body, /event: error\ndata: \{"type":"error","error":\{"code":"provider_connection_failed","reason":"upstream_read_failed"\}\}\n\n/);
    assert.doesNotMatch(result.body, /synthetic-private|Bearer|\bat\s/);
    const status = await statusOf(port);
    assert.equal(status.worker.upstream_read_failed, before + 1);
    assert.deepEqual(status.active, { admitted: 0, generation: 0, control: 0 });
  } finally { request.destroy(); }
});

for (const port of ['0', '65536', 'synthetic-secret-token']) {
  test(`the executable rejects invalid PORT configuration (${port === 'synthetic-secret-token' ? 'non-numeric' : port})`, async () => {
    const child = spawn(process.execPath, [fileURLToPath(new URL('../scripts/run_public_codex_relay.mjs', import.meta.url))], {
      env: { ...process.env, PORT: port }, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
    });
    let output = '';
    child.stdout.on('data', chunk => { output += chunk.toString(); });
    child.stderr.on('data', chunk => { output += chunk.toString(); });
    const code = await bounded(new Promise((resolve, reject) => {
      child.once('error', reject); child.once('close', resolve);
    }));
    assert.equal(code, 1);
    assert.match(output, /PORT must be an integer/);
    assert.doesNotMatch(output, /synthetic-secret-token/);
  });
}
