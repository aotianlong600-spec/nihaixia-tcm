import test from 'node:test'
import assert from 'node:assert/strict'
import {ApiClient, ApiError} from '../src/api.ts'

test('browser requests use the scoped module worker and reject safely if it fails', async t => {
  const names = ['window', 'document', 'Worker'] as const
  const descriptors = names.map(name => Object.getOwnPropertyDescriptor(globalThis, name))
  const originalFetch = globalThis.fetch
  const calls: {id:string; method:string; path:string; body:string}[] = []
  const workers: MockWorker[] = []
  let fetches = 0
  class MockWorker {
    onmessage?: (event: {data:any}) => void
    onerror?: () => void
    terminated = false
    constructor(url: URL, options: WorkerOptions) {
      assert.equal(url.href, 'https://example.test/nihaixia-tcm/browser-worker.js')
      assert.deepEqual(options, {type:'module'})
      workers.push(this)
    }
    postMessage(request: typeof calls[number]) { calls.push(request) }
    terminate() { this.terminated = true }
  }
  Object.defineProperty(globalThis, 'window', {configurable:true, value:new EventTarget()})
  Object.defineProperty(globalThis, 'document', {configurable:true, value:{baseURI:'https://example.test/nihaixia-tcm/'}})
  Object.defineProperty(globalThis, 'Worker', {configurable:true, value:MockWorker})
  globalThis.fetch = async () => { fetches++; throw Error('Unexpected network fallback') }
  t.mock.timers.enable({apis:['setTimeout']})
  const client = new ApiClient('', true)
  try {
    const waiting = client.session()
    assert.deepEqual(calls.map(({method,path,body}) => ({method,path,body})), [{method:'GET',path:'/session',body:''}])
    t.mock.timers.tick(90000)
    const session = {authenticated:true,standalone:true,platform:'browser',csrf_token:'local'}
    workers[0].onmessage!({data:{id:calls[0].id,status:200,body:session}})
    assert.deepEqual(await waiting, session)
    assert.deepEqual(client.runtime, {platform:'browser',standalone:true})

    const payload = {intake:{chief_complaint:'合成浏览器记录'}}
    const writing = client.post('/consultations', payload)
    assert.equal(calls[1].method, 'POST')
    assert.equal(calls[1].path, '/consultations')
    assert.deepEqual(JSON.parse(calls[1].body), payload)
    workers[0].onmessage!({data:{id:calls[1].id,status:200,body:{id:'saved-local-record'}}})
    assert.deepEqual(await writing, {id:'saved-local-record'})

    const failed = assert.rejects(client.request('/personal/overview'), error => error instanceof ApiError && /重新加载/.test(error.message))
    const alsoFailed = assert.rejects(client.request('/consultations'), error => error instanceof ApiError && /重新加载/.test(error.message))
    workers[0].onerror!()
    await Promise.all([failed, alsoFailed])
    await assert.rejects(client.request('/formulas'), error => error instanceof ApiError && /重新加载/.test(error.message))
    assert.equal(workers[0].terminated, true)
    assert.equal(workers.length, 1)
    assert.equal(fetches, 0)
  } finally {
    client.dispose()
    globalThis.fetch = originalFetch
    names.forEach((name, index) => {
      const descriptor = descriptors[index]
      if (descriptor) Object.defineProperty(globalThis, name, descriptor)
      else delete (globalThis as any)[name]
    })
  }
})
