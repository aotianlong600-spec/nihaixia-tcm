import test from 'node:test'
import assert from 'node:assert/strict'
import { ApiClient } from '../src/api.ts'

test('session rotation replaces CSRF and 401 notifies the page without retrying writes', async () => {
  const original=globalThis.fetch, events:string[]=[], sent:Headers[]=[]
  const client=new ApiClient()
  client.onUnauthorized=()=>events.push('locked')
  let session=0
  globalThis.fetch=async (url, options) => {
    if(String(url).endsWith('/session')) return Response.json({csrf_token:`token-${++session}`})
    sent.push(new Headers(options?.headers))
    return Response.json({detail:'请登录'}, {status:401})
  }
  try {
    await client.session();await client.session()
    await assert.rejects(client.post('/consultations',{}),/请登录/)
    assert.equal(sent.length,1);assert.equal(sent[0].get('X-CSRF-Token'),'token-2')
    assert.deepEqual(events,['locked'])
    await assert.rejects(client.post('/access/login',{password:'synthetic'}))
    assert.deepEqual(events,['locked'])
  } finally {globalThis.fetch=original}
})
