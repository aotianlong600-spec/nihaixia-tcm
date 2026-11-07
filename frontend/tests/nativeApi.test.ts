import test from 'node:test'
import assert from 'node:assert/strict'
import {ApiClient,ApiError} from '../src/api.ts'

type Call={id:string;method:string;path:string;body:string}
async function withNative(check:(client:ApiClient,calls:Call[],reply:(detail:any)=>void,surface:any)=>Promise<void>){
 const descriptor=Object.getOwnPropertyDescriptor(globalThis,'window'),originalFetch=globalThis.fetch
 const calls:Call[]=[],surface:any=new EventTarget()
 surface.NihaixiaLocal={request:(id:string,method:string,path:string,body:string)=>calls.push({id,method,path,body})}
 Object.defineProperty(globalThis,'window',{configurable:true,writable:true,value:surface})
 let fetches=0
 globalThis.fetch=async()=>{fetches++;throw Error('Native calls must never fall back to network')}
 const client=new ApiClient('https://unused-pc.example')
 try{await check(client,calls,detail=>surface.dispatchEvent(new CustomEvent('nihaixia-local-response',{detail})),surface);assert.equal(fetches,0)}
 finally{client.dispose();globalThis.fetch=originalFetch;if(descriptor)Object.defineProperty(globalThis,'window',descriptor);else delete (globalThis as any).window}
}

test('native session records runtime and native JSON calls need neither fetch nor CSRF',async()=>{
 await withNative(async(client,calls,reply)=>{
  const waiting=client.session()
  assert.deepEqual(calls.map(c=>[c.method,c.path,c.body]),[['GET','/session','']])
  const session={authenticated:true,csrf_token:'local',access_configured:false,platform:'android',standalone:true}
  reply({id:calls[0].id,status:200,body:session})
  assert.deepEqual(await waiting,session)
  assert.deepEqual(client.runtime,{platform:'android',standalone:true})
  client.token=''
  const result=client.post('/model/profiles',{name:'synthetic',api_key:'synthetic-device-key'})
  assert.equal(calls.length,2)
  assert.equal(calls[1].path,'/model/profiles')
  assert.equal(JSON.parse(calls[1].body).api_key,'synthetic-device-key')
  reply({id:calls[1].id,status:200,body:{id:'profile',has_key:true}})
  assert.deepEqual(await result,{id:'profile',has_key:true})
 })
})

test('native errors retain status and 401 notification without reflecting request bodies',async()=>{
 await withNative(async(client,calls,reply,surface)=>{
  let locked=0;client.onUnauthorized=()=>locked++
  const waiting=client.request('/consultations')
  reply({id:calls[0].id,status:401,body:{detail:'请重新解锁'}})
  await assert.rejects(waiting,error=>error instanceof ApiError&&error.status===401&&error.message==='请重新解锁')
  assert.equal(locked,1)
  const login=client.post('/access/login',{password:'synthetic-secret'})
  reply({id:calls[1].id,status:401,body:{detail:'synthetic login rejected'}})
  await assert.rejects(login,error=>error instanceof ApiError&&error.status===401)
  assert.equal(locked,1)
  surface.NihaixiaLocal.request=()=>{throw Error('synthetic-device-key should not be reflected')}
  await assert.rejects(client.post('/model/profiles',{api_key:'synthetic-device-key'}),error=>error instanceof ApiError&&!error.message.includes('synthetic-device-key'))
 })
})

test('native simultaneous responses correlate once and unmatched or late frames are ignored',async()=>{
 await withNative(async(client,calls,reply)=>{
  const first=client.request('/library/sources'),second=client.request('/consultations')
  assert.notEqual(calls[0].id,calls[1].id)
  reply({id:'stale-id',status:200,body:{unexpected:true}})
  reply({id:calls[1].id,status:200,body:{items:['second']}})
  assert.deepEqual(await second,{items:['second']})
  reply({id:calls[1].id,status:500,body:{detail:'late'}})
  reply({id:calls[0].id,status:200,body:{items:['first']}})
  assert.deepEqual(await first,{items:['first']})
 })
})

test('native transport cleans listeners on completion and pending calls on dispose',async()=>{
 await withNative(async(client,calls,reply,surface)=>{
  let attached=0
  const add=surface.addEventListener.bind(surface),remove=surface.removeEventListener.bind(surface)
  surface.addEventListener=(type:string,...rest:any[])=>{if(type==='nihaixia-local-response')attached++;return add(type,...rest)}
  surface.removeEventListener=(type:string,...rest:any[])=>{if(type==='nihaixia-local-response')attached--;return remove(type,...rest)}
  const first=client.request('/one');assert.equal(attached,1)
  reply({id:calls[0].id,status:200,body:{ok:true}});await first;assert.equal(attached,0)
  const pending=client.request('/two'),rejected=assert.rejects(pending,error=>error instanceof ApiError)
  client.dispose();await rejected;assert.equal(attached,0)
  reply({id:calls[1].id,status:200,body:{late:true}})
 })
})

test('native pending calls have a bounded timeout and are cancelled when the page closes',async(t)=>{
 t.mock.timers.enable({apis:['setTimeout']})
 await withNative(async(client,calls,reply,surface)=>{
  const pending=client.request('/waiting'),timeout=assert.rejects(pending,error=>error instanceof ApiError&&/超时/.test(error.message))
  t.mock.timers.tick(30000);await timeout
  reply({id:calls[0].id,status:200,body:{late:true}})
  const closing=client.request('/closing'),cancelled=assert.rejects(closing,error=>error instanceof ApiError)
  surface.dispatchEvent(new Event('pagehide'));await cancelled
 })
})

test('native missing bridge never silently switches to a PC or remote network',async()=>{
 await withNative(async(client,calls,reply,surface)=>{
  const first=client.request('/one');reply({id:calls[0].id,status:200,body:{ok:true}});await first
  delete surface.NihaixiaLocal
  await assert.rejects(client.request('/two'),error=>error instanceof ApiError&&/本地/.test(error.message))
 })
})

test('bundled Android origin without its bridge fails locally at startup',async()=>{
 await withNative(async(_client,_calls,_reply,surface)=>{
  surface.location={origin:'https://appassets.androidplatform.net'}
  delete surface.NihaixiaLocal
  const client=new ApiClient('https://unused-pc.example')
  assert.equal(client.runtime.standalone,true)
  await assert.rejects(client.session(),error=>error instanceof ApiError&&/本地/.test(error.message))
  client.dispose()
 })
})

test('native path and unsupported body validation happen before dispatch',async()=>{
 await withNative(async(client,calls)=>{
  for(const path of ['https://pc.example/model','//pc.example/model','/model\\secret','/model#fragment']){
   await assert.rejects(client.request(path),error=>error instanceof ApiError&&error.status===400)
  }
  await assert.rejects(client.request('/upload',{method:'POST',body:new Blob(['synthetic'])}),error=>error instanceof ApiError&&error.status===400)
  assert.equal(calls.length,0)
 })
})

test('native binary envelopes return a Blob and malformed response status fails safely',async()=>{
 await withNative(async(client,calls,reply)=>{
  const binary=client.request<Blob>('/synthetic-binary')
  reply({id:calls[0].id,status:200,body:null,content_type:'application/octet-stream',base64:'c3ludGhldGlj'})
  assert.equal(await (await binary).text(),'synthetic')
  const malformed=client.request('/malformed')
  reply({id:calls[1].id,status:'200',body:{api_key:'synthetic-device-key'}})
  await assert.rejects(malformed,error=>error instanceof ApiError&&!error.message.includes('synthetic-device-key'))
 })
})
