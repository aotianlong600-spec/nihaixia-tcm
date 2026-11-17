import { createServer } from 'node:http';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { pathToFileURL } from 'node:url';
import worker from './codex_relay_worker.mjs';

const APP_ORIGIN = 'https://aotianlong600-spec.github.io';

function errorResponse(incoming, outgoing, status, error, extra = {}) {
  const origin = incoming.headers.origin || '';
  let allowed = origin === APP_ORIGIN;
  try {
    const url = new URL(origin);
    allowed ||= url.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(url.hostname);
  } catch {}
  outgoing.writeHead(status, {
    'Content-Type': 'application/json', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff', Connection: 'close', Vary: 'Origin',
    ...(allowed ? {
      'Access-Control-Allow-Origin': origin,
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Expose-Headers': 'Content-Type, Retry-After',
    } : {}), ...extra,
  });
  outgoing.end(JSON.stringify({ error }));
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
  requestTimeoutMs = 15000, headersTimeoutMs = requestTimeoutMs, responseTimeoutMs = 110000,
} = {}) {
  let active = 0;
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
    const health = incoming.method === 'GET' && url.pathname === '/health' &&
      !incoming.headers['transfer-encoding'] && Number(incoming.headers['content-length'] || 0) === 0;
    if (!health && active >= maxConcurrent) {
      errorResponse(incoming, outgoing, 503, 'relay_busy', { 'Retry-After': '1' });
      return;
    }
    if (!health) active++;
    const controller = new AbortController();
    let released = false;
    let responseTimer;
    const cleanup = () => {
      if (released) return;
      released = true;
      if (!health) active--;
      clearTimeout(requestTimer);
      clearTimeout(responseTimer);
      incoming.off('aborted', onDisconnect);
      outgoing.off('finish', cleanup);
      outgoing.off('close', onClose);
    };
    const onDisconnect = () => { controller.abort(); cleanup(); };
    const onClose = () => {
      if (!outgoing.writableFinished) onDisconnect();
      else cleanup();
    };
    const fail = (status, error) => {
      controller.abort();
      if (!outgoing.headersSent && !outgoing.destroyed) errorResponse(incoming, outgoing, status, error);
      else outgoing.destroy();
    };
    const requestTimer = setTimeout(() => fail(408, 'request_timeout'), requestTimeoutMs);
    incoming.once('aborted', onDisconnect);
    outgoing.once('finish', cleanup);
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
      if (response.body) await pipeline(Readable.fromWeb(response.body), outgoing, { signal: controller.signal });
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
