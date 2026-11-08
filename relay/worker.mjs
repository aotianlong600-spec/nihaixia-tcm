const APP_ORIGIN = 'https://aotianlong600-spec.github.io'
const TARGETS = new Map([
  ['auth.openai.com', new Set(['/api/accounts/deviceauth/usercode', '/api/accounts/deviceauth/token', '/oauth/token'])],
  ['chatgpt.com', new Set(['/backend-api/codex/responses'])],
  ['api.openai.com', new Set(['/v1/chat/completions', '/v1/responses'])],
  ['api.deepseek.com', new Set(['/chat/completions', '/v1/chat/completions'])],
  ['api.sensenova.cn', new Set(['/v1/chat/completions', '/v1/llm/chat-completions'])],
  ['api.siliconflow.cn', new Set(['/v1/chat/completions'])],
  ['openrouter.ai', new Set(['/api/v1/chat/completions'])],
  ['open.bigmodel.cn', new Set(['/api/paas/v4/chat/completions'])],
  ['dashscope.aliyuncs.com', new Set(['/compatible-mode/v1/chat/completions'])],
])
const HEADER_NAMES = new Set(['authorization', 'content-type', 'accept', 'chatgpt-account-id', 'openai-beta', 'originator', 'user-agent'])

function allowedOrigin(origin) {
  if (origin === APP_ORIGIN) return true
  try {
    const url = new URL(origin)
    return url.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(url.hostname)
  } catch { return false }
}

function cors(origin) {
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Expose-Headers': 'Content-Type, Retry-After',
    'Cache-Control': 'no-store',
    Vary: 'Origin',
  }
}

function json(body, status, origin) {
  return new Response(JSON.stringify(body), { status, headers: { ...cors(origin), 'Content-Type': 'application/json' } })
}

async function readLimited(stream, maximum) {
  if (!stream) return new Uint8Array()
  const reader = stream.getReader()
  const chunks = []
  let length = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      length += value.byteLength
      if (length > maximum) {
        await reader.cancel()
        throw new RangeError('Body exceeds supported size')
      }
      chunks.push(value)
    }
  } finally { reader.releaseLock() }
  const bytes = new Uint8Array(length)
  let offset = 0
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
  return bytes
}

export default {
  async fetch(request) {
    const origin = request.headers.get('Origin') || ''
    const path = new URL(request.url).pathname
    if (path === '/health' && request.method === 'GET') {
      return json({ status: 'ok', providers: [...TARGETS.keys()] }, 200, allowedOrigin(origin) ? origin : APP_ORIGIN)
    }
    if (path !== '/relay') return json({ error: 'not_found' }, 404, APP_ORIGIN)
    if (!allowedOrigin(origin)) return json({ error: 'origin_not_allowed' }, 403, APP_ORIGIN)
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors(origin) })
    if (request.method !== 'POST') return json({ error: 'method_not_allowed' }, 405, origin)
    let payload, target, headers
    try {
      if (!request.headers.get('Content-Type')?.startsWith('application/json')) throw new TypeError()
      payload = JSON.parse(new TextDecoder().decode(await readLimited(request.body, 2 * 1024 * 1024)))
      if (!payload || payload.method !== 'POST' || typeof payload.url !== 'string' || typeof payload.body !== 'string') throw new TypeError()
      target = new URL(payload.url)
      if (target.protocol !== 'https:' || target.username || target.password || target.port || target.search || target.hash || !TARGETS.get(target.hostname)?.has(target.pathname)) throw new TypeError()
      if (!payload.headers || typeof payload.headers !== 'object' || Array.isArray(payload.headers)) throw new TypeError()
      headers = new Headers()
      for (const [name, value] of Object.entries(payload.headers)) {
        if (!HEADER_NAMES.has(name.toLowerCase()) || typeof value !== 'string' || value.length > 8000 || /[\r\n]/.test(value)) throw new TypeError()
        headers.set(name, value)
      }
      if (target.hostname !== 'auth.openai.com' && !/^Bearer \S+$/.test(headers.get('Authorization') || '')) throw new TypeError()
      if (!['application/json', 'application/x-www-form-urlencoded'].includes(headers.get('Content-Type'))) throw new TypeError()
    } catch (error) {
      return json({ error: error instanceof RangeError ? 'request_too_large' : 'invalid_request' }, error instanceof RangeError ? 413 : 400, origin)
    }
    const controller = new AbortController()
    const abort = () => controller.abort()
    request.signal.addEventListener('abort', abort, { once: true })
    if (request.signal.aborted) abort()
    const timer = setTimeout(() => controller.abort(), 95000)
    try {
      const upstream = await fetch(target.href, { method: 'POST', headers, body: payload.body, redirect: 'manual', signal: controller.signal })
      if (upstream.status >= 300 && upstream.status < 400) return json({ error: 'provider_redirect_rejected' }, 502, origin)
      const bytes = await readLimited(upstream.body, 4 * 1024 * 1024)
      if (!upstream.ok) {
        let code = 'provider_request_failed'
        if (target.hostname === 'auth.openai.com') {
          try {
            const value = JSON.parse(new TextDecoder().decode(bytes))
            if (typeof value.error === 'string' && /^[a-z0-9_]{1,80}$/.test(value.error)) code = value.error
          } catch {}
        }
        return json({ error: code }, upstream.status, origin)
      }
      const type = upstream.headers.get('Content-Type') || 'application/json'
      if (!/^(application\/json|text\/event-stream)(?:;|$)/i.test(type)) return json({ error: 'provider_content_type_invalid' }, 502, origin)
      return new Response(bytes, { status: upstream.status, headers: { ...cors(origin), 'Content-Type': type } })
    } catch {
      return json({ error: 'provider_connection_failed' }, 502, origin)
    } finally {
      clearTimeout(timer)
      request.signal.removeEventListener('abort', abort)
    }
  },
}
