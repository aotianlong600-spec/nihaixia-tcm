// Private IPC only: the Python parent encrypts credential frames; never log this pipe.
import { pathToFileURL } from 'node:url';
import { createServer } from 'node:net';

export function safeOAuthFailure(error, stage) {
  if (['callback_busy', 'callback_unavailable'].includes(error?.code)) return {code:error.code, stage};
  const message=error instanceof Error ? error.message : '';
  const status=message.match(/token (?:exchange|refresh) failed \((\d{3})\)/)?.[1];
  if (status) return {code:`token_http_${status}`, stage};
  if (message.includes('extract accountId')) return {code:'account_claims', stage};
  if (message.includes('response missing fields')) return {code:'token_response', stage};
  if (message==='Invalid credential' || message==='Invalid account') return {code:'credential_invalid', stage:'validating_credential'};
  if (message === 'fetch failed' || ['ETIMEDOUT','ECONNRESET','ENOTFOUND','UND_ERR_CONNECT_TIMEOUT'].includes(error?.cause?.code) || message.startsWith('fetch failed ')) return {code:stage==='exchanging_token'?'token_network':'oauth_network', stage};
  if (stage==='validating_credential') return {code:'credential_invalid', stage};
  return {code:'oauth_failed', stage};
}

export async function checkBrowserCallback(port=1455) {
  await new Promise((resolve,reject)=>{
    const server=createServer();
    server.once('error',error=>reject(Object.assign(new Error('Callback unavailable'),{code:error.code==='EADDRINUSE'?'callback_busy':'callback_unavailable'})));
    server.listen(port,'127.0.0.1',()=>server.close(resolve));
  });
}

export function validateCredential(value) {
  if (!value || value.type !== 'oauth' || !Number.isFinite(value.expires) || value.expires <= 0) throw Error('Invalid credential');
  for (const key of ['access', 'refresh']) if (typeof value[key] !== 'string' || !value[key] || value[key].length > 7000 || /[\x00-\x20\x7f]/.test(value[key])) throw Error('Invalid credential');
  if (typeof value.accountId !== 'string' || !value.accountId || value.accountId.length > 256) throw Error('Invalid account');
  return { type: 'oauth', access: value.access, refresh: value.refresh, expires: value.expires, accountId: value.accountId };
}

function authUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || !['auth.openai.com', 'chatgpt.com'].includes(url.hostname) || url.username || url.password || url.port) throw Error('Invalid authorization URL');
  return url.href;
}

export function publicAuthEvent(event) {
  if (event.type === 'auth_url') return { type: 'auth_url', url: authUrl(event.url) };
  if (event.type === 'device_code') {
    if (typeof event.userCode !== 'string' || !/^[A-Za-z0-9-]{1,64}$/.test(event.userCode)) throw Error('Invalid device code');
    return { type: 'device_code', userCode: event.userCode, verificationUri: authUrl(event.verificationUri) };
  }
  return { type: 'progress', message: '等待OpenAI授权完成' };
}

export async function performOAuth(request, { oauth, emit, signal }) {
  if (!request || !['login', 'refresh'].includes(request.op)) throw Error('Invalid operation');
  if (request.op === 'refresh') return validateCredential(await oauth.refresh(validateCredential(request.credential), signal));
  if (!['device', 'browser'].includes(request.method)) throw Error('Invalid login method');
  const interaction = {
    signal,
    notify: event => emit(publicAuthEvent(event)),
    prompt: prompt => {
      if (prompt.type === 'select') {
        const choice = request.method === 'device' ? 'device_code' : 'browser';
        if (!prompt.options?.some(o => o.id === choice)) throw Error('Unsupported selection');
        return Promise.resolve(choice);
      }
      if (prompt.type !== 'manual_code') return Promise.reject(Error('Unsupported login prompt'));
      emit({ type: 'waiting_callback' });
      // The SDK races this against its localhost callback. No password is entered in our app.
      return new Promise((resolve, reject) => {
        const cancel = () => reject(Error('Login cancelled'));
        if (signal.aborted || prompt.signal?.aborted) return cancel();
        signal.addEventListener('abort', cancel, { once: true });
        prompt.signal?.addEventListener('abort', cancel, { once: true });
      });
    },
  };
  return validateCredential(await oauth.login(interaction, { agentName: 'nihaixia-tcm' }));
}

async function ipcMain() {
  process.env = {};
  if (process.stdout.isTTY) { process.exitCode = 1; return; }
  const controller = new AbortController();
  let input = '', started = false, finished = false, stage='starting';
  let timer = setTimeout(() => stop('timeout'), 10000);
  const write = event => {
    if (['auth_url','device_code'].includes(event.type)) stage='waiting_authorization';
    if (!finished) process.stdout.write(JSON.stringify(event) + '\n');
  };
  const end = event => {
    if (finished) return;
    finished = true; clearTimeout(timer); controller.abort(); process.stdin.pause();
    process.stdout.write(JSON.stringify(event) + '\n', () => process.exit(event.type === 'credential' ? 0 : 1));
  };
  function stop(code) { end({ type: 'error', code, stage }); }
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (target, init) => {
    const url = new URL(target instanceof Request ? target.url : String(target));
    if (url.protocol !== 'https:' || !['auth.openai.com', 'chatgpt.com'].includes(url.hostname) || url.port || url.username || url.password) throw Error('Unexpected OAuth endpoint');
    if (url.pathname==='/oauth/token') {stage='exchanging_token';write({type:'progress',stage});}
    return originalFetch(target, { ...init, redirect: 'manual', signal: controller.signal });
  };
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', data => {
    input += data;
    if (Buffer.byteLength(input) > 65536) return stop('input_limit');
    let newline;
    while ((newline = input.indexOf('\n')) !== -1) {
      const line = input.slice(0, newline); input = input.slice(newline + 1);
      let request;
      try { request = JSON.parse(line); } catch { return stop('invalid_request'); }
      if (started) { if (request.type === 'cancel') stop('cancelled'); else stop('invalid_request'); return; }
      started = true;
      clearTimeout(timer); timer = setTimeout(() => stop('timeout'), request.op === 'refresh' ? 30000 : 15 * 60 * 1000);
      void (async () => {
        try {
          if (request.op==='login' && request.method==='browser') await checkBrowserCallback();
          const { openaiCodexProvider } = await import('@earendil-works/pi-ai/providers/openai-codex');
          const credential = await performOAuth(request, { oauth: openaiCodexProvider().auth.oauth, emit: write, signal: controller.signal });
          stage='validating_credential';write({type:'progress',stage});
          end({ type: 'credential', credential });
        } catch(error) {end({type:'error',...safeOAuthFailure(error,stage)});}
      })();
    }
  });
  process.stdin.on('end', () => stop('cancelled'));
  process.stdout.on('error', () => { controller.abort(); process.exit(1); });
  process.on('uncaughtException', () => stop('oauth_failed'));
  process.on('unhandledRejection', () => stop('oauth_failed'));
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) void ipcMain();
