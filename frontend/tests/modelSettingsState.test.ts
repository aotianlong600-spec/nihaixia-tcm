import assert from 'node:assert/strict'
import test from 'node:test'
import {createServer} from 'node:http'
import {ApiClient} from '../src/api.ts'
import {ModelSettingsState} from '../src/modelSettingsState.ts'

async function withSettings(check:(state:ModelSettingsState,requests:{path:string;body:any}[])=>Promise<void>){
 const requests:{path:string;body:any}[]=[]
 let config:any={auth_mode:'api_key',base_url:'https://example.test',model:'',enabled:false,allow_external:false,allow_evidence:false,has_key:true,codex:{logged_in:false}}
 const server=createServer(async(req,res)=>{
  const chunks:Buffer[]=[];for await(const chunk of req)chunks.push(Buffer.from(chunk))
  const raw=Buffer.concat(chunks).toString(),body=raw?JSON.parse(raw):undefined
  requests.push({path:req.url!,body});res.setHeader('Content-Type','application/json')
  if(req.url==='/api/session')return res.end('{"csrf_token":"synthetic"}')
  if(req.url==='/api/model/codex')return res.end('{"logged_in":true,"login":{"status":"completed","stage":"completed"}}')
  if(req.url==='/api/model/codex/models')return res.end('{"items":[{"id":"synthetic-codex","name":"合成目录模型"}],"scope":"合成SDK目录"}')
  if(req.url==='/api/model/config'){
   if(req.method==='PUT'){
    const {api_key,...saved}=body
    config={...saved,base_url:saved.auth_mode==='codex'?'https://chatgpt.com/backend-api':saved.base_url,has_key:true,codex:{logged_in:true}}
   }
   return res.end(JSON.stringify(config))
  }
  res.writeHead(404);res.end('{"detail":"unexpected test endpoint"}')
 })
 await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
 try{const {port}=server.address() as {port:number};await check(new ModelSettingsState(new ApiClient(`http://127.0.0.1:${port}`)),requests)}finally{server.close()}
}

test('authorization refresh preserves the unsaved selection and the saved active configuration',async()=>{
 await withSettings(async(state)=>{
  await state.load()
  state.config.auth_mode='codex';state.config.model='custom-codex';state.config.enabled=true
  await state.refreshCodex()
  assert.equal(state.codex.logged_in,true)
  assert.equal(state.config.model,'custom-codex')
  assert.equal(state.config.auth_mode,'codex')
  assert.equal(state.config.enabled,true)
  assert.equal(state.saved?.auth_mode,'api_key')
  assert.equal(state.saved?.model,'')
  assert.equal(state.saved?.enabled,false)
 })
})

test('selecting Codex loads its catalog without replacing a manual model ID or saving the draft',async()=>{
 await withSettings(async(state,requests)=>{
  await state.load();state.config.model='custom-id'
  await state.selectAuthMode('codex')
  assert.deepEqual(state.models,[{id:'synthetic-codex',name:'合成目录模型'}])
  assert.equal(state.catalogNote,'合成SDK目录')
  assert.equal(state.config.model,'custom-id')
  assert.equal(state.config.auth_mode,'codex')
  assert.equal(state.saved?.auth_mode,'api_key')
  assert.equal(requests.filter(r=>r.path==='/api/model/config'&&r.body).length,0)
 })
})

test('saving a custom Codex ID updates the active snapshot and never sends the API key',async()=>{
 await withSettings(async(state,requests)=>{
  await state.load();state.config.auth_mode='codex';state.config.model='custom-codex';state.config.enabled=true
  await state.save('synthetic-api-key')
  assert.deepEqual(requests.find(r=>r.body)?.body,{auth_mode:'codex',base_url:'',model:'custom-codex',enabled:true,allow_external:false,allow_evidence:false})
  assert.equal(state.saved?.model,'custom-codex')
  assert.equal(state.saved?.enabled,true)
  state.config.model='next-draft'
  assert.equal(state.saved?.model,'custom-codex')
 })
})

test('API Key mode keeps an arbitrary model ID and sends a new key only in the save request',async()=>{
 await withSettings(async(state,requests)=>{
  await state.load();state.config.model='provider/manual-model'
  await state.save('synthetic-api-key')
  assert.equal(requests.find(r=>r.body)?.body.model,'provider/manual-model')
  assert.equal(requests.find(r=>r.body)?.body.api_key,'synthetic-api-key')
  assert.equal('api_key' in state.config,false)
  assert.equal('api_key' in state.saved!,false)
 })
})

test('opening a saved Codex configuration loads the SDK catalog automatically',async()=>{
 await withSettings(async(state)=>{
  await state.load();state.config.auth_mode='codex';state.config.model='saved-custom-id';await state.save()
  const reopened=new ModelSettingsState(state.client)
  await reopened.load()
  assert.equal(reopened.saved?.model,'saved-custom-id')
  assert.deepEqual(reopened.models,[{id:'synthetic-codex',name:'合成目录模型'}])
  assert.equal(reopened.config.model,'saved-custom-id')
 })
})
