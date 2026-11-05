import test from 'node:test';
import assert from 'node:assert/strict';
import { runCodex, CODEX_ENDPOINT } from './codex.mjs';
const token='e30.'+Buffer.from(JSON.stringify({'https://api.openai.com/auth':{chatgpt_account_id:'synthetic'}})).toString('base64url')+'.synthetic';
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
