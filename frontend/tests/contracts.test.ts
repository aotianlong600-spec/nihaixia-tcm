import assert from 'node:assert/strict'
import test from 'node:test'
import { createServer } from 'node:http'
import { ApiClient, ApiError } from '../src/api.ts'
import { canDecide, blankVisit } from '../src/visitState.ts'

test('writes initialize a CSRF session and surface backend detail without swallowing errors', async () => {
  const requests: string[] = []
  const server = createServer((req, res) => {
    requests.push(req.url || '')
    res.setHeader('Content-Type', 'application/json')
    if (req.url === '/api/session') return res.end(JSON.stringify({csrf_token:'test-token',mode:'simulation',version:'0.1.0'}))
    if (req.headers['x-csrf-token'] !== 'test-token') { res.writeHead(403); return res.end('{"detail":"CSRF missing"}') }
    res.writeHead(409); res.end('{"detail":"访次已变更，请重新分析"}')
  })
  await new Promise<void>(r => server.listen(0, '127.0.0.1', r))
  try {
    const address = server.address() as {port:number}
    const client = new ApiClient(`http://127.0.0.1:${address.port}`)
    await assert.rejects(client.request('/visits/a', { method:'PUT', body:JSON.stringify({}) }), (e: unknown) => e instanceof ApiError && e.status === 409 && e.message === '访次已变更，请重新分析')
    assert.deepEqual(requests, ['/api/session','/api/visits/a'])
  } finally { server.close() }
})

test('an edited, different-visit, or stale analysis can never be adopted', () => {
  const analysis = { visit_id:'visit-a', visit_revision:2, stale:false }
  assert.equal(canDecide(analysis, {id:'visit-a',revision:2}, false), true)
  assert.equal(canDecide(analysis, {id:'visit-a',revision:2}, true), false)
  assert.equal(canDecide(analysis, {id:'visit-a',revision:3}, false), false)
  assert.equal(canDecide(analysis, {id:'visit-b',revision:2}, false), false)
  assert.equal(canDecide({...analysis,stale:true}, {id:'visit-a',revision:2}, false), false)
})

test('a follow-up starts with no inherited facts', () => {
  const first = blankVisit('patient-a', 'visit-a')
  assert.deepEqual(first.facts, [])
  assert.equal(first.previous_visit_id, 'visit-a')
  first.facts.push({key:'synthetic',state:'unknown',verified:false})
  assert.deepEqual(blankVisit('patient-a').facts, [])
})
