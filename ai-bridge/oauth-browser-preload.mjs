import net from 'node:net';
import http from 'node:http';
import {syncBuiltinESMExports} from 'node:module';

// Test-only child isolation: neither callback preflight nor HTTP listener uses the real login port.
function isolateCallback(server,announce) {
 const listen=server.listen;
 server.listen=function(port,...args) {
  if(port===1455) {
   if(announce) this.once('listening',()=>process.stdout.write(JSON.stringify({type:'callback_port',port:this.address().port})+'\n'));
   port=0;
  }
  return listen.call(this,port,...args);
 };
 return server;
}
const netCreateServer=net.createServer,httpCreateServer=http.createServer;
net.createServer=(...args)=>isolateCallback(netCreateServer(...args),false);
http.createServer=(...args)=>isolateCallback(httpCreateServer(...args),true);
syncBuiltinESMExports();

// Every outbound fetch is synthetic or rejected.
const originalFetch=globalThis.fetch;
const localTokenUrl=process.env.SYNTHETIC_OAUTH_TOKEN_URL;
if(localTokenUrl) {
 const url=new URL(localTokenUrl);
 if(url.protocol!=='https:' || url.hostname!=='127.0.0.1' || !url.port || url.pathname!=='/oauth/token' || url.username || url.password) throw Error('Invalid synthetic TLS endpoint');
}
globalThis.fetch=async (target,init)=>{
 const url=new URL(target instanceof Request?target.url:String(target));
 const body=new URLSearchParams(init?.body);
 if(url.href!=='https://auth.openai.com/oauth/token' || init?.method!=='POST' || body.get('code')!=='synthetic-browser-code') throw Error('Unexpected synthetic OAuth request');
 if(localTokenUrl) return originalFetch(localTokenUrl,{...init,redirect:'manual'});
 const payload=Buffer.from(JSON.stringify({'https://api.openai.com/auth':{chatgpt_account_id:'synthetic-account'}})).toString('base64url');
 return new Response(JSON.stringify({access_token:`eyJhbGciOiJub25lIn0.${payload}.synthetic`,refresh_token:'synthetic-refresh',expires_in:3600}),{status:200,headers:{'Content-Type':'application/json'}});
};
