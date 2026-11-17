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
const MAX_RESPONSE = 4 * 1024 * 1024

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

async function readLimited(stream, maximum, stopAtCodexEnd = false, diagnostic = null) {
  if (!stream) return new Uint8Array()
  const reader = stream.getReader()
  const chunks = []
  let length = 0
  const decoder = stopAtCodexEnd ? new TextDecoder() : null
  let pendingLine = '', dataLines = []
  const terminalEvent = line => {
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
    if (line || !dataLines.length) return false
    const data = dataLines.join('\n').trim()
    dataLines = []
    if (data === '[DONE]') return true
    try {
      return ['response.completed', 'response.done', 'response.failed', 'response.incomplete'].includes(JSON.parse(data)?.type)
    } catch { return false }
  }
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      length += value.byteLength
      if (diagnostic) diagnostic.response_bytes = length
      if (length > maximum) {
        await reader.cancel()
        throw new RangeError('Body exceeds supported size')
      }
      chunks.push(value)
      if (decoder) {
        pendingLine += decoder.decode(value, { stream: true })
        let index, complete = false
        while ((index = pendingLine.indexOf('\n')) !== -1) {
          complete = terminalEvent(pendingLine.slice(0, index).replace(/\r$/, ''))
          pendingLine = pendingLine.slice(index + 1)
          if (complete) break
        }
        if (complete) {
          if (diagnostic) {
            diagnostic.terminal_seen = true
            diagnostic.stage = 'terminal_cancel'
          }
          await reader.cancel()
          break
        }
      }
    }
  } finally { reader.releaseLock() }
  const bytes = new Uint8Array(length)
  let offset = 0
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
  return bytes
}

function providerFailure(upstream, bytes, target) {
  const text = new TextDecoder().decode(bytes)
  let value
  try { value = JSON.parse(text) } catch {}
  const contentType = upstream.headers.get('Content-Type') || ''
  const format = value && typeof value === 'object' ? 'json'
    : /text\/html/i.test(contentType) || /^\s*<!?(?:doctype|html)/i.test(text) ? 'html' : 'text'
  let code = 'provider_request_failed'
  const rawCode = typeof value?.error === 'string' ? value.error : value?.error?.code || value?.error?.type
  if (target.hostname === 'auth.openai.com' && typeof rawCode === 'string' && /^[a-z0-9_]{1,80}$/.test(rawCode)) code = rawCode
  else if (rawCode === 'unsupported_country_region_territory') code = 'provider_region_blocked'
  else if (['model_not_found', 'unsupported_model', 'invalid_token', 'token_expired', 'account_deactivated', 'usage_limit_reached', 'insufficient_quota'].includes(rawCode)) code = rawCode
  else if (upstream.status === 403 && upstream.headers.get('cf-mitigated') === 'challenge') code = 'provider_challenge'
  else if (upstream.status === 403 && format === 'html') code = 'provider_access_blocked'
  const failure = { error: code, upstream_format: format }
  const edgeCode = text.match(/\berror(?:\s+code)?\s*:\s*(\d{4})\b/i)?.[1]
  if (edgeCode && upstream.status === 403 && format !== 'json' && ['provider_request_failed', 'provider_access_blocked'].includes(code)) {
    failure.error = 'provider_access_blocked'
    failure.upstream_edge_code = Number(edgeCode)
  }
  return failure
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
    let payload, target, headers, timeoutMs = 600000
    try {
      if (!request.headers.get('Content-Type')?.startsWith('application/json')) throw new TypeError()
      payload = JSON.parse(new TextDecoder().decode(await readLimited(request.body, 2 * 1024 * 1024)))
      if (!payload || typeof payload.url !== 'string') throw new TypeError()
      if (Object.hasOwn(payload, 'timeout_ms')) {
        if (!Number.isInteger(payload.timeout_ms) || payload.timeout_ms < 1000 || payload.timeout_ms > 600000) throw new TypeError()
        timeoutMs = payload.timeout_ms
      }
      target = new URL(payload.url)
      if (target.protocol !== 'https:' || target.username || target.password || target.port || target.hash) throw new TypeError()
      const models = target.hostname === 'chatgpt.com' && target.pathname === '/backend-api/codex/models'
      if (models) {
        if (payload.method !== 'GET' || target.search !== '?client_version=1.0.0' || payload.body != null) throw new TypeError()
      } else if (payload.method !== 'POST' || typeof payload.body !== 'string' || target.search || !TARGETS.get(target.hostname)?.has(target.pathname)) throw new TypeError()
      if (!payload.headers || typeof payload.headers !== 'object' || Array.isArray(payload.headers)) throw new TypeError()
      headers = new Headers()
      for (const [name, value] of Object.entries(payload.headers)) {
        if (!HEADER_NAMES.has(name.toLowerCase()) || typeof value !== 'string' || value.length > 8000 || /[\r\n]/.test(value)) throw new TypeError()
        headers.set(name, value)
      }
      if (target.hostname !== 'auth.openai.com' && !/^Bearer \S+$/.test(headers.get('Authorization') || '')) throw new TypeError()
      if (payload.method === 'POST' && !['application/json', 'application/x-www-form-urlencoded'].includes(headers.get('Content-Type'))) throw new TypeError()
    } catch (error) {
      return json({ error: error instanceof RangeError ? 'request_too_large' : 'invalid_request' }, error instanceof RangeError ? 413 : 400, origin)
    }
    const started = Date.now()
    const diagnostic = { stage: 'connect', response_bytes: 0, terminal_seen: false }
    let abortReason = ''
    const controller = new AbortController()
    const abort = () => { abortReason ||= 'client_aborted'; controller.abort() }
    request.signal.addEventListener('abort', abort, { once: true })
    if (request.signal.aborted) abort()
    const timer = setTimeout(() => { abortReason ||= 'deadline_exceeded'; controller.abort() }, timeoutMs + 2000)
    try {
      const upstream = await fetch(target.href, { method: payload.method, headers, body: payload.method === 'POST' ? payload.body : undefined, redirect: 'manual', signal: controller.signal })
      if (upstream.status >= 300 && upstream.status < 400) return json({ error: 'provider_redirect_rejected' }, 502, origin)
      diagnostic.stage = 'read'
      const bytes = await readLimited(upstream.body, MAX_RESPONSE,
        upstream.ok && target.hostname === 'chatgpt.com' && target.pathname === '/backend-api/codex/responses', diagnostic)
      diagnostic.stage = 'respond'
      if (!upstream.ok) {
        return json(providerFailure(upstream, bytes, target), upstream.status, origin)
      }
      const prefix = new TextDecoder().decode(bytes.subarray(0, 256))
      const type = upstream.headers.get('Content-Type') || (/^\s*(?:data:|event:|:)/.test(prefix) ? 'text/event-stream' : 'application/json')
      if (!/^(application\/json|text\/event-stream)(?:;|$)/i.test(type)) return json({ error: 'provider_content_type_invalid' }, 502, origin)
      return new Response(bytes, { status: upstream.status, headers: { ...cors(origin), 'Content-Type': type } })
    } catch {
      const reason = abortReason || (diagnostic.response_bytes > MAX_RESPONSE ? 'response_too_large'
        : diagnostic.stage === 'terminal_cancel' ? 'terminal_cancel_failed'
        : diagnostic.stage === 'connect' ? 'upstream_connection_failed' : 'upstream_read_failed')
      return json({ error: 'provider_connection_failed', reason, ...diagnostic, elapsed_ms: Math.max(0, Date.now() - started) }, 502, origin)
    } finally {
      clearTimeout(timer)
      request.signal.removeEventListener('abort', abort)
    }
  },
}
