import assert from 'node:assert/strict'
import test from 'node:test'
import { createServer } from 'node:http'
import { ApiClient } from '../src/api.ts'
import { KnowledgeWorkspace } from '../src/knowledgeState.ts'

async function withApi(check:(workspace:KnowledgeWorkspace,requests:{method:string;path:string;body:any}[])=>Promise<void>){
 const requests:{method:string;path:string;body:any}[]=[]
 const server=createServer(async(req,res)=>{
  const chunks:Buffer[]=[];for await(const chunk of req)chunks.push(Buffer.from(chunk))
  const raw=Buffer.concat(chunks).toString();const body=raw?JSON.parse(raw):undefined
  const url=new URL(req.url!,'http://localhost');requests.push({method:req.method!,path:req.url!,body})
  res.setHeader('Content-Type','application/json')
  if(url.pathname==='/api/session')return res.end(JSON.stringify({csrf_token:'test-token',mode:'simulation',version:'0.1.0'}))
  if(url.pathname==='/api/search'){
   if(url.searchParams.has('document_id')&&!url.searchParams.get('document_id')){res.writeHead(400);return res.end('{"detail":"invalid document id"}')}
   return res.end(JSON.stringify({items:[{document_id:'doc-a',physical_page:2,snippet:'全库原文'}]}))
  }
  if(req.method==='GET'&&url.pathname.includes('/pages/'))return res.end(JSON.stringify({document_id:'doc-a',physical_page:2,raw_text:'原文A',corrected_text:'订正文A',review_status:'reviewed',kind:'经典原文',printed_page:null,warning:''}))
  if(req.headers['x-csrf-token']!=='test-token'){res.writeHead(403);return res.end('{"detail":"CSRF missing"}')}
  res.end('{"id":"saved"}')
 })
 await new Promise<void>(r=>server.listen(0,'127.0.0.1',r))
 try{const {port}=server.address() as {port:number};await check(new KnowledgeWorkspace(new ApiClient(`http://127.0.0.1:${port}`)),requests)}finally{server.close()}
}

test('all-document search succeeds without an empty document_id filter',async()=>{
 await withApi(async(workspace,requests)=>{
  const result=await workspace.search('原文')
  assert.equal(result.items[0].snippet,'全库原文')
  assert.equal(new URL(requests.at(-1)!.path,'http://localhost').searchParams.has('document_id'),false)
  workspace.targetDocumentId='doc-b';await workspace.search('原文')
  assert.equal(new URL(requests.at(-1)!.path,'http://localhost').searchParams.get('document_id'),'doc-b')
 })
})

test('changing the unopened target cannot redirect review, evidence or PDF away from the loaded page',async()=>{
 await withApi(async(workspace,requests)=>{
  await workspace.load('doc-a',2)
  workspace.targetDocumentId='doc-b';workspace.targetPhysicalPage=8
  assert.equal(workspace.pdfUrl,'/api/documents/doc-a/pdf#page=2')
  await workspace.review({corrected_text:'人工订正A',kind:'经典原文',reviewer:'校核人',note:'与原件核对'})
  const write=requests.find(r=>r.method==='POST'&&r.path.endsWith('/review'))!
  assert.equal(write.path,'/api/documents/doc-a/pages/2/review')
  assert.equal(write.body.corrected_text,'人工订正A')
  assert.equal(requests.at(-1)!.path,'/api/documents/doc-a/pages/2')
  await workspace.createEvidence({quote:'订正文A',kind:'经典原文',reviewer:'校核人'})
  assert.equal(requests.at(-1)!.body.document_id,'doc-a')
  assert.equal(requests.at(-1)!.body.physical_page,2)
  assert.equal(workspace.targetDocumentId,'doc-b')
  assert.equal(workspace.targetPhysicalPage,8)
 })
})
