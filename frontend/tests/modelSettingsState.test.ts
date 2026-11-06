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
  if(req.url==='/api/model/codex/models')return res.end('{"items":[{"id":"synthetic-codex","name":"合成目录模型","reasoning_efforts":["low","medium","high","xhigh","max"]}],"scope":"合成SDK目录"}')
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
  assert.deepEqual(state.models,[{id:'synthetic-codex',name:'合成目录模型',reasoning_efforts:['low','medium','high','xhigh','max']}])
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
  assert.deepEqual(requests.find(r=>r.body)?.body,{auth_mode:'codex',base_url:'',model:'custom-codex',enabled:true,allow_external:false,allow_evidence:false,reasoning_effort:'auto'})
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
  assert.deepEqual(reopened.models,[{id:'synthetic-codex',name:'合成目录模型',reasoning_efforts:['low','medium','high','xhigh','max']}])
  assert.equal(reopened.config.model,'saved-custom-id')
 })
})

type ProfileFixtureControl={setActive:(id:string|null)=>void;setFailSelect:(value:boolean)=>void}
async function withProfiles(check:(state:ModelSettingsState,requests:{method:string;path:string;body:any}[],control:ProfileFixtureControl)=>Promise<void>,initialActive:string|null='p1',options:{omitRevision?:boolean}={}){
 const requests:{method:string;path:string;body:any}[]=[]
 let active:string|null=initialActive, failSelect=false
 const base={auth_mode:'api_key',base_url:'https://example.test',model:'m1',enabled:true,allow_external:true,allow_evidence:true}
 let profiles:any[]=[{id:'p1',name:'配置一',...base,has_key:true,revision:1},{id:'p2',name:'配置二',...base,model:'m2',reasoning_effort:'low',has_key:true,revision:2}]
 const publicConfig=(id:string|null)=>{
  const result:any=id?(()=>{const {revision,...fields}=profiles.find(p=>p.id===id);return {...fields,profile_id:id,profile_name:fields.name,codex:{logged_in:false},profile_revision:revision}})():{...base,profile_id:null,profile_name:null,has_key:true,codex:{logged_in:false},profile_revision:null}
  if(options.omitRevision)delete result.profile_revision
  return result
 }
 const server=createServer(async(req,res)=>{
  const chunks:Buffer[]=[];for await(const chunk of req)chunks.push(Buffer.from(chunk))
  const raw=Buffer.concat(chunks).toString(),body=raw?JSON.parse(raw):undefined,path=req.url!
  requests.push({method:req.method!,path,body});res.setHeader('Content-Type','application/json')
  if(path==='/api/session')return res.end('{"csrf_token":"synthetic"}')
  if(path==='/api/model/config')return res.end(JSON.stringify(publicConfig(active)))
  if(path==='/api/model/profiles'&&req.method==='GET')return res.end(JSON.stringify({items:profiles,active_id:active}))
  if(path==='/api/model/profiles'&&req.method==='POST'){
   const {api_key,...rest}=body;const saved={id:'p3',...rest,has_key:!!api_key,revision:1};profiles=[...profiles,saved];return res.end(JSON.stringify(saved))
  }
  const one=path.match(/^\/api\/model\/profiles\/([^/]+)$/)
  if(one&&req.method==='PUT'){
   const {api_key,...rest}=body
   profiles=profiles.map(p=>p.id===one[1]?{...p,...rest,has_key:p.has_key||!!api_key,revision:(p.revision||0)+1}:p)
   return res.end(JSON.stringify(profiles.find(p=>p.id===one[1])))
  }
  if(one&&req.method==='DELETE'){
   profiles=profiles.filter(p=>p.id!==one[1]);if(active===one[1])active=null
   return res.end(JSON.stringify({deleted_id:one[1],active_id:active}))
  }
  const select=path.match(/^\/api\/model\/profiles\/([^/]+)\/select$/)
  if(select&&req.method==='POST'){
   if(failSelect){res.writeHead(500);return res.end('{"detail":"select failed"}')}
   active=select[1];return res.end(JSON.stringify(publicConfig(active)))
  }
  if(path==='/api/model/codex')return res.end('{"logged_in":false,"login":{"id":"login-1","status":"pending","method":"browser","stage":"waiting_authorization","auth_url":"http://localhost:1455/auth/callback"}}')
  if(path==='/api/model/codex/models')return res.end('{"items":[{"id":"synthetic-codex","name":"合成目录模型","reasoning_efforts":["low","medium","high","xhigh","max"]}],"scope":"合成SDK目录"}')
  if(/^\/api\/model\/codex\/login\/[^/]+\/code$/.test(path))return res.end('{"status":"submitted"}')
  res.writeHead(404);res.end('{"detail":"unexpected test endpoint"}')
 })
 await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
 try{const {port}=server.address() as {port:number};const control:ProfileFixtureControl={setActive:id=>{active=id},setFailSelect:value=>{failSelect=value}};await check(new ModelSettingsState(new ApiClient(`http://127.0.0.1:${port}`)),requests,control)}finally{server.close()}
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

test('activating the profile being edited preserves its unsaved credential recipient',async()=>{
 await withProfiles(async(state)=>{
  await state.load();await state.loadProfiles();state.selectForEdit(state.profiles[1])
  state.config.base_url='https://draft-recipient.test/v1';state.config.model='draft-model'
  await state.useProfile('p2')
  assert.equal(state.saved?.profile_id,'p2')
  assert.equal(state.saved?.base_url,'https://example.test')
  assert.equal(state.config.base_url,'https://draft-recipient.test/v1')
  assert.equal(state.config.model,'draft-model')
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

test('reasoning effort round-trips through save while old configs default to auto',async()=>{
 await withSettings(async(state,requests)=>{
  await state.load()
  assert.equal(state.config.reasoning_effort,'auto')
  assert.equal(state.config.enabled,false)
  assert.equal(state.config.allow_external,false)
  state.config.model='provider/model';state.config.reasoning_effort='high'
  await state.save()
  assert.equal(requests.find(r=>r.body)?.body.reasoning_effort,'high')
  assert.equal(state.saved?.reasoning_effort,'high')
  assert.equal(state.config.reasoning_effort,'high')
 })
})

test('known Codex models expose only auto plus catalog efforts and preserve valid effort across refresh',async()=>{
 await withSettings(async(state)=>{
  await state.load();await state.selectAuthMode('codex')
  state.config.model='synthetic-codex'
  assert.deepEqual(state.effortChoices,['auto','low','medium','high','xhigh','max'])
  state.config.reasoning_effort='high'
  await state.loadModels()
  assert.equal(state.config.reasoning_effort,'high')
  assert.equal(state.effortValid,true)
 })
})

test('custom or unknown Codex models limit effort to auto and block invalid saves',async()=>{
 await withSettings(async(state,requests)=>{
  await state.load();await state.selectAuthMode('codex')
  state.config.model='custom-codex';state.modelChanged()
  assert.deepEqual(state.effortChoices,['auto'])
  assert.equal(state.effortCapabilityKnown,false)
  state.config.reasoning_effort='low'
  assert.equal(state.effortValid,false)
  const before=requests.filter(r=>r.body).length
  await assert.rejects(state.save(),/不受当前模型支持/)
  assert.equal(requests.filter(r=>r.body).length,before)
 })
})

test('changing model or auth mode resets only unsupported effort to auto',async()=>{
 await withSettings(async(state)=>{
  await state.load();await state.selectAuthMode('codex')
  state.config.model='synthetic-codex';state.config.reasoning_effort='high'
  state.modelChanged()
  assert.equal(state.config.reasoning_effort,'high')
  state.config.model='custom-codex';state.modelChanged()
  assert.equal(state.config.reasoning_effort,'auto')
  await state.selectAuthMode('api_key')
  assert.deepEqual(state.effortChoices,['auto','none','minimal','low','medium','high','xhigh','max'])
  state.config.reasoning_effort='max';state.modelChanged()
  assert.equal(state.config.reasoning_effort,'max')
  await state.selectAuthMode('codex')
  assert.equal(state.config.reasoning_effort,'auto')
 })
})

test('a whitelisted but unsupported effort is invalid and never silently sent',async()=>{
 await withSettings(async(state,requests)=>{
  await state.load();state.config.model='provider/model';state.config.reasoning_effort='turbo'
  assert.equal(state.effortValid,false)
  const before=requests.filter(r=>r.body).length
  await assert.rejects(state.save(),/有效的思考档位/)
  assert.equal(requests.filter(r=>r.body).length,before)
 })
})

test('profile edit and save persist reasoning effort without changing the active snapshot',async()=>{
 await withProfiles(async(state,requests)=>{
  await state.load();await state.loadProfiles()
  assert.equal(state.saved?.reasoning_effort,'auto')
  state.selectForEdit(state.profiles[0])
  assert.equal(state.config.reasoning_effort,'auto')
  state.selectForEdit(state.profiles[1])
  assert.equal(state.config.reasoning_effort,'low')
  state.config.reasoning_effort='high'
  assert.equal(state.saved?.reasoning_effort,'auto')
  await state.saveProfile()
  const update=requests.find(r=>r.method==='PUT'&&r.path==='/api/model/profiles/p2')
  assert.equal(update?.body.reasoning_effort,'high')
  assert.equal(state.config.reasoning_effort,'high')
  assert.equal(state.saved?.reasoning_effort,'auto')
  await state.useProfile('p2')
  assert.equal(state.saved?.reasoning_effort,'high')
  assert.equal(state.config.reasoning_effort,'high')
  state.newDraft()
  assert.equal(state.config.reasoning_effort,'auto')
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

test('consultation load picks the active profile and requires no write for an unchanged draft',async()=>{
 await withProfiles(async(state,requests)=>{
  await state.loadConsultation()
  assert.equal(state.editingId,'p1')
  assert.equal(state.activeId,'p1')
  assert.equal(state.saved?.profile_id,'p1')
  assert.equal(state.consultationDirty,false)
  assert.deepEqual(state.consultationSelection,{profile_id:'p1',profile_revision:1})
  const before=requests.length
  state.config.model='m1-draft'
  assert.equal(state.consultationDirty,true)
  assert.equal(state.consultationSelection,null)
  assert.equal(requests.length,before)
 })
})

test('a profile-only consultation switch selects without rewriting the stored profile',async()=>{
 await withProfiles(async(state,requests)=>{
  await state.loadConsultation()
  state.selectForEdit(state.profiles.find(p=>p.id==='p2')!)
  assert.equal(state.consultationDirty,false)
  assert.equal(state.consultationSelection,null)
  const before=requests.length
  const selection=await state.applyConsultation()
  const tail=requests.slice(before)
  assert.deepEqual(tail.map(r=>`${r.method} ${r.path}`),['POST /api/model/profiles/p2/select','GET /api/model/config','GET /api/model/profiles'])
  assert.equal(tail.some(r=>r.method==='PUT'),false)
  assert.deepEqual(selection,{profile_id:'p2',profile_revision:2})
  assert.equal(state.saved?.model,'m2')
  assert.equal(state.saved?.profile_revision,2)
 })
})

test('applying a changed non-active profile PUTs it, selects it, then reloads the real current snapshot',async()=>{
 await withProfiles(async(state,requests)=>{
  await state.loadConsultation()
  state.selectForEdit(state.profiles.find(p=>p.id==='p2')!)
  state.config.model='m2-edited'
  assert.equal(state.consultationDirty,true)
  const before=requests.length
  const selection=await state.applyConsultation()
  const tail=requests.slice(before)
  assert.deepEqual(tail.map(r=>`${r.method} ${r.path}`),['PUT /api/model/profiles/p2','POST /api/model/profiles/p2/select','GET /api/model/config','GET /api/model/profiles'])
  assert.equal(tail[0].body.model,'m2-edited')
  assert.equal('api_key' in tail[0].body,false)
  assert.equal('has_key' in tail[0].body,false)
  assert.deepEqual(selection,{profile_id:'p2',profile_revision:3})
  assert.equal(state.saved?.model,'m2-edited')
  assert.equal(state.saved?.profile_revision,3)
  assert.equal(state.consultationDirty,false)
 })
})

test('consultation application never sends credentials or changes consent flags',async()=>{
 await withProfiles(async(state,requests)=>{
  await state.loadConsultation()
  state.config.reasoning_effort='high'
  const before=requests.length
  await state.applyConsultation()
  const tail=requests.slice(before)
  const update=tail.find(r=>r.method==='PUT')!
  assert.equal(update.body.reasoning_effort,'high')
  assert.equal(update.body.expected_profile_revision,1)
  assert.equal('api_key' in update.body,false)
  assert.equal('has_key' in update.body,false)
  assert.equal(update.body.allow_external,true)
  assert.equal(update.body.allow_evidence,true)
  assert.equal(update.body.base_url,'https://example.test')
  assert.equal('api_key' in state.config,false)
  assert.equal('api_key' in state.saved!,false)
  assert.equal(state.saved?.has_key,true)
 })
})

test('failure during consultation selection never yields a ready selection and supports retry',async()=>{
 await withProfiles(async(state,_requests,control)=>{
  await state.loadConsultation()
  state.selectForEdit(state.profiles.find(p=>p.id==='p2')!)
  state.config.model='m2-edited'
  control.setFailSelect(true)
  await assert.rejects(state.applyConsultation(),/select failed/)
  assert.equal(state.consultationSelection,null)
  assert.equal(state.activeId,'p1')
  assert.equal(state.consultationDirty,false)
  control.setFailSelect(false)
  const selection=await state.applyConsultation()
  assert.deepEqual(selection,{profile_id:'p2',profile_revision:3})
 })
})

test('a saved configuration without a numeric revision fails closed',async()=>{
 await withProfiles(async(state)=>{
  await state.loadConsultation()
  assert.equal(state.saved?.profile_revision,undefined)
  assert.equal(state.consultationSelection,null)
  state.selectForEdit(state.profiles.find(p=>p.id==='p2')!)
  await state.applyConsultation()
  assert.equal(state.consultationSelection,null)
 },'p1',{omitRevision:true})
})

test('consultation reload observes an active profile changed from model settings',async()=>{
 await withProfiles(async(state,requests,control)=>{
  await state.loadConsultation()
  assert.equal(state.editingId,'p1')
  control.setActive('p2')
  await state.loadConsultation()
  assert.equal(state.activeId,'p2')
  assert.equal(state.editingId,'p2')
  assert.equal(state.config.model,'m2')
  assert.deepEqual(state.consultationSelection,{profile_id:'p2',profile_revision:2})
 })
})

test('an old profile with omitted effort is clean while a draft effort change is pending',async()=>{
 await withProfiles(async(state)=>{
  await state.loadConsultation()
  assert.equal(state.config.reasoning_effort,'auto')
  assert.equal(state.consultationDirty,false)
  state.config.reasoning_effort='high'
  assert.equal(state.consultationDirty,true)
  assert.equal(state.consultationSelection,null)
  state.config.reasoning_effort='auto'
  assert.equal(state.consultationDirty,false)
  assert.deepEqual(state.consultationSelection,{profile_id:'p1',profile_revision:1})
 })
})
