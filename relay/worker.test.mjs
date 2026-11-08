import test from 'node:test'
import assert from 'node:assert/strict'
import worker from './worker.mjs'

const origin = 'https://aotianlong600-spec.github.io'
const payload = {
  method: 'POST', url: 'https://api.deepseek.com/v1/chat/completions',
  headers: { Authorization: 'Bearer synthetic-test-key', 'Content-Type': 'application/json' }, body: '{}',
}
const request = (value = payload, source = origin) => new Request('https://relay.example/relay', {
  method: 'POST', headers: { Origin: source, 'Content-Type': 'application/json' }, body: JSON.stringify(value),
})

test('relay rejects other origins, private targets and credential headers before networking', async () => {
  const previous = globalThis.fetch
  let calls = 0
  globalThis.fetch = async () => { calls++; throw Error('Network should not be reached') }
  try {
    assert.equal((await worker.fetch(request(payload, 'https://other.example'))).status, 403)
    for (const url of ['https://127.0.0.1/v1/chat/completions', 'https://api.deepseek.com/other', 'https://user:pass@api.deepseek.com/v1/chat/completions']) {
      assert.equal((await worker.fetch(request({ ...payload, url }))).status, 400)
    }
    assert.equal((await worker.fetch(request({ ...payload, headers: { ...payload.headers, Cookie: 'unexpected' } }))).status, 400)
    assert.equal(calls, 0)
  } finally { globalThis.fetch = previous }
})

test('relay preserves completed SSE and refuses credential redirects', async () => {
  const previous = globalThis.fetch
  let captured
  globalThis.fetch = async (url, options) => {
    captured = { url, options }
    return new Response('data: [DONE]\n\n', { headers: { 'Content-Type': 'text/event-stream' } })
  }
  try {
    const response = await worker.fetch(request())
    assert.equal(response.status, 200)
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), origin)
    assert.equal(await response.text(), 'data: [DONE]\n\n')
    assert.equal(captured.options.redirect, 'manual')
    globalThis.fetch = async () => new Response(null, { status: 302, headers: { Location: 'https://other.example' } })
    assert.equal((await worker.fetch(request())).status, 502)
  } finally { globalThis.fetch = previous }
})

test('relay preserves pending device status and does not reflect provider error bodies', async () => {
  const previous = globalThis.fetch
  globalThis.fetch = async () => Response.json({ error: 'authorization_pending', secret: 'synthetic-hidden' }, { status: 400 })
  try {
    const response = await worker.fetch(request({ ...payload, url: 'https://auth.openai.com/api/accounts/deviceauth/token' }))
    assert.equal(response.status, 400)
    assert.deepEqual(await response.json(), { error: 'authorization_pending' })
  } finally { globalThis.fetch = previous }
})

test('relay accepts supported consultation sizes and stops an aborted request', async () => {
  const previous = globalThis.fetch
  globalThis.fetch = async () => new Response('data: [DONE]\n\n', { headers: { 'Content-Type': 'text/event-stream' } })
  try {
    assert.equal((await worker.fetch(request({ ...payload, body: JSON.stringify({ text: 'x'.repeat(750000) }) }))).status, 200)
    let started
    const ready = new Promise(resolve => { started = resolve })
    globalThis.fetch = async (url, options) => new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(Error('Synthetic cancellation')), { once: true })
      started()
    })
    const controller = new AbortController()
    const waiting = worker.fetch(new Request(request(), { signal: controller.signal }))
    await ready
    controller.abort()
    assert.equal((await waiting).status, 502)
  } finally { globalThis.fetch = previous }
})
