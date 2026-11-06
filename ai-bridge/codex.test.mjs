import test from 'node:test';
import assert from 'node:assert/strict';
import { zstdDecompressSync } from 'node:zlib';
import { runCodex, CODEX_ENDPOINT } from './codex.mjs';
const token='e30.'+Buffer.from(JSON.stringify({'https://api.openai.com/auth':{chatgpt_account_id:'synthetic'}})).toString('base64url')+'.synthetic';
function sentBody(init){
  const raw=init.body;
  const text=typeof raw==='string'?raw:new TextDecoder().decode(zstdDecompressSync(Buffer.from(raw)));
  return JSON.parse(text);
}
function sse(complete=true){
 const item={type:'message',id:'msg1',role:'assistant',status:'completed',content:[{type:'output_text',text:'Synthetic works',annotations:[]}]};
 const events=[{type:'response.created',response:{id:'r1',status:'in_progress',output:[]}},{type:'response.output_item.added',output_index:0,item:{...item,status:'in_progress',content:[]}},{type:'response.content_part.added',output_index:0,content_index:0,part:{type:'output_text',text:'',annotations:[]}},{type:'response.output_text.delta',output_index:0,content_index:0,delta:'Synthetic works'},{type:'response.output_item.done',output_index:0,item}];
 if(complete)events.push({type:'response.completed',response:{id:'r1',status:'completed',output:[item],usage:{input_tokens:5,output_tokens:2,total_tokens:7}}});
 return events.map(e=>'data: '+JSON.stringify(e)+'\n\n').join('');
}
test('Codex text channel uses fixed endpoint, explicit token and completion marker',async()=>{
 const calls=[];let text='';
 const result=await runCodex({model:'synthetic-model',api_key:token,input:'Synthetic only',system:'Return text',maxTokens:4096,timeoutMs:1000},{signal:new AbortController().signal,onDelta:d=>text+=d,fetchImpl:async(url,init)=>{calls.push([String(url),init]);return new Response(sse(),{headers:{'content-type':'text/event-stream'}});}});
 assert.equal(result.text,'Synthetic works');assert.equal(text,'Synthetic works');assert.equal(calls[0][0],CODEX_ENDPOINT);assert.equal(calls[0][1].redirect,'manual');
 assert(!JSON.stringify(calls).includes('refresh'));
});
test('Codex cannot turn an interrupted stream into success',async()=>{
 await assert.rejects(()=>runCodex({model:'synthetic',api_key:token,input:'test',maxTokens:100,timeoutMs:1000},{signal:new AbortController().signal,onDelta:()=>{},fetchImpl:async()=>new Response(sse(false),{headers:{'content-type':'text/event-stream'}})}));
});
test('Codex does not follow a redirect with the subscription credential',async()=>{
 let calls=0;
 await assert.rejects(()=>runCodex({model:'synthetic',api_key:token,input:'test',maxTokens:100,timeoutMs:1000},{signal:new AbortController().signal,onDelta:()=>{},fetchImpl:async()=>{calls++;return new Response(null,{status:302,headers:{location:'https://evil.example'}})}}));
 assert.equal(calls,1);
});
test('known Codex models do not receive a hand-built reasoning effort and may stream without a content type',async()=>{
 let body=null;
 const result=await runCodex({model:'gpt-6.1-sol',api_key:token,input:'Synthetic only',system:'Return text',maxTokens:256,timeoutMs:1000},
  {signal:new AbortController().signal,onDelta:()=>{},fetchImpl:async(url,init)=>{body=sentBody(init);return new Response(new TextEncoder().encode(sse()),{status:200});}});
 assert.equal(result.text,'Synthetic works');
 assert.equal(body.model,'gpt-6.1-sol');
 assert.equal(Object.hasOwn(body,'reasoning'),false,'SDK catalog says this model has no "off" level; inventing effort none is rejected by the backend');
});
test('unknown Codex models also avoid inventing an unsupported reasoning effort',async()=>{
 let body=null;
 await runCodex({model:'unknown-synthetic',api_key:token,input:'Synthetic only',maxTokens:100,timeoutMs:1000},
  {signal:new AbortController().signal,onDelta:()=>{},fetchImpl:async(url,init)=>{body=sentBody(init);return new Response(sse(),{headers:{'content-type':'text/event-stream'}})}});
 assert.equal(Object.hasOwn(body,'reasoning'),false);
});
test('selected Codex thinking effort reaches the actual wire body',async()=>{
 for(const effort of ['low','medium','high','xhigh','max']){
  let body;
  await runCodex({model:'gpt-6.1-sol',reasoning_effort:effort,api_key:token,input:'Synthetic only',maxTokens:100,timeoutMs:1000},
   {signal:new AbortController().signal,onDelta:()=>{},fetchImpl:async(url,init)=>{body=sentBody(init);return new Response(sse(),{headers:{'content-type':'text/event-stream'}})}});
  assert.equal(body.reasoning.effort,effort);
  assert.equal(Object.hasOwn(body.reasoning,'summary'),false,'Disabling a reasoning display must not send unsupported summary off');
  assert.equal(body.tool_choice,'none');
 }
});
test('unsupported and unknown Codex thinking levels fail before sending credentials',async()=>{
 for(const [model,effort] of [['gpt-6.1-sol','none'],['gpt-6.1-sol','minimal'],['unknown-synthetic','high']]){
  let calls=0;
  await assert.rejects(()=>runCodex({model,reasoning_effort:effort,api_key:token,input:'test',maxTokens:100,timeoutMs:1000},
   {signal:new AbortController().signal,onDelta:()=>{},fetchImpl:async()=>{calls++;return new Response(sse())}}),error=>error.code==='unsupported_reasoning');
  assert.equal(calls,0);
 }
});
test('auto delegates to the model default even when SDK supports an off level',async()=>{
 let body;
 await runCodex({model:'gpt-6-sol',reasoning_effort:'auto',api_key:token,input:'test',maxTokens:100,timeoutMs:1000},
  {signal:new AbortController().signal,onDelta:()=>{},fetchImpl:async(url,init)=>{body=sentBody(init);return new Response(sse(),{headers:{'content-type':'text/event-stream'}})}});
 assert.equal(Object.hasOwn(body,'reasoning'),false);
});
test('provider identifiers cannot carry arbitrary input or credentials',async()=>{
 await assert.rejects(()=>runCodex({model:'gpt-6.1-sol',api_key:token,input:'test',maxTokens:100,timeoutMs:1000},
  {signal:new AbortController().signal,onDelta:()=>{},fetchImpl:async()=>new Response(JSON.stringify({error:{code:'syntheticSecret123',type:'syntheticSecret123',param:'syntheticSecret123'}}),{status:400})}),
  error=>{for(const key of ['code','type','param'])assert.equal(error[key],undefined);return true;});
});
test('rate-limit responses expose a bounded retry hint',async()=>{
 await assert.rejects(()=>runCodex({model:'gpt-6.1-sol',api_key:token,input:'Synthetic only',maxTokens:100,timeoutMs:1000},
  {signal:new AbortController().signal,onDelta:()=>{},fetchImpl:async()=>new Response(JSON.stringify({error:{type:'usage_limit_reached'}}),{status:429,headers:{'content-type':'application/json','x-codex-primary-reset-after-seconds':'600'}})}),
  error=>{assert.equal(error.status,429);assert.equal(error.retry_after,600);return true;});
});
test('transport failures expose safe status and machine codes only',async()=>{
 const leak='synthetic input must not leak';
 await assert.rejects(()=>runCodex({model:'gpt-6.1-sol',api_key:token,input:leak,maxTokens:100,timeoutMs:1000},
  {signal:new AbortController().signal,onDelta:()=>{},fetchImpl:async()=>new Response(JSON.stringify({error:{message:leak,code:'unsupported_value',param:'reasoning.effort'}}),{status:400,headers:{'content-type':'application/json'}})}),
  error=>{assert.equal(error.status,400);assert.equal(error.code,'unsupported_value');assert.equal(error.param,'reasoning.effort');assert.equal(String(error.message).includes(leak),false);return true;});
});
