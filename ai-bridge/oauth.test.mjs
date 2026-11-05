import test from 'node:test';
import assert from 'node:assert/strict';
import { performOAuth, validateCredential, publicAuthEvent } from './oauth.mjs';
const credential={type:'oauth',access:'synthetic-access',refresh:'synthetic-refresh',expires:Date.now()+100000,accountId:'synthetic'};
test('only safe authentication events are public',()=>{
 assert.deepEqual(publicAuthEvent({type:'device_code',userCode:'ABCD-1234',verificationUri:'https://auth.openai.com/codex/device',access:'do-not-echo'}),{type:'device_code',userCode:'ABCD-1234',verificationUri:'https://auth.openai.com/codex/device'});
 assert.throws(()=>publicAuthEvent({type:'auth_url',url:'https://evil.example/callback?access=secret'}));
 assert.throws(()=>validateCredential({...credential,expires:Infinity}));
});
test('device login selects explicit method and returns credentials only to the caller',async()=>{
 const events=[];
 const oauth={login:async(i)=>{assert.equal(await i.prompt({type:'select',options:[{id:'browser'},{id:'device_code'}]}),'device_code');i.notify({type:'device_code',userCode:'ABCD',verificationUri:'https://auth.openai.com/codex/device'});return credential;}};
 const result=await performOAuth({op:'login',method:'device'}, {oauth,emit:e=>events.push(e),signal:new AbortController().signal});
 assert.equal(result.refresh,'synthetic-refresh');assert(!JSON.stringify(events).includes('synthetic-refresh'));
});
test('refresh is explicit and does not read ambient credentials',async()=>{
 const oauth={refresh:async(c)=>({...c,access:'new-synthetic-access',expires:Date.now()+200000})};
 const result=await performOAuth({op:'refresh',credential},{oauth,emit:()=>{},signal:new AbortController().signal});
 assert.equal(result.access,'new-synthetic-access');assert.equal(result.refresh,credential.refresh);
 await assert.rejects(()=>performOAuth({op:'read-global-auth'},{oauth,emit:()=>{},signal:new AbortController().signal}));
});
