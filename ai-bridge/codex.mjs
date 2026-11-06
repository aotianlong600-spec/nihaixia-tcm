import { pathToFileURL } from 'node:url';

export const CODEX_BASE = 'https://chatgpt.com/backend-api';
export const CODEX_ENDPOINT = CODEX_BASE + '/codex/responses';

const SAFE_DETAIL = /^[A-Za-z0-9_.-]{1,80}$/;

// Model capabilities come from the SDK catalog. Hand-built model objects make
// the SDK assume `reasoning.effort: "none"`, which newer Codex models reject.
async function resolveModel(config) {
  const fallback = {
    id: config.model, name: config.model, provider: 'openai-codex', api: 'openai-codex-responses',
    baseUrl: CODEX_BASE, reasoning: true, thinkingLevelMap: { off: null }, input: ['text'],
    maxTokens: config.maxTokens, contextWindow: 128000,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  };
  try {
    const { openaiCodexProvider } = await import('@earendil-works/pi-ai/providers/openai-codex');
    const known = openaiCodexProvider().getModels().find(item => item.id === config.model);
    if (!known) return fallback;
    return { ...known, provider: 'openai-codex', api: 'openai-codex-responses', baseUrl: CODEX_BASE,
      input: known.input?.length ? known.input : ['text'], maxTokens: config.maxTokens };
  } catch {
    return fallback;
  }
}

async function providerError(response) {
  const error = new Error('Codex transport failed');
  error.status = response.status;
  for (const header of ['retry-after', 'x-codex-primary-reset-after-seconds']) {
    const value = response.headers.get(header);
    if (/^\d{1,7}$/.test(value || '')) { error.retry_after = Number(value); break; }
  }
  try {
    const body = await response.clone().json();
    const value = body?.error || body;
    for (const key of ['code', 'type', 'param']) {
      if (typeof value?.[key] === 'string' && SAFE_DETAIL.test(value[key])) error[key] = value[key];
    }
  } catch { /* Keep only status when the body is not safe JSON. */ }
  return error;
}

export async function runCodex(config, { signal, onDelta, fetchImpl = globalThis.fetch }) {
  let completed = false, failed = false, reportedUsage = false, bytes = 0, pending = '';
  let transportFailure = null;
  const transport = async (input, init) => {
    if (String(input instanceof Request ? input.url : input) !== CODEX_ENDPOINT) throw Error('Unexpected Codex endpoint');
    const response = await fetchImpl(input, { ...init, signal, redirect: 'manual' });
    const contentType = response.headers.get('content-type');
    // The live Codex endpoint can stream SSE without a Content-Type header.
    // Only reject an explicit non-SSE type; a malformed body still fails closed
    // because the SDK can never emit a valid completion event from it.
    if (!response.ok || !response.body || (contentType && !contentType.includes('text/event-stream'))) {
      const failure = await providerError(response);
      transportFailure = failure;
      await response.body?.cancel();
      throw failure;
    }
    const decoder = new TextDecoder();
    const bounded = response.body.pipeThrough(new TransformStream({
      transform(chunk, output) {
        bytes += chunk.byteLength;
        if (bytes > 2 * 1024 * 1024) throw Error('Codex response too large');
        pending += decoder.decode(chunk, { stream: true });
        let newline;
        while ((newline = pending.indexOf('\n')) !== -1) {
          const line = pending.slice(0, newline); pending = pending.slice(newline + 1);
          if (!line.startsWith('data:')) continue;
          try {
            const event = JSON.parse(line.slice(5));
            if (['response.failed', 'response.incomplete', 'error'].includes(event.type)) failed = true;
            if (['response.completed', 'response.done'].includes(event.type)) {
              completed = event.response?.status === 'completed';
              reportedUsage = Boolean(event.response?.usage);
            }
          } catch { /* SDK parses payloads; malformed or missing terminal data never passes completion. */ }
        }
        output.enqueue(chunk);
      },
    }));
    return new Response(bounded, { status: response.status, headers: response.headers });
  };
  const { stream } = await import('@earendil-works/pi-ai/api/openai-codex-responses');
  const { normalizeContext } = await import('@earendil-works/pi-ai/utils/transcript');
  const model = await resolveModel(config);
  const events = stream(model, normalizeContext({ systemPrompt: config.system,
    messages: [{ role: 'user', content: config.input, timestamp: Date.now() }], tools: [] }),
    { apiKey: config.api_key, fetch: transport, signal, transport: 'sse', toolChoice: 'none',
      reasoningSummary: 'off', maxTokens: config.maxTokens, timeoutMs: config.timeoutMs, maxRetries: 0,
      cacheRetention: 'none', env: {}, headers: { originator: 'nihaixia-tcm' } });
  let text = '';
  for await (const event of events) {
    if (event.type === 'error') throw transportFailure ?? Error('Codex output unsupported or failed');
    if (event.type.startsWith('toolcall')) throw Error('Codex output unsupported or failed');
    if (event.type === 'text_delta') {
      text += event.delta;
      if (Buffer.byteLength(text) > 128 * 1024) throw Error('Codex output too large');
      onDelta(event.delta);
    }
    if (event.type === 'done') {
      if (!completed || failed || event.reason !== 'stop' || event.message.content.some(b => b.type === 'toolCall')) throw Error('Codex response incomplete');
      const usage = {};
      if (reportedUsage) for (const key of ['input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens']) {
        const n = event.message.usage[key]; if (Number.isSafeInteger(n) && n >= 0) usage[key] = n;
      }
      return { text, usage, stop_reason: 'stop' };
    }
  }
  throw Error('Codex response incomplete');
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url && process.argv[2] === '--models') {
  process.env = {};
  const { openaiCodexProvider } = await import('@earendil-works/pi-ai/providers/openai-codex');
  console.log(JSON.stringify(openaiCodexProvider().getModels().map(m => ({ id: m.id, name: m.name }))));
}
