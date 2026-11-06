import test from 'node:test';
import assert from 'node:assert/strict';
import { performOAuth, validateCredential, publicAuthEvent, safeOAuthFailure, checkBrowserCallback } from './oauth.mjs';
import {createServer} from 'node:net';
const credential={type:'oauth',access:'synthetic-access',refresh:'synthetic-refresh',expires:Date.now()+100000,accountId:'synthetic'};
test('OAuth failures report only stage/code, never upstream response or credentials',()=>{
 const failure=safeOAuthFailure(new Error('OpenAI Codex token exchange failed (403): synthetic-secret-response'), 'exchanging_token');
 assert.deepEqual(failure,{code:'token_http_403',stage:'exchanging_token'});
 assert.deepEqual(safeOAuthFailure(new Error('Failed to extract accountId from token'), 'exchanging_token'),{code:'account_claims',stage:'exchanging_token'});
 assert.deepEqual(safeOAuthFailure(new Error('fetch failed synthetic-secret'), 'exchanging_token'),{code:'token_network',stage:'exchanging_token'});
 assert(!JSON.stringify(failure).includes('synthetic-secret'));
});
test('occupied callback port fails before showing an authorization URL',async()=>{
 const server=createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 try {await assert.rejects(checkBrowserCallback(server.address().port), e=>e.code==='callback_busy');}
 finally {await new Promise(resolve=>server.close(resolve));}
});
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
