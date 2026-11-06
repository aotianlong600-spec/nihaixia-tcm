import test from 'node:test';
import assert from 'node:assert/strict';
import { performOAuth, validateCredential, publicAuthEvent, safeOAuthFailure, checkBrowserCallback, fetchOAuth } from './oauth.mjs';
import {createServer} from 'node:net';
import {spawn,spawnSync} from 'node:child_process';
import {createInterface} from 'node:readline';
import {get} from 'node:http';
import {fileURLToPath} from 'node:url';
import {createServer as createHttpsServer} from 'node:https';
import {mkdtempSync,writeFileSync,unlinkSync,rmdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
const credential={type:'oauth',access:'synthetic-access',refresh:'synthetic-refresh',expires:Date.now()+100000,accountId:'synthetic'};
test('transient device polling errors retry, token redemption and HTTP responses do not',{timeout:3000},async()=>{
 let calls=0,retries=0;
 const failure=()=>Object.assign(new TypeError('fetch failed'),{cause:{code:'ECONNRESET'}});
 const signal=new AbortController().signal;
 const response=await fetchOAuth('https://auth.openai.com/api/accounts/deviceauth/token',{method:'POST'},
  {signal,onRetry:()=>retries++,fetchImpl:async()=>{if(++calls<2)throw failure();return new Response('{}')}});
 assert.equal(response.status,200);assert.equal(calls,2);assert.equal(retries,1);
 calls=0;
 await assert.rejects(fetchOAuth('https://auth.openai.com/oauth/token',{method:'POST'},
  {signal,fetchImpl:async()=>{calls++;throw failure()}}));
 assert.equal(calls,1);
 calls=0;
 assert.equal((await fetchOAuth('https://auth.openai.com/api/accounts/deviceauth/token',{},
  {signal,fetchImpl:async()=>{calls++;return new Response('{}',{status:403})}})).status,403);
 assert.equal(calls,1);
 const aborted=new AbortController();aborted.abort();calls=0;
 await assert.rejects(fetchOAuth('https://auth.openai.com/api/accounts/deviceauth/token',{},
  {signal:aborted.signal,fetchImpl:async()=>{calls++;throw failure()}}));
 assert.equal(calls,1);
});
test('OAuth failures report only stage/code, never upstream response or credentials',()=>{
 const failure=safeOAuthFailure(new Error('OpenAI Codex token exchange failed (403): synthetic-secret-response'), 'exchanging_token');
 assert.deepEqual(failure,{code:'token_http_403',stage:'exchanging_token'});
 assert.deepEqual(safeOAuthFailure(new Error('Failed to extract accountId from token'), 'exchanging_token'),{code:'account_claims',stage:'exchanging_token'});
 assert.deepEqual(safeOAuthFailure(new Error('fetch failed synthetic-secret'), 'exchanging_token'),{code:'token_network',stage:'exchanging_token'});
 assert(!JSON.stringify(failure).includes('synthetic-secret'));
});
test('callback occupancy can be detected without touching that listener',async()=>{
 const server=createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 try {await assert.rejects(checkBrowserCallback(server.address().port), e=>e.code==='callback_busy');}
 finally {await new Promise(resolve=>server.close(resolve));}
});

test('manual callback is supplied privately to the SDK prompt',{timeout:500},async()=>{
 const events=[],value='http://localhost:1455/auth/callback?code=synthetic&state=synthetic';
 const oauth={login:async i=>{assert.equal(await i.prompt({type:'manual_code',signal:new AbortController().signal}),value);return credential;}};
 const result=await performOAuth({op:'login',method:'browser'},{oauth,emit:e=>events.push(e),signal:new AbortController().signal,readAuthorizationInput:async()=>value});
 assert.equal(result.refresh,credential.refresh);
 assert.deepEqual(events,[{type:'waiting_callback'}]);
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

for(const transport of ['stub','https','https-large','manual','refresh']) test(`private IPC completes with exit zero (${transport})`,{timeout:15000},async t=>{
 let child,exit,timer,reader,httpsServer,certificateDirectory,requests=0;
 const events=[];
 let browserStatus,callbackPort,stderr='';
 try {
  const env=Object.fromEntries(['SYSTEMROOT','WINDIR','PATH','TEMP','TMP'].filter(key=>process.env[key]!==undefined).map(key=>[key,process.env[key]]));
  if(transport==='manual') env.SYNTHETIC_OAUTH_MANUAL='1';
  if(transport.startsWith('https')) {
   const generated=spawnSync('python',['-c',`
import json, ipaddress
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
key=ec.generate_private_key(ec.SECP256R1())
name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic OAuth test CA')])
now=datetime.now(timezone.utc)
cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(hours=1)).add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256()))
print(json.dumps({'cert':cert.public_bytes(serialization.Encoding.PEM).decode(),'key':key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()}))
`],{windowsHide:true,encoding:'utf8',timeout:5000,maxBuffer:65536});
   assert.equal(generated.status,0,'synthetic certificate setup failed');
   const certificate=JSON.parse(generated.stdout);
   certificateDirectory=mkdtempSync(join(tmpdir(),'synthetic-oauth-tls-'));
   env.NODE_EXTRA_CA_CERTS=join(certificateDirectory,'ca.pem');
   writeFileSync(env.NODE_EXTRA_CA_CERTS,certificate.cert);
   const payload=Buffer.from(JSON.stringify({'https://api.openai.com/auth':{chatgpt_account_id:'synthetic-account'},padding:transport==='https-large'?'x'.repeat(4200):undefined})).toString('base64url');
   httpsServer=createHttpsServer(certificate,(request,response)=>{
    requests++;request.resume();
    response.writeHead(200,{'Content-Type':'application/json'});
    response.end(JSON.stringify({access_token:`eyJhbGciOiJub25lIn0.${payload}.synthetic`,refresh_token:'synthetic-refresh',expires_in:3600}));
   });
   await new Promise(resolve=>httpsServer.listen(0,'127.0.0.1',resolve));
   env.SYNTHETIC_OAUTH_TOKEN_URL=`https://127.0.0.1:${httpsServer.address().port}/oauth/token`;
  }
  child=spawn(process.execPath,['--import',new URL('./oauth-browser-preload.mjs',import.meta.url).href,fileURLToPath(new URL('./oauth.mjs',import.meta.url))],{windowsHide:true,env,stdio:['pipe','pipe','pipe']});
  exit=new Promise((resolve,reject)=>{child.once('close',(code,signal)=>resolve({code,signal}));child.once('error',reject);});
  timer=setTimeout(()=>child.kill(),7000);
  reader=createInterface({input:child.stdout});
  child.stderr.setEncoding('utf8');child.stderr.on('data',chunk=>{stderr=(stderr+chunk).slice(0,65536);});
  child.stdin.write(JSON.stringify(transport==='refresh'?{op:'refresh',credential:{...credential,accountId:'synthetic-account'}}:{op:'login',method:'browser'})+'\n');
  let authorizationUrl;
  for await(const line of reader) {
   const event=JSON.parse(line);events.push(event);
   if(event.type==='callback_port') callbackPort=event.port;
   if(event.type==='auth_url') {
    const authorization=new URL(event.url);authorizationUrl=authorization;
    const callback=new URL(authorization.searchParams.get('redirect_uri'));
    assert.equal(callback.origin,'http://localhost:1455');
    assert.equal(callback.pathname,'/auth/callback');
    if(transport==='manual')continue;
    assert.equal(Number.isInteger(callbackPort) && callbackPort>0 && callbackPort!==1455,true);
    callback.port=String(callbackPort);
    callback.searchParams.set('state',authorization.searchParams.get('state'));
    callback.searchParams.set('code','synthetic-browser-code');
    browserStatus=await new Promise((resolve,reject)=>{
     get(callback,response=>{response.resume();response.once('end',()=>resolve(response.statusCode));}).once('error',reject);
    });
   }
   if(transport==='manual' && event.type==='waiting_callback') {
    const callback=new URL(authorizationUrl.searchParams.get('redirect_uri'));
    callback.searchParams.set('state',authorizationUrl.searchParams.get('state'));callback.searchParams.set('code','synthetic-browser-code');
    child.stdin.write(JSON.stringify({type:'authorization_input',value:callback.href})+'\n');
   }
  }
  const result=await exit;
  const credentialBytes=Buffer.byteLength(JSON.stringify(events.at(-1)?.credential??{}));
  t.diagnostic(JSON.stringify({transport,event_types:events.map(event=>event.type),exit_code:result.code,credential_bytes:credentialBytes,stderr_marker:stderr.includes('Assertion failed')?'native_assertion':stderr?'stderr_present':null}));
  if(!['manual','refresh'].includes(transport)) assert.equal(browserStatus,200);
  if(transport==='manual')assert.equal(callbackPort,undefined);
  if(transport==='refresh')assert.deepEqual(events.map(e=>e.type),['credential']);
  assert.equal(result.code,0);
  assert.equal(result.signal,null);
  assert.equal(events.at(-1)?.type,'credential');
  assert.equal(events.at(-1)?.credential?.accountId==='synthetic-account',true);
  assert.equal(events.at(-1)?.credential?.refresh==='synthetic-refresh',true);
  if(transport.startsWith('https')) assert.equal(requests,1);
  if(transport==='https-large') assert.equal(credentialBytes>4096 && events.at(-1).credential.access.length<7000,true);
 } finally {
  clearTimeout(timer);reader?.close();child?.stdin.destroy();
  if(child && child.exitCode===null && child.signalCode===null) child.kill();
  if(exit) await exit;
  if(httpsServer) await new Promise(resolve=>{httpsServer.close(resolve);httpsServer.closeAllConnections();});
  if(certificateDirectory) {unlinkSync(join(certificateDirectory,'ca.pem'));rmdirSync(certificateDirectory);}
 }
});
