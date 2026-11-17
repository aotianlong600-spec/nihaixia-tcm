import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'

const source = await readFile(new URL('../scripts/codex_relay_worker.mjs', import.meta.url), 'utf8')
const { default: worker } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))
const origin = 'https://aotianlong600-spec.github.io'

function request(target = 'https://chatgpt.com/backend-api/codex/responses', requestOrigin = origin) {
  return new Request('https://relay.example/relay', {
    method: 'POST', headers: { Origin: requestOrigin, 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: target, method: 'POST', headers: {
      Authorization: 'Bearer synthetic-token', 'Content-Type': 'application/json',
    }, body: '{"model":"synthetic-model"}' }),
  })
}

for (const sample of [
  { label: 'challenge', headers: { 'Content-Type': 'text/html', 'cf-mitigated': 'challenge' }, body: '<html>Just a moment... synthetic-secret</html>', error: 'provider_challenge' },
  { label: 'HTML block', headers: { 'Content-Type': 'text/html' }, body: '<html>Access denied. synthetic-secret</html>', error: 'provider_access_blocked' },
  { label: 'region denial', headers: { 'Content-Type': 'application/json' }, body: '{"error":{"code":"unsupported_country_region_territory","message":"synthetic-secret"}}', error: 'provider_region_blocked' },
  { label: 'model denial', headers: { 'Content-Type': 'application/json' }, body: '{"error":{"code":"model_not_found","message":"synthetic-secret"}}', error: 'model_not_found' },
]) {
  test(`upstream 403 distinguishes ${sample.label} without exposing the body`, async t => {
    t.mock.method(globalThis, 'fetch', async () => new Response(sample.body, { status: 403, headers: sample.headers }))
    const response = await worker.fetch(request())
    const body = await response.json()
    assert.equal(response.status, 403)
    assert.equal(body.error, sample.error)
    assert.equal(JSON.stringify(body).includes('synthetic-secret'), false)
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), origin)
  })
}

test('OAuth polling still preserves authorization_pending', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('{"error":"authorization_pending"}', { status: 403 }))
  const response = await worker.fetch(request('https://auth.openai.com/api/accounts/deviceauth/token'))
  assert.equal((await response.json()).error, 'authorization_pending')
})

test('structured provider codes take precedence over numbers in their messages', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('{"error":{"code":"model_not_found","message":"Requested model error:1234 is unavailable"}}', { status: 403, headers: { 'Content-Type': 'application/json' } }))
  const response = await worker.fetch(request())
  assert.equal((await response.json()).error, 'model_not_found')
})

test('an explicit challenge takes precedence over a numeric edge code', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>error code: 1020</html>', { status: 403, headers: { 'Content-Type': 'text/html', 'cf-mitigated': 'challenge' } }))
  const response = await worker.fetch(request())
  assert.equal((await response.json()).error, 'provider_challenge')
})

test('unknown provider errors retain a generic error without echoing secrets', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('{"error":{"message":"synthetic-secret"}}', { status: 403, headers: { 'Content-Type': 'application/json' } }))
  const response = await worker.fetch(request())
  const body = await response.json()
  assert.equal(body.error, 'provider_request_failed')
  assert.equal(body.upstream_format, 'json')
  assert.equal(JSON.stringify(body).includes('synthetic-secret'), false)
})

test('unapproved origins and target hosts remain rejected before outbound fetch', async t => {
  const upstream = t.mock.method(globalThis, 'fetch', async () => new Response('unused'))
  assert.equal((await worker.fetch(request(undefined, 'https://untrusted.example'))).status, 403)
  assert.equal((await worker.fetch(request('https://untrusted.example/'))).status, 400)
  assert.equal(upstream.mock.callCount(), 0)
})

test('only exact provider paths without credentials, redirects, or extra queries are permitted', async t => {
  const upstream = t.mock.method(globalThis, 'fetch', async () => new Response('unused'))
  for (const target of [
    'https://chatgpt.com/backend-api/codex/responses/other',
    'https://chatgpt.com/backend-api/codex/responses?url=http://127.0.0.1',
    'https://user:password@chatgpt.com/backend-api/codex/responses',
    'https://auth.openai.com/api/accounts/deviceauth/arbitrary',
  ]) assert.equal((await worker.fetch(request(target))).status, 400)
  assert.equal(upstream.mock.callCount(), 0)
})

test('the exact Codex models GET is forwarded with no request body', async t => {
  const upstream = t.mock.method(globalThis, 'fetch', async (_url, init) => {
    assert.equal(init.method, 'GET')
    assert.equal(init.body, undefined)
    return new Response('{"models":[{"slug":"synthetic-model"}]}', { headers: { 'Content-Type': 'application/json' } })
  })
  const incoming = new Request('https://relay.example/relay', {
    method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: 'https://chatgpt.com/backend-api/codex/models?client_version=1.0.0', method: 'GET', headers: { Authorization: 'Bearer synthetic-token' }, body: null }),
  })
  const response = await worker.fetch(incoming)
  assert.equal(response.status, 200)
  assert.equal((await response.json()).models[0].slug, 'synthetic-model')
  assert.equal(upstream.mock.callCount(), 1)
})

test('Codex SSE without Content-Type retains an event-stream response type', async t => {
  const body = 'data: {"type":"response.completed"}\n\n'
  t.mock.method(globalThis, 'fetch', async () => new Response(new TextEncoder().encode(body)))
  const response = await worker.fetch(request())
  assert.match(response.headers.get('Content-Type'), /^text\/event-stream/)
  assert.equal(await response.text(), body)
})

test('redirects and oversized upstream responses do not reach the browser', async t => {
  const upstream = t.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 302, headers: { Location: 'https://untrusted.example' } }))
  const redirect = await worker.fetch(request())
  assert.equal(redirect.status, 502)
  assert.equal((await redirect.json()).error, 'provider_redirect_rejected')
  upstream.mock.mockImplementation(async () => new Response(new Uint8Array(4 * 1024 * 1024 + 1)))
  const large = await worker.fetch(request())
  assert.equal(large.status, 502)
  assert.equal((await large.json()).error, 'provider_connection_failed')
})

test('a completed Codex stream returns even when the upstream connection stays open', async t => {
  let controller, cancelled = false
  const terminal = 'data: {"type":"response.completed"}\n\n'
  const stream = new ReadableStream({
    start(value) {
      controller = value
      value.enqueue(new TextEncoder().encode(terminal.slice(0, 17)))
      value.enqueue(new TextEncoder().encode(terminal.slice(17)))
    },
    cancel() { cancelled = true },
  })
  t.mock.method(globalThis, 'fetch', async () => new Response(stream))
  const pending = worker.fetch(request())
  let timer
  try {
    const response = await Promise.race([
      pending,
      new Promise((_, reject) => { timer = setTimeout(() => reject(Error('Completed stream stayed pending')), 250) }),
    ])
    assert.equal(await response.text(), terminal)
    assert.equal(cancelled, true)
  } finally {
    clearTimeout(timer)
    if (!cancelled) controller.close()
    await pending
  }
})
