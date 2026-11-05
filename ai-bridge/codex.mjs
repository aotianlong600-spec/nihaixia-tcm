import { pathToFileURL } from 'node:url';

export const CODEX_BASE = 'https://chatgpt.com/backend-api';
export const CODEX_ENDPOINT = CODEX_BASE + '/codex/responses';

export async function runCodex(config, { signal, onDelta, fetchImpl = globalThis.fetch }) {
  let completed = false, failed = false, reportedUsage = false, bytes = 0, pending = '';
  const transport = async (input, init) => {
    if (String(input instanceof Request ? input.url : input) !== CODEX_ENDPOINT) throw Error('Unexpected Codex endpoint');
    const response = await fetchImpl(input, { ...init, signal, redirect: 'manual' });
    if (!response.ok || !response.headers.get('content-type')?.includes('text/event-stream') || !response.body) {
      await response.body?.cancel(); throw Error('Codex transport failed');
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
  const model = { id: config.model, name: config.model, provider: 'openai-codex', api: 'openai-codex-responses',
    baseUrl: CODEX_BASE, reasoning: true, input: ['text'], maxTokens: 4096, contextWindow: 128000,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
  const events = stream(model, normalizeContext({ systemPrompt: config.system,
    messages: [{ role: 'user', content: config.input, timestamp: Date.now() }], tools: [] }),
    { apiKey: config.api_key, fetch: transport, signal, transport: 'sse', toolChoice: 'none',
      reasoningSummary: 'off', maxTokens: config.maxTokens, timeoutMs: config.timeoutMs, maxRetries: 0,
      cacheRetention: 'none', env: {}, headers: { originator: 'nihaixia-tcm' } });
  let text = '';
  for await (const event of events) {
    if (event.type.startsWith('toolcall') || event.type === 'error') throw Error('Codex output unsupported or failed');
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
