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

function send(port, { path = '/relay', method = 'POST', body = '{}', headers = {} } = {}) {
  const request = httpRequest({
    hostname: '127.0.0.1', port, path, method,
    headers: { Origin: ORIGIN, 'Content-Type': 'application/json', ...headers },
  });
  const response = responseOf(request);
  request.end(body);
  return bounded(response);
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
