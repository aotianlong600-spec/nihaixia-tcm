import assert from 'node:assert/strict'
import test from 'node:test'
import { createServer } from 'node:http'
import { ApiClient } from '../src/api.ts'
import { loadClinicalReferences, retainRuleSelection } from '../src/clinicalReferences.ts'
test('clinic reference refresh rereads newly published rules and evidence from the API',async()=>{
 let published=false
 const server=createServer((req,res)=>{
  res.setHeader('Content-Type','application/json')
  if(req.url==='/api/session')return res.end('{"csrf_token":"token","mode":"simulation","version":"0.1.0"}')
  if(req.url==='/api/rules')return res.end(JSON.stringify({items:published?[{id:'rule-new',status:'published',version:2}]:[]}))
  if(req.url==='/api/evidence')return res.end(JSON.stringify({items:published?[{id:'evidence-new',quote:'已校核引文'}]:[]}))
  res.writeHead(404);res.end('{"detail":"unexpected patient/visit reload"}')
 })
 await new Promise<void>(r=>server.listen(0,'127.0.0.1',r))
 try{
  const {port}=server.address() as {port:number};const client=new ApiClient(`http://127.0.0.1:${port}`)
  assert.deepEqual(await loadClinicalReferences(client),{rules:[],evidence:[]})
  published=true
  const next=await loadClinicalReferences(client)
  assert.equal(next.rules[0]?.id,'rule-new')
  assert.equal(next.evidence[0]?.quote,'已校核引文')
 }finally{server.close()}
})

test('withdrawn base and incompatible modifications cannot remain as hidden selections',()=>{
 const rules=[{id:'base',kind:'pattern',status:'published',formula_id:'f@2'},
              {id:'mod',kind:'modification',status:'published',base_formula_id:'f@2'},
              {id:'old-mod',kind:'modification',status:'withdrawn',base_formula_id:'f@2'},
              {id:'wrong-base-mod',kind:'modification',status:'published',base_formula_id:'other@1'}]
 assert.deepEqual(retainRuleSelection(rules,'base',['mod','old-mod','wrong-base-mod']),{baseRule:'base',modifications:['mod']})
 assert.deepEqual(retainRuleSelection(rules,'withdrawn-base',['mod']),{baseRule:'',modifications:[]})
})

