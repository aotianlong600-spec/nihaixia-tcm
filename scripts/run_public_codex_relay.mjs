import { createServer } from 'node:http';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { pathToFileURL } from 'node:url';
import worker, { getRelayMetrics, isControlEnvelope } from './codex_relay_worker.mjs';

const APP_ORIGIN = 'https://aotianlong600-spec.github.io';

function allowedOrigin(origin) {
  if (origin === APP_ORIGIN) return true;
  try {
    const url = new URL(origin);
    return url.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(url.hostname);
  } catch { return false; }
}

function corsHeaders(incoming) {
  const origin = incoming.headers.origin || '';
  return allowedOrigin(origin) ? {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Expose-Headers': 'Content-Type, Retry-After',
    Vary: 'Origin',
  } : {};
}

function errorResponse(incoming, outgoing, status, error, extra = {}) {
  outgoing.writeHead(status, {
    'Content-Type': 'application/json', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff', Connection: 'close', Vary: 'Origin',
    ...corsHeaders(incoming), ...extra,
  });
  outgoing.end(JSON.stringify({ error }));
}

function bodyless(incoming) {
  return !incoming.headers['transfer-encoding'] && Number(incoming.headers['content-length'] || 0) === 0;
}

function requestClass(incoming, url, body) {
  if (incoming.method === 'POST' && url.pathname === '/relay') {
    try {
      const payload = JSON.parse(body.toString('utf8'));
      if (isControlEnvelope(payload)) return 'control';
    } catch {}
  }
  return 'generation';
}

function readBody(incoming, limit, signal) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    const cleanup = () => {
      incoming.off('data', onData);
      incoming.off('end', onEnd);
      incoming.off('error', onError);
      signal.removeEventListener('abort', onAbort);
    };
    const onError = error => { cleanup(); reject(error); };
    const onAbort = () => { incoming.pause(); onError(signal.reason); };
    const onEnd = () => { cleanup(); resolve(Buffer.concat(chunks, size)); };
    const onData = chunk => {
      size += chunk.length;
      if (size > limit) {
        incoming.pause();
        onError(new RangeError('request_too_large'));
      } else chunks.push(chunk);
    };
    incoming.on('data', onData);
    incoming.once('end', onEnd);
    incoming.once('error', onError);
    signal.addEventListener('abort', onAbort, { once: true });
    if (signal.aborted) onAbort();
  });
}

export function createRelayServer({
  handler = worker.fetch.bind(worker), bodyLimit = 2 * 1024 * 1024, maxConcurrent = 16,
  maxControlConcurrent = 4, maxAdmitted = 24,
  requestTimeoutMs = 15000, headersTimeoutMs = requestTimeoutMs, responseTimeoutMs = 610000,
} = {}) {
  const capacity = { generation: maxConcurrent, control: maxControlConcurrent, admission: maxAdmitted };
  const active = { admitted: 0, generation: 0, control: 0 };
  const counters = { completed: 0, failures: {
    admission_busy: 0, generation_busy: 0, control_busy: 0,
    invalid_request: 0, request_too_large: 0, request_timeout: 0,
    relay_timeout: 0, relay_internal_error: 0, client_aborted: 0,
    stream_failed: 0, http_4xx: 0, http_5xx: 0,
  } };
  return createServer({
    maxHeaderSize: 16 * 1024, headersTimeout: headersTimeoutMs,
    // The body timer below returns JSON/CORS; Node's native body timeout sends an empty 408.
    requestTimeout: 0,
    connectionsCheckingInterval: Math.min(1000, headersTimeoutMs, requestTimeoutMs),
  }, async (incoming, outgoing) => {
    let url;
    try {
      if (!incoming.url.startsWith('/') || incoming.url.startsWith('//')) throw new TypeError();
      url = new URL(`http://127.0.0.1${incoming.url}`);
    } catch {
      errorResponse(incoming, outgoing, 400, 'invalid_request');
      return;
    }
    if (url.pathname === '/status') {
      const local = ['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(incoming.socket.remoteAddress);
      const permitted = local && incoming.method === 'GET' && bodyless(incoming) && !Object.hasOwn(incoming.headers, 'origin');
      outgoing.writeHead(permitted ? 200 : 403, {
        'Content-Type': 'application/json', 'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff', Connection: 'close',
      });
      outgoing.end(JSON.stringify(permitted ? { capacity, active, ...counters, worker: getRelayMetrics() } : { error: 'status_not_available' }));
      return;
    }
    if (incoming.method === 'OPTIONS' && url.pathname === '/relay') {
      if (!allowedOrigin(incoming.headers.origin || '')) errorResponse(incoming, outgoing, 403, 'origin_not_allowed');
      else if (!bodyless(incoming)) errorResponse(incoming, outgoing, 400, 'invalid_request');
      else {
        outgoing.writeHead(204, { ...corsHeaders(incoming), 'Cache-Control': 'no-store' });
        outgoing.end();
      }
      return;
    }
    const health = incoming.method === 'GET' && url.pathname === '/health' && bodyless(incoming);
    if (!health && active.admitted >= maxAdmitted) {
      counters.failures.admission_busy++;
      errorResponse(incoming, outgoing, 503, 'relay_busy', { 'Retry-After': '1' });
      return;
    }
    if (!health) active.admitted++;
    const controller = new AbortController();
    let released = false;
    let slot = null;
    let failure = '';
    let responseTimer;
    const markFailure = reason => {
      if (!failure) { failure = reason; counters.failures[reason]++; }
    };
    const cleanup = () => {
      if (released) return;
      released = true;
      if (!health) active.admitted--;
      if (slot) active[slot]--;
      clearTimeout(requestTimer);
      clearTimeout(responseTimer);
      incoming.off('aborted', onDisconnect);
      outgoing.off('finish', onFinish);
      outgoing.off('close', onClose);
    };
    const onFinish = () => {
      if (!health) {
        counters.completed++;
        if (outgoing.statusCode >= 500) counters.failures.http_5xx++;
        else if (outgoing.statusCode >= 400) counters.failures.http_4xx++;
      }
      cleanup();
    };
    const onDisconnect = () => { markFailure('client_aborted'); controller.abort(); cleanup(); };
    const onClose = () => {
      if (!outgoing.writableFinished) onDisconnect();
      else cleanup();
    };
    const fail = (status, error) => {
      markFailure(error);
      controller.abort();
      if (!outgoing.headersSent && !outgoing.destroyed) errorResponse(incoming, outgoing, status, error);
      else outgoing.destroy();
    };
    const requestTimer = setTimeout(() => fail(408, 'request_timeout'), requestTimeoutMs);
    incoming.once('aborted', onDisconnect);
    outgoing.once('finish', onFinish);
    outgoing.once('close', onClose);
    try {
      if (Number(incoming.headers['content-length']) > bodyLimit) {
        fail(413, 'request_too_large');
        return;
      }
      let body;
      try { body = await readBody(incoming, bodyLimit, controller.signal); }
      catch (error) {
        if (!controller.signal.aborted) fail(error instanceof RangeError ? 413 : 400,
          error instanceof RangeError ? 'request_too_large' : 'invalid_request');
        return;
      }
      clearTimeout(requestTimer);
      if (!health) {
        const kind = requestClass(incoming, url, body);
        if (active[kind] >= capacity[kind]) {
          markFailure(`${kind}_busy`);
          errorResponse(incoming, outgoing, 503, 'relay_busy', { 'Retry-After': '1' });
          return;
        }
        slot = kind;
        active[slot]++;
      }
      responseTimer = setTimeout(() => fail(504, 'relay_timeout'), responseTimeoutMs);
      const request = new Request(url, {
        method: incoming.method, headers: incoming.headers, signal: controller.signal,
        body: ['GET', 'HEAD'].includes(incoming.method) ? undefined : body,
      });
      const response = await handler(request);
      if (controller.signal.aborted || outgoing.destroyed || outgoing.writableEnded) {
        await response.body?.cancel();
        return;
      }
      outgoing.writeHead(response.status, Object.fromEntries(response.headers));
      if (response.body) {
        const stream = Readable.fromWeb(response.body);
        stream.once('error', () => { if (!controller.signal.aborted) markFailure('stream_failed'); });
        await pipeline(stream, outgoing, { signal: controller.signal });
      }
      else outgoing.end();
    } catch {
      if (!controller.signal.aborted) fail(500, 'relay_internal_error');
    }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const rawPort = process.env.PORT || '18769';
  const port = Number(rawPort);
  if (!/^\d+$/.test(rawPort) || !Number.isInteger(port) || port < 1 || port > 65535) {
    console.error('PORT must be an integer between 1 and 65535.');
    process.exitCode = 1;
  } else {
    const server = createRelayServer();
    server.once('error', () => { console.error('Relay server failed to start.'); process.exitCode = 1; });
    server.listen(port, '127.0.0.1', () => console.log(`Relay listening on http://127.0.0.1:${port}`));
    const shutdown = () => {
      const deadline = setTimeout(() => server.closeAllConnections(), 10000);
      deadline.unref();
      server.close(() => clearTimeout(deadline));
      server.closeIdleConnections();
    };
    process.once('SIGTERM', shutdown);
    process.once('SIGINT', shutdown);
  }
}
