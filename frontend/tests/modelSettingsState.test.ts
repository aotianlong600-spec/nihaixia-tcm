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

async function withProfiles(check:(state:ModelSettingsState,requests:{method:string;path:string;body:any}[])=>Promise<void>,initialActive:string|null='p1'){
 const requests:{method:string;path:string;body:any}[]=[]
 let active:string|null=initialActive
 const base={auth_mode:'api_key',base_url:'https://example.test',model:'m1',enabled:true,allow_external:false,allow_evidence:false}
 let profiles:any[]=[{id:'p1',name:'配置一',...base,has_key:true},{id:'p2',name:'配置二',...base,model:'m2',has_key:false}]
 const publicConfig=(id:string|null)=>id?{...profiles.find(p=>p.id===id),profile_id:id,profile_name:profiles.find(p=>p.id===id)?.name,codex:{logged_in:false}}:{...base,profile_id:null,profile_name:null,has_key:true}
 const server=createServer(async(req,res)=>{
  const chunks:Buffer[]=[];for await(const chunk of req)chunks.push(Buffer.from(chunk))
  const raw=Buffer.concat(chunks).toString(),body=raw?JSON.parse(raw):undefined,path=req.url!
  requests.push({method:req.method!,path,body});res.setHeader('Content-Type','application/json')
  if(path==='/api/session')return res.end('{"csrf_token":"synthetic"}')
  if(path==='/api/model/config')return res.end(JSON.stringify(publicConfig(active)))
  if(path==='/api/model/profiles'&&req.method==='GET')return res.end(JSON.stringify({items:profiles,active_id:active}))
  if(path==='/api/model/profiles'&&req.method==='POST'){
   const {api_key,...rest}=body;const saved={id:'p3',...rest,has_key:!!api_key};profiles=[...profiles,saved];return res.end(JSON.stringify(saved))
  }
  const one=path.match(/^\/api\/model\/profiles\/([^/]+)$/)
  if(one&&req.method==='PUT'){
   const {api_key,...rest}=body
   profiles=profiles.map(p=>p.id===one[1]?{...p,...rest,has_key:p.has_key||!!api_key}:p)
   return res.end(JSON.stringify(profiles.find(p=>p.id===one[1])))
  }
  if(one&&req.method==='DELETE'){
   profiles=profiles.filter(p=>p.id!==one[1]);if(active===one[1])active=null
   return res.end(JSON.stringify({deleted_id:one[1],active_id:active}))
  }
  const select=path.match(/^\/api\/model\/profiles\/([^/]+)\/select$/)
  if(select&&req.method==='POST'){active=select[1];return res.end(JSON.stringify(publicConfig(active)))}
  if(path==='/api/model/codex')return res.end('{"logged_in":false,"login":{"id":"login-1","status":"pending","method":"browser","stage":"waiting_authorization","auth_url":"http://localhost:1455/auth/callback"}}')
  if(/^\/api\/model\/codex\/login\/[^/]+\/code$/.test(path))return res.end('{"status":"submitted"}')
  res.writeHead(404);res.end('{"detail":"unexpected test endpoint"}')
 })
 await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
 try{const {port}=server.address() as {port:number};await check(new ModelSettingsState(new ApiClient(`http://127.0.0.1:${port}`)),requests)}finally{server.close()}
}

test('profiles keep the edit selection separate from the active configuration',async()=>{
 await withProfiles(async(state)=>{
  await state.load();await state.loadProfiles()
  assert.equal(state.activeId,'p1');assert.equal(state.saved?.profile_id,'p1')
  state.selectForEdit(state.profiles[1])
  assert.equal(state.config.model,'m2');assert.equal(state.name,'配置二')
  assert.equal(state.saved?.model,'m1');assert.equal(state.activeId,'p1')
 })
})

test('a null profile_id from the config endpoint leaves no saved active configuration',async()=>{
 await withProfiles(async(state)=>{
  await state.load();await state.loadProfiles()
  assert.equal(state.activeId,null);assert.equal(state.saved,null);assert.equal(state.profiles.length,2)
 },null)
})

test('creating a draft profile does not activate it and never sends a blank key',async()=>{
 await withProfiles(async(state,requests)=>{
  await state.load();await state.loadProfiles();state.newDraft()
  state.name='新配置';state.config.model='m3'
  await state.saveProfile()
  const create=requests.find(r=>r.method==='POST'&&r.path==='/api/model/profiles')
  assert.equal(create?.body.name,'新配置');assert.equal('api_key' in create!.body,false)
  assert.equal(state.activeId,'p1');assert.equal(state.saved?.model,'m1');assert.equal(state.editingId,'p3')
 })
})

test('updating a profile sends a new key only when provided and keeps the old key otherwise',async()=>{
 await withProfiles(async(state,requests)=>{
  await state.load();await state.loadProfiles();state.selectForEdit(state.profiles[1])
  state.config.model='m2-updated'
  await state.saveProfile()
  const updates=()=>requests.filter(r=>r.method==='PUT'&&r.path==='/api/model/profiles/p2')
  assert.equal('api_key' in updates()[0].body,false)
  assert.equal(state.saved?.model,'m1')
  await state.saveProfile('synthetic-profile-key')
  assert.equal(updates()[1].body.api_key,'synthetic-profile-key')
  assert.equal('api_key' in state.config,false);assert.equal('api_key' in state.saved!,false)
 })
})

test('explicit selection activates the profile while preserving a different unsaved draft',async()=>{
 await withProfiles(async(state)=>{
  await state.load();await state.loadProfiles();state.selectForEdit(state.profiles[1]);state.config.model='draft-only'
  await state.useProfile('p1')
  assert.equal(state.activeId,'p1');assert.equal(state.saved?.profile_id,'p1');assert.equal(state.saved?.profile_name,'配置一')
  assert.equal(state.config.model,'draft-only')
 })
})

test('deleting the active profile leaves no active configuration and clears its edit draft',async()=>{
 await withProfiles(async(state)=>{
  await state.load();await state.loadProfiles();state.selectForEdit(state.profiles[0])
  const result=await state.deleteProfile('p1')
  assert.equal(result.active_id,null);assert.equal(state.activeId,null);assert.equal(state.saved,null)
  assert.equal(state.editingId,null);assert.equal(state.profiles.length,1)
 })
})

test('manual callback code is posted to the pending login and never stored in settings',async()=>{
 await withProfiles(async(state,requests)=>{
  await state.load();await state.refreshCodex()
  const value='http://localhost:1455/auth/callback?code=synthetic&state=synthetic'
  await state.submitLoginCode(value)
  const submit=requests.find(r=>r.path==='/api/model/codex/login/login-1/code')
  assert.equal(submit?.body.value,value)
  assert.equal(requests.filter(r=>r.path==='/api/model/codex').length,2)
  assert.equal(JSON.stringify(state.config).includes('synthetic'),false)
  assert.equal(JSON.stringify(state.saved).includes('synthetic'),false)
 })
})
