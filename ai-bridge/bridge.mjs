// This single-use child receives all configuration on stdin, including SDK logging/auth.
process.env = {};

const INPUT_LIMIT = 1024 * 1024;
const OUTPUT_LIMIT = 128 * 1024;
const controller = new AbortController();
let terminal = false, started = false, pending = Buffer.alloc(0), outputBytes = 0;
let status, text = '';
let timer = setTimeout(() => fail('timeout', 'Input deadline exceeded.'), 90000);

function frame(event) { return JSON.stringify(event) + '\n'; }

function finish(event) {
  if (terminal) return;
  terminal = true;
  clearTimeout(timer);
  controller.abort();
  process.stdin.pause();
  // Exit after flushing the sole terminal frame; the parent's stdin may remain open.
  process.stdout.write(frame(event), () => process.exit(event.type === 'done' ? 0 : 1));
}

function fail(code, message) {
  finish({ type: 'error', code, message });
}

function validate(value) {
  const allowed = ['base_url', 'api_key', 'model', 'input', 'system', 'max_output_tokens', 'timeout_ms', 'auth_mode'];
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !allowed.includes(key))) throw Error();
  for (const key of ['base_url', 'api_key', 'model', 'input']) {
    if (typeof value[key] !== 'string' || !value[key].trim()) throw Error();
  }
  if (value.system !== undefined && typeof value.system !== 'string') throw Error();
  if (value.api_key.length > 8192 || /[\x00-\x20\x7f]/.test(value.api_key)) throw Error();
  if (value.model.length > 256 || /[\x00-\x1f\x7f]/.test(value.model)) throw Error();
  const maxTokens = value.max_output_tokens ?? 2048;
  const timeoutMs = value.timeout_ms ?? 90000;
  if (!Number.isInteger(maxTokens) || maxTokens < 1 || maxTokens > 4096) throw Error();
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 90000) throw Error();
  if (!['api_key','codex'].includes(value.auth_mode ?? 'api_key')) throw Error();
  const url = new URL(value.base_url);
  if (url.username || url.password || url.search || url.hash || url.hostname.endsWith('.')) throw Error();
  const loopback = url.hostname === 'localhost' || url.hostname === '[::1]' || /^127(?:\.\d{1,3}){3}$/.test(url.hostname);
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback)) throw Error();
  const base = url.href.replace(/\/+$/, '');
  if (value.auth_mode === 'codex' && base !== 'https://chatgpt.com/backend-api') throw Error();
  return { ...value, base_url: base, maxTokens, timeoutMs };
}

async function run(request) {
  let config;
  try { config = validate(request); }
  catch { fail('invalid_request', 'Invalid model request parameters.'); return; }
  clearTimeout(timer);
  timer = setTimeout(() => fail('timeout', 'Model request deadline exceeded.'), config.timeoutMs);
  if (config.auth_mode === 'codex') {
    try {
      const { runCodex } = await import('./codex.mjs');
      const result = await runCodex(config, { signal: controller.signal, onDelta: delta => {
        if (terminal) throw Error();
        const next = text + delta;
        const line = frame({type:'delta',text:delta});
        const reserved = Buffer.byteLength(frame({type:'done',text:next,usage:{},stop_reason:'stop'})) + 512;
        if (outputBytes + Buffer.byteLength(line) + reserved > OUTPUT_LIMIT) {
          fail('output_limit','Model response exceeded the size limit.'); throw Error();
        }
        text = next; outputBytes += Buffer.byteLength(line); process.stdout.write(line);
      }});
      if (!terminal) finish({type:'done',text:result.text,usage:result.usage,stop_reason:'stop'});
    } catch { if (!terminal) fail('provider_error','Codex request failed or did not complete.'); }
    return;
  }
  const endpoint = config.base_url + '/chat/completions';
  let sawDone = false, usageReported = false;
  const transport = async (input, init) => {
    if (String(input instanceof Request ? input.url : input) !== endpoint) throw Error();
    const response = await fetch(input, { ...init, signal: controller.signal, redirect: 'manual' });
    status = response.status;
    if (!response.ok) {
      await response.body?.cancel();
      throw Error();
    }
    if (!response.headers.get('content-type')?.toLowerCase().includes('text/event-stream')) {
      await response.body?.cancel();
      throw Error();
    }
    let received = 0, sseLine = '';
    const decoder = new TextDecoder();
    const bounded = response.body.pipeThrough(new TransformStream({
      transform(chunk, output) {
        received += chunk.byteLength;
        // shortcut: cap SSE overhead at 2MiB; revisit for providers with larger metadata.
        if (received > 2 * INPUT_LIMIT) { fail('output_limit', 'Model response exceeded the size limit.'); throw Error(); }
        sseLine += decoder.decode(chunk, { stream: true });
        let newline;
        while ((newline = sseLine.indexOf('\n')) !== -1) {
          const complete = sseLine.slice(0, newline);
          if (/^data:\s*\[DONE\]\s*$/.test(complete)) sawDone = true;
          else if (complete.startsWith('data:')) {
            try { if (JSON.parse(complete.slice(5)).usage) usageReported = true; } catch { /* Pi validates SSE payloads. */ }
          }
          sseLine = sseLine.slice(newline + 1);
        }
        output.enqueue(chunk);
      },
    }));
    return new Response(bounded, { status: response.status, headers: response.headers });
  };
  const model = {
    id: config.model, name: config.model, api: 'openai-completions', provider: 'explicit-openai-compatible',
    baseUrl: config.base_url, reasoning: false, input: ['text'], maxTokens: 4096, contextWindow: 128000,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    compat: { supportsStore: false, supportsDeveloperRole: false, supportsReasoningEffort: false,
      supportsFinishReason: true, maxTokensField: 'max_tokens' },
  };
  try {
    const { stream } = await import('@earendil-works/pi-ai/api/openai-completions');
    const { normalizeContext } = await import('@earendil-works/pi-ai/utils/transcript');
    if (terminal) return;
    const events = stream(model, normalizeContext({
      systemPrompt: config.system,
      messages: [{ role: 'user', content: config.input, timestamp: Date.now() }],
    }), { apiKey: config.api_key, fetch: transport, signal: controller.signal,
      maxTokens: config.maxTokens, timeoutMs: config.timeoutMs, maxRetries: 0, cacheRetention: 'none', env: {} });
    for await (const event of events) {
      if (terminal) return;
      if (event.type.startsWith('toolcall')) { fail('unsupported_output', 'Tool calls are not supported.'); return; }
      if (event.type === 'text_delta') {
        const next = text + event.delta;
        const line = frame({ type: 'delta', text: event.delta });
        const reserved = Buffer.byteLength(frame({ type: 'done', text: next, usage: {}, stop_reason: 'stop' })) + 512;
        if (outputBytes + Buffer.byteLength(line) + reserved > OUTPUT_LIMIT) {
          fail('output_limit', 'Model response exceeded the size limit.'); return;
        }
        text = next;
        outputBytes += Buffer.byteLength(line);
        process.stdout.write(line);
      }
      if (event.type === 'error') {
        fail('provider_error', status && status !== 200 ? `Model request failed (HTTP ${status}).` : 'Model request failed or ended without a complete response.');
        return;
      }
      if (event.type === 'done') {
        if (!sawDone || event.reason !== 'stop' || event.message.rawStopReason !== 'stop' || event.message.content.some(block => block.type === 'toolCall')) {
          fail('incomplete', 'Model response did not finish normally.'); return;
        }
        const usage = {};
        for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens']) {
          const count = event.message.usage[key];
          if (usageReported && Number.isSafeInteger(count) && count >= 0) usage[key] = count;
        }
        finish({ type: 'done', text, usage, stop_reason: 'stop' });
        return;
      }
    }
    fail('incomplete', 'Model response ended without a terminal result.');
  } catch {
    if (!terminal) fail('provider_error', status ? `Model request failed (HTTP ${status}).` : 'Model request failed.');
  }
}

function line(data) {
  let message;
  try { message = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(data)); }
  catch { fail('invalid_request', 'Invalid JSON input.'); return; }
  if (!started) { started = true; void run(message); }
  else if (message?.type === 'cancel' && Object.keys(message).length === 1) fail('cancelled', 'Model request cancelled.');
  else fail('invalid_request', 'Invalid control message.');
}

process.stdin.on('data', data => {
  if (terminal) return;
  pending = Buffer.concat([pending, data]);
  let newline;
  while (!terminal && (newline = pending.indexOf(10)) !== -1) {
    if (newline > INPUT_LIMIT) { fail('input_limit', 'Input exceeded the size limit.'); return; }
    const complete = pending.subarray(0, newline);
    pending = pending.subarray(newline + 1);
    line(complete);
  }
  if (pending.length > INPUT_LIMIT) fail('input_limit', 'Input exceeded the size limit.');
});
process.stdin.on('end', () => {
  if (terminal) return;
  if (pending.length) { line(pending); pending = Buffer.alloc(0); }
  else if (!started) fail('invalid_request', 'Missing model request.');
});
process.stdin.on('error', () => fail('invalid_request', 'Input channel failed.'));
process.stdout.on('error', () => process.exit(1));
process.on('uncaughtException', () => fail('internal_error', 'Model bridge failed.'));
process.on('unhandledRejection', () => fail('internal_error', 'Model bridge failed.'));
