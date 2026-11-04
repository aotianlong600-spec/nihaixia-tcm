import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const bridge = new URL('./bridge.mjs', import.meta.url);
const secret = 'fake-explicit-key';
const chunk = (text = '', finish = null) => `data: ${JSON.stringify({ id: 'synthetic', object: 'chat.completion.chunk', created: 1, model: 'synthetic-model', choices: [{ index: 0, delta: { content: text }, finish_reason: finish }] })}\n\n`;

async function fixture(handler, run) {
  const server = http.createServer(async (req, res) => {
    let body = '';
    for await (const data of req) body += data;
    handler(req, res, JSON.parse(body));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try { await run(`http://127.0.0.1:${server.address().port}/v1`); }
  finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}

function invoke(base_url, extra = {}, cancel = false) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [fileURLToPath(bridge)], {
      env: { ...process.env, OPENAI_API_KEY: 'environment-key-must-never-be-used',
        OPENAI_ORG_ID: 'environment-organization', OPENAI_PROJECT_ID: 'environment-project',
        OPENAI_LOG: 'debug', OPENAI_CUSTOM_HEADERS: 'X-Environment-Header: forbidden' },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    let stdout = '', stderr = '';
    const timer = setTimeout(() => { child.kill(); reject(new Error('Bridge did not terminate')); }, 12000);
    child.stdout.on('data', data => {
      stdout += data;
      if (cancel && stdout.includes('"delta"')) { child.stdin.write('{"type":"cancel"}\n'); cancel = false; }
    });
    child.stderr.on('data', data => { stderr += data; });
    child.on('error', reject);
    child.on('exit', code => {
      clearTimeout(timer);
      if (stderr) { reject(new Error('Bridge emitted stderr (implementation missing or leaked diagnostics)')); return; }
      let events;
      try { events = stdout.trim().split('\n').filter(Boolean).map(JSON.parse); }
      catch { reject(new Error(`Non JSONL output: ${stdout}`)); return; }
      resolve({ code, events, stdout });
    });
    child.stdin.write(JSON.stringify({ base_url, api_key: secret, model: 'synthetic-model', input: 'synthetic input', ...extra }) + '\n');
  });
}

test('streams a complete answer, uses only explicit credentials, and exits with stdin open', async () => {
  await fixture((req, res, body) => {
    assert.equal(req.url, '/v1/chat/completions');
    assert.equal(req.headers.authorization, `Bearer ${secret}`);
    assert.equal(req.headers['openai-organization'], undefined);
    assert.equal(req.headers['openai-project'], undefined);
    assert.equal(req.headers['x-environment-header'], undefined);
    assert.equal(body.messages.at(-1).content, 'synthetic input');
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    res.write(chunk('syn'));
    setTimeout(() => res.end(chunk('thetic', 'stop') + 'data: [DONE]\n\n'), 15);
  }, async url => {
    const { events } = await invoke(url);
    assert.equal(events.filter(e => e.type === 'delta').map(e => e.text).join(''), 'synthetic');
    assert.equal(events.at(-1).type, 'done');
    assert.equal(events.at(-1).text, 'synthetic');
    assert.equal(events.at(-1).stop_reason, 'stop');
    assert.deepEqual(events.at(-1).usage, {}, 'Missing usage must remain unknown, never fabricated zero');
  });
});

test('a stream without finish_reason cannot become a successful result', async () => {
  await fixture((req, res) => { res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.end(chunk('partial')); }, async url => {
    const { events } = await invoke(url);
    assert.equal(events.at(-1).type, 'error');
    assert.equal(events.some(e => e.type === 'done'), false);
  });
});

test('finish_reason without the SSE DONE marker remains incomplete', async () => {
  await fixture((req, res) => { res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.end(chunk('partial', 'stop')); }, async url => {
    assert.equal((await invoke(url)).events.at(-1).type, 'error');
  });
});

test('HTTP failure reports a safe code without echoing credentials or response body', async () => {
  await fixture((req, res) => { res.writeHead(401, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ error: { message: secret + ' synthetic input' } })); }, async url => {
    const result = await invoke(url);
    assert.equal(result.events.at(-1).type, 'error');
    assert.match(result.events.at(-1).message, /401/);
    assert.equal(result.stdout.includes(secret), false);
    assert.equal(result.stdout.includes('synthetic input'), false);
  });
});

test('cancellation aborts a live stream with one error terminal', async () => {
  await fixture((req, res) => { res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.write(chunk('partial')); }, async url => {
    const { events } = await invoke(url, {}, true);
    assert.equal(events.at(-1).code, 'cancelled');
    assert.equal(events.filter(e => e.type !== 'delta').length, 1);
  });
});

test('redirect is rejected without contacting the redirect destination', async () => {
  let redirected = 0;
  await fixture((req, res) => { redirected++; res.end('{}'); }, async target => {
    await fixture((req, res) => { res.writeHead(307, { Location: target + '/chat/completions' }); res.end(); }, async url => {
      assert.equal((await invoke(url)).events.at(-1).type, 'error');
      assert.equal(redirected, 0);
    });
  });
});

test('length, timeout and malformed parameters fail closed', async () => {
  await fixture((req, res) => { res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.end(chunk('truncated', 'length') + 'data: [DONE]\n\n'); }, async url => {
    assert.equal((await invoke(url)).events.at(-1).type, 'error');
    assert.equal((await invoke(url, { api_key: '' })).events.at(-1).code, 'invalid_request');
    assert.equal((await invoke(url, { max_output_tokens: 4097 })).events.at(-1).code, 'invalid_request');
    assert.equal((await invoke('http://example.com')).events.at(-1).code, 'invalid_request');
  });
  await fixture((req, res) => { res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.write(chunk('partial')); }, async url => {
    assert.equal((await invoke(url, { timeout_ms: 50 })).events.at(-1).code, 'timeout');
  });
});

test('reports token counts when the server supplies usage', async () => {
  await fixture((req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    res.end(chunk('ok', 'stop') + 'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}\n\ndata: [DONE]\n\n');
  }, async url => {
    const usage = (await invoke(url)).events.at(-1).usage;
    assert.equal(usage.input, 3);
    assert.equal(usage.output, 2);
    assert.equal(usage.totalTokens, 5);
  });
});

test('input and output byte limits fail without emitting oversized JSONL', async () => {
  let calls = 0;
  await fixture((req, res) => {
    calls++;
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    res.end(chunk('文'.repeat(30000), 'stop') + 'data: [DONE]\n\n');
  }, async url => {
    const largeInput = await invoke(url, { input: 'x'.repeat(1024 * 1024) });
    assert.equal(largeInput.events.at(-1).code, 'input_limit');
    assert.equal(calls, 0);
    const largeOutput = await invoke(url);
    assert.equal(largeOutput.events.at(-1).code, 'output_limit');
    assert.ok(Buffer.byteLength(largeOutput.stdout) <= 128 * 1024);
  });
});
